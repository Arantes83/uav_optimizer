"""
op_lod.py - LOD generation.
"""

import bpy
import bmesh
import re
from bpy.types import Operator


def _tri_count(obj):
    """Count triangles, treating ngons as n-2 triangles."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    count = sum(max(1, len(face.verts) - 2) for face in bm.faces)
    bm.free()
    return count


def _decimate_obj(context, obj, ratio):
    """Apply collapse decimation while respecting UV seams."""
    ratio = min(max(float(ratio), 0.001), 1.0)
    if ratio >= 0.999:
        return

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=0.001)
    bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bpy.ops.object.mode_set(mode='OBJECT')

    mod = obj.modifiers.new(name='LOD_Decimate', type='DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    mod.delimit = {'SEAM'}
    bpy.ops.object.modifier_apply(modifier=mod.name)

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    bpy.ops.mesh.dissolve_degenerate(threshold=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')


def _calc_lod_table(base_tris, target_tris, ratio, max_levels):
    """Return [{'level': N, 'tris': int, 'step_ratio': float}, ...]."""
    if ratio <= 0 or ratio >= 1:
        return []
    if target_tris >= base_tris:
        return []

    levels = []
    current = base_tris
    level = 1
    while level <= max_levels:
        next_tris = max(int(round(base_tris * (ratio ** level))), 4)
        step_ratio = next_tris / max(current, 1)
        levels.append({
            'level': level,
            'tris': next_tris,
            'step_ratio': min(max(step_ratio, 0.001), 0.999),
        })
        current = next_tris
        if next_tris <= target_tris:
            break
        level += 1
    return levels


def _duplicate_mesh_object(obj, new_name, target_collection):
    """Create a real object+mesh copy without touching the source object."""
    new_obj = obj.copy()
    if obj.data is not None:
        new_obj.data = obj.data.copy()
        new_obj.data.name = new_name
    new_obj.name = new_name
    target_collection.objects.link(new_obj)
    return new_obj


_LOD_SUFFIX_RE = re.compile(r'(_LOD\d+|_PREP|_FASTDECIMATE|_TRUEQEM|_EDGELENGTH|_QEM_Simplified)$')


def _resolve_base_name(obj):
    """Resolve the canonical model name from derived pipeline objects."""
    visited = set()
    current = obj

    while current is not None and current.name not in visited:
        visited.add(current.name)
        source_name = current.get("uav_source_object") if hasattr(current, "get") else None
        if isinstance(source_name, str) and source_name:
            source_obj = bpy.data.objects.get(source_name)
            if source_obj is not None:
                current = source_obj
                continue
        break

    name = current.name if current is not None else obj.name
    while True:
        stripped = _LOD_SUFFIX_RE.sub('', name)
        if stripped == name:
            break
        name = stripped

    return name


class UAV_OT_generate_lods(Operator):
    """Generate LODs from the active mesh while keeping the source untouched."""

    bl_idname = 'uav.generate_lods'
    bl_label = 'Generate LODs'
    bl_description = (
        'Generate multiple levels of detail from the active object. '
        'LOD0 is created as a copy, and each next LOD is decimated from the previous one.'
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH' and obj.data.uv_layers.active is not None

    def invoke(self, context, event):
        props = context.scene.uav_lod_props
        obj = context.active_object

        base_tris = _tri_count(obj)
        self._lod_table = _calc_lod_table(
            base_tris,
            props.lod_min_polycount,
            props.lod_ratio,
            props.lod_max_levels,
        )
        if not self._lod_table:
            self.report(
                {'WARNING'},
                'No LODs to generate: the object is already below the target or the parameters are invalid.',
            )
            return {'CANCELLED'}

        self._base_obj = obj
        self._base_tris = base_tris
        self._base_name = _resolve_base_name(obj)
        self._step_idx = 0
        self._created = []

        col_name = props.lod_collection_name.strip() or f'{self._base_name}_LOD'
        if col_name not in bpy.data.collections:
            self._lod_col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(self._lod_col)
        else:
            self._lod_col = bpy.data.collections[col_name]

        self._lod0_obj = _duplicate_mesh_object(self._base_obj, f'{self._base_name}_LOD0', self._lod_col)
        self._prev_obj = self._lod0_obj
        self._created.append(self._lod0_obj)

        self._wm = context.window_manager
        self._wm.progress_begin(0, len(self._lod_table))
        context.window.cursor_set('WAIT')
        self._timer = self._wm.event_timer_add(0.01, window=context.window)
        self._wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        if self._step_idx >= len(self._lod_table):
            self._finish(context)
            final_level = max(0, len(self._created) - 1)
            self.report(
                {'INFO'},
                f'Generated {len(self._created)} LOD object(s) | '
                f'LOD0={self._base_tris:,} tris -> '
                f'LOD{final_level}={self._lod_table[-1]["tris"]:,} tris',
            )
            return {'FINISHED'}

        entry = self._lod_table[self._step_idx]
        try:
            self._process_step(context, entry)
        except Exception as exc:
            self._finish(context)
            self.report({'ERROR'}, f'LOD{entry["level"]} failed: {exc}')
            return {'CANCELLED'}

        self._step_idx += 1
        self._wm.progress_update(self._step_idx)
        return {'RUNNING_MODAL'}

    def _process_step(self, context, entry):
        level = entry['level']
        new_obj = _duplicate_mesh_object(self._prev_obj, f'{self._base_name}_LOD{level}', self._lod_col)
        _decimate_obj(context, new_obj, entry['step_ratio'])
        self._created.append(new_obj)
        self._prev_obj = new_obj

    def _finish(self, context):
        self._wm.progress_end()
        context.window.cursor_set('DEFAULT')
        if hasattr(self, '_timer'):
            self._wm.event_timer_remove(self._timer)

        bpy.ops.object.select_all(action='DESELECT')
        for obj in self._created:
            obj.select_set(True)
        if self._created:
            context.view_layer.objects.active = self._created[0]


class UAV_OT_lod_preview(Operator):
    """Compute and display the LOD table without generating meshes."""

    bl_idname = 'uav.lod_preview'
    bl_label = 'Preview LOD Table'
    bl_description = 'Estimate how many LOD levels will be generated and their triangle counts'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        props = context.scene.uav_lod_props
        obj = context.active_object
        base_tris = _tri_count(obj)
        table = _calc_lod_table(
            base_tris,
            props.lod_min_polycount,
            props.lod_ratio,
            props.lod_max_levels,
        )

        props.preview_base_tris = base_tris
        props.preview_levels = len(table)
        props.preview_final_tris = table[-1]['tris'] if table else base_tris

        self.report({'INFO'}, f'LOD0: {base_tris:,} tris')
        for entry in table:
            self.report(
                {'INFO'},
                f'  LOD{entry["level"]}: ~{entry["tris"]:,} tris (step ratio {entry["step_ratio"]:.3f})',
            )
        if not table:
            self.report({'WARNING'}, 'No LODs would be generated with the current settings.')
        return {'FINISHED'}

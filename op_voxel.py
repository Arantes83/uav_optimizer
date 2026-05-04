import bpy
from bpy.types import Operator


def _capture_source_state(context, obj):
    return {
        "hidden": obj.hide_get(),
        "selected": obj.select_get(),
        "active": context.view_layer.objects.active is obj,
    }


def _restore_source_state(context, obj, state):
    obj.hide_set(state["hidden"])
    obj.select_set(state["selected"])
    if state["active"] or state["selected"]:
        context.view_layer.objects.active = obj


class UAV_OT_voxel_retopo(Operator):
    bl_idname = "uav.voxel_retopo"
    bl_label = "Run Voxel Remesh"
    bl_description = "Generates a fast quad mesh using Blender's native Voxel projection. Adds automatic thickness to prevent holes in open terrains."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props      = context.scene.uav_props
        voxel_size = props.voxel_size
        solidify_thickness = props.voxel_solidify_thickness  # was hardcoded 2.0

        objects_to_process = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not objects_to_process:
            self.report({'WARNING'}, "No valid meshes selected.")
            return {'CANCELLED'}

        # 1. Setup safe collection
        base_name      = objects_to_process[0].name.replace("_QEM", "")
        voxel_col_name = f"{base_name}_Voxel"

        if voxel_col_name not in bpy.data.collections:
            voxel_col = bpy.data.collections.new(voxel_col_name)
            context.scene.collection.children.link(voxel_col)
        else:
            voxel_col = bpy.data.collections[voxel_col_name]

        if context.active_object and context.active_object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        created_objects = []
        restored_sources = []

        self.report({'INFO'}, f"Starting Voxel Remesh (Size: {voxel_size}m, Thickness: {solidify_thickness}m)...")

        # 2. Process each selected object
        for obj in objects_to_process:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            source_state = _capture_source_state(context, obj)

            bpy.ops.object.duplicate()
            new_obj      = context.active_object
            clean_name   = obj.name.replace("_QEM", "")
            new_obj.name = f"{clean_name}_Voxel"

            obj.hide_set(True)
            obj.select_set(False)

            for coll in new_obj.users_collection:
                coll.objects.unlink(new_obj)
            voxel_col.objects.link(new_obj)

            # ------------------------------------------------------------------
            # Fix for open terrains: Solidify before Voxel Remesh
            # Thickness is now exposed via props.voxel_solidify_thickness
            # ------------------------------------------------------------------
            try:
                solid_mod           = new_obj.modifiers.new(name="Voxel_Fix_Thickness", type='SOLIDIFY')
                solid_mod.thickness = solidify_thickness
                solid_mod.offset    = -1.0  # always project downward
                bpy.ops.object.modifier_apply(modifier=solid_mod.name)

                new_obj.data.remesh_voxel_size = voxel_size
                bpy.ops.object.voxel_remesh()

                created_objects.append(context.active_object)

            except Exception as e:
                self.report({'ERROR'}, f"Voxel Remesh failed on {new_obj.name}.")
                print(f"Voxel Error: {e}")
                bpy.data.objects.remove(new_obj, do_unlink=True)
                _restore_source_state(context, obj, source_state)
                restored_sources.append(obj)

        # 3. Cleanup & reselect results
        bpy.ops.object.select_all(action='DESELECT')
        for created_obj in created_objects:
            if created_obj:
                created_obj.select_set(True)
        for source_obj in restored_sources:
            if source_obj:
                source_obj.select_set(True)

        if created_objects:
            context.view_layer.objects.active = created_objects[0]
            self.report({'INFO'}, "Voxel Remesh Completed Successfully without holes!")
            return {'FINISHED'}
        elif restored_sources:
            context.view_layer.objects.active = restored_sources[0]
            return {'CANCELLED'}
        else:
            return {'CANCELLED'}

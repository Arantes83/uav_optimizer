"""
op_bake.py -- High-poly to Low-poly Texture Baking
====================================================
Bakes Albedo (diffuse colour), Ambient Occlusion, or Normal maps
from a high-poly source mesh onto the UVs of a low-poly target mesh.

Pipeline
--------
1. Validate inputs (low-poly active, high-poly set, UVs present)
2. Switch render engine to Cycles
3. Create / update a dedicated bake material on the low-poly object
4. Create a new Image node set as active (the bake target)
5. Select high-poly, set low-poly as active -> run bpy.ops.object.bake()
6. Save the image to disk with the correct suffix (_albedo / _ao / _normal)
7. Restore original render settings

Properties are defined in properties.py (UAVBakeProperties) and 
registered as Scene.uav_bake_props.
"""

import os
import bpy
from bpy.types import Operator
from bpy.props import (
    EnumProperty, IntProperty, FloatProperty,
    BoolProperty, StringProperty, PointerProperty,
)


# ============================================================
#  HELPERS
# ============================================================

_SUFFIX = {
    'ALBEDO': '_albedo',
    'AO':     '_ao',
    'NORMAL': '_normal',
}

_COLORSPACE = {
    'ALBEDO': 'sRGB',
    'AO':     'Non-Color',
    'NORMAL': 'Non-Color',
}

_BLENDER_BAKE_TYPE = {
    'ALBEDO': 'DIFFUSE',
    'AO':     'AO',
    'NORMAL': 'NORMAL',
}


def _resolve_output_dir(props):
    """Return an absolute output directory, falling back to the blend file dir."""
    if props.output_dir.strip():
        return bpy.path.abspath(props.output_dir.strip())
    blend = bpy.data.filepath
    if blend:
        return os.path.dirname(os.path.abspath(blend))
    return bpy.app.tempdir


def _build_image_name(base, bake_type):
    return (base.strip() or "bake") + _SUFFIX[bake_type]


def _get_or_create_bake_material(lowpoly_obj, mat_name):
    """
    Return the bake material for the low-poly object.
    Creates it if absent; always places it in slot 0.
    """
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)

    mat.use_nodes = True

    # Ensure the low-poly object uses this material in slot 0
    if lowpoly_obj.data.materials:
        lowpoly_obj.data.materials[0] = mat
    else:
        lowpoly_obj.data.materials.append(mat)

    # Guarantee a valid Principled BSDF -> Material Output chain
    # (required so Blender can bake DIFFUSE/COLOR without errors)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    out_node = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if out_node is None:
        out_node = nodes.new('ShaderNodeOutputMaterial')
        out_node.location = (300, 0)

    bsdf_node = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf_node is None:
        bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf_node.location = (0, 0)

    # Link BSDF to output if not already linked
    if not out_node.inputs['Surface'].links:
        links.new(bsdf_node.outputs['BSDF'], out_node.inputs['Surface'])

    return mat


def _setup_bake_target_node(mat, image, bake_type):
    """
    Insert (or reuse) a dedicated Image Texture node and make it the
    active (selected) node — the bake destination.
    The node is intentionally NOT connected so it does not affect shading.
    """
    nodes = mat.node_tree.nodes
    NODE_NAME = "UAV_BakeTarget"

    img_node = nodes.get(NODE_NAME)
    if img_node is None:
        img_node = nodes.new('ShaderNodeTexImage')
        img_node.name = NODE_NAME
        img_node.location = (-300, 200)

    img_node.image = image

    # Colour space
    if bake_type in ('AO', 'NORMAL'):
        img_node.image.colorspace_settings.name = 'Non-Color'
    else:
        img_node.image.colorspace_settings.name = 'sRGB'

    # Deselect all, select only this node so Blender bakes into it
    for n in nodes:
        n.select = False
    img_node.select = True
    nodes.active = img_node

    return img_node


def _create_bake_image(name, size, bake_type):
    """Remove any stale image with the same name and create a fresh one."""
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    is_normal = (bake_type == 'NORMAL')
    is_albedo = (bake_type == 'ALBEDO')

    image = bpy.data.images.new(
        name,
        width=size,
        height=size,
        alpha=is_albedo,
        float_buffer=is_normal,  # 32-bit float for normals
    )
    image.file_format = 'PNG'
    image.colorspace_settings.name = _COLORSPACE[bake_type]
    return image


def _save_image(image, out_dir, filename):
    """Save a Blender image to disk as PNG. Returns the absolute path."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename + ".png")

    # For float (normal) images Blender needs file_format and use_zbuffer cleared
    image.filepath_raw = path
    image.file_format = 'PNG'

    # PNG settings: 16-bit for normals, 8-bit for others
    scene = bpy.context.scene
    orig_fmt    = scene.render.image_settings.file_format
    orig_depth  = scene.render.image_settings.color_depth
    orig_color  = scene.render.image_settings.color_mode

    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode  = 'RGB'
    scene.render.image_settings.color_depth = '16' if image.is_float else '8'

    image.save_render(path)

    # Restore
    scene.render.image_settings.file_format = orig_fmt
    scene.render.image_settings.color_depth = orig_depth
    scene.render.image_settings.color_mode  = orig_color

    return path


# ============================================================
#  OPERATOR
# ============================================================

class UAV_OT_detail_baking(Operator):
    bl_idname  = "uav.detail_baking"
    bl_label   = "Bake Texture"
    bl_description = (
        "Bake Albedo, AO, or Normal map from the high-poly source mesh "
        "onto the UV-unwrapped low-poly active object using Cycles"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            obj.mode == 'OBJECT'
        )

    # ----------------------------------------------------------
    def execute(self, context):
        import time
        props   = context.scene.uav_bake_props
        lowpoly = context.active_object

        # ------ Validate ----------------------------------------
        errors = self._validate(context, props, lowpoly)
        if errors:
            for e in errors:
                self.report({'ERROR'}, e)
            return {'CANCELLED'}

        highpoly  = props.highpoly_object
        bake_type = props.bake_type
        size      = int(props.texture_size)
        base_name = props.texture_name.strip() or lowpoly.name
        img_name  = _build_image_name(base_name, bake_type)
        out_dir   = _resolve_output_dir(props)
        mat_name  = f"{lowpoly.name}_BakeMat"

        # ------ Save render state --------------------------------
        orig_engine  = context.scene.render.engine
        orig_samples = context.scene.cycles.samples if hasattr(context.scene, 'cycles') else 16

        t_start = time.time()

        try:
            # ------ Switch to Cycles ----------------------------
            context.scene.render.engine = 'CYCLES'
            context.scene.cycles.samples = props.samples

            # ------ Bake settings -------------------------------
            bk = context.scene.render.bake
            bk.use_selected_to_active = True
            bk.cage_extrusion         = props.cage_extrusion
            bk.max_ray_distance       = props.max_ray_distance
            bk.margin                 = props.margin
            bk.margin_type            = 'EXTEND'
            bk.use_clear              = True
            bk.target                 = 'IMAGE_TEXTURES'

            # ------ Create image --------------------------------
            image    = _create_bake_image(img_name, size, bake_type)

            # ------ Material setup ------------------------------
            mat      = _get_or_create_bake_material(lowpoly, mat_name)
            _setup_bake_target_node(mat, image, bake_type)

            # ------ Select high → active low --------------------
            bpy.ops.object.select_all(action='DESELECT')
            highpoly.select_set(True)
            lowpoly.select_set(True)
            context.view_layer.objects.active = lowpoly

            # ------ Run bake ------------------------------------
            blender_type = _BLENDER_BAKE_TYPE[bake_type]

            if bake_type == 'ALBEDO':
                bpy.ops.object.bake(
                    type='DIFFUSE',
                    pass_filter={'COLOR'},
                    use_selected_to_active=True,
                )
            elif bake_type == 'AO':
                bpy.ops.object.bake(
                    type='AO',
                    use_selected_to_active=True,
                )
            else:  # NORMAL
                bpy.ops.object.bake(
                    type='NORMAL',
                    normal_space=props.normal_space,
                    use_selected_to_active=True,
                )

            # ------ Save ----------------------------------------
            out_path = _save_image(image, out_dir, img_name)

            # ------ Update image datablock path -----------------
            image.filepath = out_path
            image.pack()   # also keep in .blend

            elapsed = time.time() - t_start

            # ------ Store results -------------------------------
            props.last_bake_type = bake_type
            props.last_bake_path = out_path
            props.last_bake_time = elapsed
            props.last_bake_ok   = True

            self.report(
                {'INFO'},
                f"Baked {bake_type} ({size}px) -> {out_path} [{elapsed:.1f}s]"
            )
            return {'FINISHED'}

        except Exception as exc:
            props.last_bake_ok = False
            self.report({'ERROR'}, f"Bake failed: {exc}")
            return {'CANCELLED'}

        finally:
            # Always restore render state
            context.scene.render.engine = orig_engine
            if hasattr(context.scene, 'cycles'):
                context.scene.cycles.samples = orig_samples

    # ----------------------------------------------------------
    def _validate(self, context, props, lowpoly):
        errors = []

        if lowpoly is None or lowpoly.type != 'MESH':
            errors.append("Active object must be the low-poly mesh.")
            return errors  # can't continue

        if props.highpoly_object is None:
            errors.append("No high-poly source set. Assign it in the Bake panel.")

        if props.highpoly_object == lowpoly:
            errors.append("High-poly source and low-poly target cannot be the same object.")

        if not lowpoly.data.uv_layers.active:
            errors.append(f"'{lowpoly.name}' has no active UV map. Run Unwrap first.")

        if not context.preferences.addons.get('cycles'):
            errors.append("Cycles is not enabled. Enable it in Preferences -> Add-ons.")

        if props.texture_size not in {'512', '1024', '2048', '4096'}:
            errors.append("Invalid texture size.")

        out_dir = _resolve_output_dir(props)
        if not out_dir:
            errors.append("No output directory. Save the .blend file or set an output folder.")

        return errors

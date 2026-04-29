"""
op_export.py - Engine-ready FBX export for the UAV asset pipeline.
"""

import os
import re
import shutil
import time

import bpy
from bpy.types import Operator


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".hdr"}


def _safe_name(value, fallback="asset"):
    name = _SAFE_NAME_RE.sub("_", (value or "").strip())
    name = name.strip("._")
    return name or fallback


def _resolve_output_dir(props):
    if props.output_dir.strip():
        return bpy.path.abspath(props.output_dir.strip())
    if bpy.data.filepath:
        return os.path.dirname(os.path.abspath(bpy.data.filepath))
    return bpy.app.tempdir


def _find_lod_collection(context, props):
    if props.collection_name.strip():
        return bpy.data.collections.get(props.collection_name.strip())

    lod_props = getattr(context.scene, "uav_lod_props", None)
    if lod_props and lod_props.lod_collection_name.strip():
        collection = bpy.data.collections.get(lod_props.lod_collection_name.strip())
        if collection is not None:
            return collection

    active = context.active_object
    if active is not None:
        base_name = active.name.split("_LOD")[0]
        return bpy.data.collections.get(f"{base_name}_LODs")
    return None


def _objects_from_collection(collection):
    objects = []
    for obj in collection.all_objects:
        if obj.type in {"MESH", "ARMATURE", "EMPTY"}:
            objects.append(obj)
    return sorted(objects, key=lambda item: item.name)


def _collect_export_objects(context, props):
    if props.scope == "ACTIVE":
        obj = context.active_object
        return [obj] if obj is not None and obj.type in {"MESH", "ARMATURE", "EMPTY"} else []

    if props.scope == "SELECTED":
        return [
            obj for obj in context.selected_objects
            if obj.type in {"MESH", "ARMATURE", "EMPTY"}
        ]

    collection = _find_lod_collection(context, props)
    if collection is None:
        return []
    return _objects_from_collection(collection)


def _default_asset_name(context, props, objects):
    if props.asset_name.strip():
        return _safe_name(props.asset_name)
    if props.scope == "LOD_COLLECTION":
        collection = _find_lod_collection(context, props)
        if collection is not None:
            return _safe_name(collection.name)
    if objects:
        return _safe_name(objects[0].name.split("_LOD")[0])
    return "uav_asset"


def _iter_image_nodes(node_tree, visited=None):
    if node_tree is None:
        return
    if visited is None:
        visited = set()
    pointer = node_tree.as_pointer()
    if pointer in visited:
        return
    visited.add(pointer)

    for node in node_tree.nodes:
        if node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None:
            yield node.image
        elif node.type == "GROUP" and getattr(node, "node_tree", None) is not None:
            yield from _iter_image_nodes(node.node_tree, visited)


def _collect_material_images(objects):
    images = []
    seen = set()
    for obj in objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material is None or material.node_tree is None:
                continue
            for image in _iter_image_nodes(material.node_tree):
                pointer = image.as_pointer()
                if pointer not in seen:
                    seen.add(pointer)
                    images.append(image)
    return images


def _image_filename(image):
    raw_path = bpy.path.abspath(image.filepath) if image.filepath else ""
    raw_name = os.path.basename(raw_path) if raw_path else image.name
    stem, ext = os.path.splitext(raw_name)
    ext = ext.lower()
    if ext not in _IMAGE_EXTENSIONS:
        ext = ".png"
    return _safe_name(stem, fallback="texture") + ext


def _save_generated_image(image, target_path):
    original_path = getattr(image, "filepath_raw", "")
    original_format = getattr(image, "file_format", "PNG")
    _, ext = os.path.splitext(target_path)
    format_map = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".tga": "TARGA",
        ".tif": "TIFF",
        ".tiff": "TIFF",
        ".exr": "OPEN_EXR",
        ".hdr": "HDR",
    }
    try:
        image.filepath_raw = target_path
        image.file_format = format_map.get(ext.lower(), "PNG")
        image.save()
    finally:
        try:
            image.filepath_raw = original_path
            image.file_format = original_format
        except Exception:
            pass


def _copy_textures(objects, output_dir, texture_subdir):
    texture_dir = os.path.join(output_dir, _safe_name(texture_subdir, fallback="Textures"))
    copied = []
    used_targets = set()

    for image in _collect_material_images(objects):
        os.makedirs(texture_dir, exist_ok=True)
        target_path = os.path.join(texture_dir, _image_filename(image))
        stem, ext = os.path.splitext(target_path)
        counter = 1
        while os.path.normcase(target_path) in used_targets:
            target_path = f"{stem}_{counter:02d}{ext}"
            counter += 1
        used_targets.add(os.path.normcase(target_path))

        source_path = bpy.path.abspath(image.filepath) if image.filepath else ""

        if source_path and os.path.isfile(source_path):
            if os.path.abspath(source_path) != os.path.abspath(target_path):
                shutil.copy2(source_path, target_path)
        else:
            _save_generated_image(image, target_path)
        copied.append(target_path)

    return texture_dir if copied else "", copied


def _supported_fbx_kwargs(kwargs):
    try:
        supported = set(bpy.ops.export_scene.fbx.get_rna_type().properties.keys())
    except Exception:
        return kwargs
    return {key: value for key, value in kwargs.items() if key in supported}


def _fbx_kwargs_for_target(target, filepath, props):
    if target == "UNREAL":
        preset = {
            "axis_forward": "-X",
            "axis_up": "Z",
            "apply_scale_options": "FBX_SCALE_NONE",
        }
    else:
        preset = {
            "axis_forward": "-Z",
            "axis_up": "Y",
            "apply_scale_options": "FBX_SCALE_UNITS",
        }

    kwargs = {
        "filepath": filepath,
        "check_existing": False,
        "filter_glob": "*.fbx",
        "use_selection": True,
        "global_scale": props.global_scale,
        "apply_unit_scale": True,
        "apply_scale_options": preset["apply_scale_options"],
        "bake_space_transform": False,
        "object_types": {"EMPTY", "MESH", "ARMATURE"},
        "use_mesh_modifiers": props.apply_modifiers,
        "use_mesh_modifiers_render": props.apply_modifiers,
        "mesh_smooth_type": "FACE",
        "use_tspace": props.export_tangents,
        "use_triangles": props.triangulate,
        "use_custom_props": props.use_custom_props,
        "add_leaf_bones": False,
        "primary_bone_axis": "Y",
        "secondary_bone_axis": "X",
        "use_armature_deform_only": True,
        "bake_anim": False,
        "path_mode": "AUTO",
        "embed_textures": False,
        "batch_mode": "OFF",
        "use_batch_own_dir": True,
        "use_metadata": True,
        "axis_forward": preset["axis_forward"],
        "axis_up": preset["axis_up"],
    }
    return _supported_fbx_kwargs(kwargs)


def _stash_context(context):
    return {
        "active_object": context.view_layer.objects.active,
        "selected_objects": list(context.selected_objects),
        "mode": context.object.mode if context.object is not None else "OBJECT",
    }


def _restore_context(context, state):
    try:
        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    bpy.ops.object.select_all(action="DESELECT")
    for obj in state["selected_objects"]:
        if obj is not None and obj.name in bpy.data.objects:
            obj.select_set(True)
    active = state["active_object"]
    if active is not None and active.name in bpy.data.objects:
        context.view_layer.objects.active = active

    if state["mode"] != "OBJECT" and context.view_layer.objects.active is not None:
        try:
            bpy.ops.object.mode_set(mode=state["mode"])
        except Exception:
            pass


class UAV_OT_export_engine_asset(Operator):
    """Export the processed asset using Unity or Unreal FBX conventions."""

    bl_idname = "uav.export_engine_asset"
    bl_label = "Export Engine Asset"
    bl_description = "Export the active, selected, or generated LOD asset as an engine-ready FBX package"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def _validate(self, props, objects, output_dir):
        errors = []
        if not objects:
            errors.append("Nenhum objeto valido encontrado para exportacao.")
        if not output_dir:
            errors.append("Diretorio de saida invalido.")
        mesh_count = sum(1 for obj in objects if obj.type == "MESH")
        if mesh_count == 0:
            errors.append("A exportacao precisa conter pelo menos uma malha.")
        for obj in objects:
            if obj.type == "MESH" and obj.data.uv_layers.active is None:
                errors.append(f"'{obj.name}' nao possui UV map ativo.")
        return errors

    def execute(self, context):
        props = context.scene.uav_export_props
        state = _stash_context(context)
        start_time = time.perf_counter()

        props.last_export_ok = False
        props.last_export_path = ""
        props.last_texture_dir = ""
        props.last_object_count = 0

        objects = _collect_export_objects(context, props)
        output_dir = _resolve_output_dir(props)
        asset_name = _default_asset_name(context, props, objects)
        filepath = os.path.join(output_dir, asset_name + ".fbx")

        errors = self._validate(props, objects, output_dir)
        if errors:
            for error in errors:
                self.report({"ERROR"}, error)
            return {"CANCELLED"}

        try:
            os.makedirs(output_dir, exist_ok=True)
            if context.object is not None and context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            bpy.ops.object.select_all(action="DESELECT")
            for obj in objects:
                obj.select_set(True)
            context.view_layer.objects.active = next((obj for obj in objects if obj.type == "MESH"), objects[0])

            texture_dir = ""
            copied_textures = []
            if props.include_textures:
                texture_dir, copied_textures = _copy_textures(objects, output_dir, props.texture_subdir)

            kwargs = _fbx_kwargs_for_target(props.target_engine, filepath, props)
            bpy.ops.export_scene.fbx(**kwargs)

            props.last_export_ok = True
            props.last_export_path = filepath
            props.last_texture_dir = texture_dir
            props.last_object_count = len(objects)
            props.last_export_time = time.perf_counter() - start_time

            self.report(
                {"INFO"},
                (
                    f"Exportado {asset_name}.fbx para {props.target_engine} "
                    f"({len(objects)} objeto(s), {len(copied_textures)} textura(s))"
                ),
            )
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Exportacao falhou: {exc}")
            import traceback
            traceback.print_exc()
            return {"CANCELLED"}
        finally:
            _restore_context(context, state)

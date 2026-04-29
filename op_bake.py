"""
op_bake.py - High-poly to low-poly baking with BakeLab-style pass extraction.
"""

import os
import time

import bpy
from bpy.types import Operator

TMP_MAT_SUFFIX = "_UAVBakeTmp"
TMP_NODE_NAME = "UAV_BakeTarget"
BAKE_MAT_SUFFIX = "_baking"
FINAL_NODE_PREFIX = "UAV_Baked_"
FINAL_UV_NODE_NAME = FINAL_NODE_PREFIX + "UVMap"
FINAL_AO_MIX_NODE_NAME = FINAL_NODE_PREFIX + "AOMix"
FINAL_NORMALMAP_NODE_NAME = FINAL_NODE_PREFIX + "NormalMap"

MAP_SETTINGS = {
    "ALBEDO": {
        "label": "Albedo",
        "suffix": "_albedo",
        "colorspace": "sRGB",
        "float_buffer": False,
        "blender_type": "EMIT",
        "emit_passes": ["albedo", "color", "base color", "col", "paint color"],
    },
    "AO": {
        "label": "Ambient Occlusion",
        "suffix": "_ao",
        "colorspace": "Non-Color",
        "float_buffer": False,
        "blender_type": "AO",
    },
    "NORMAL": {
        "label": "Normal",
        "suffix": "_normal",
        "colorspace": "Non-Color",
        "float_buffer": True,
        "blender_type": "NORMAL",
    },
    "ROUGHNESS": {
        "label": "Roughness",
        "suffix": "_roughness",
        "colorspace": "Non-Color",
        "float_buffer": False,
        "blender_type": "ROUGHNESS",
    },
    "METALLIC": {
        "label": "Metallic",
        "suffix": "_metallic",
        "colorspace": "Non-Color",
        "float_buffer": False,
        "blender_type": "EMIT",
        "emit_passes": ["metallic", "metalness", "metallic weight"],
    },
    "EMISSION": {
        "label": "Emission",
        "suffix": "_emission",
        "colorspace": "sRGB",
        "float_buffer": False,
        "blender_type": "EMIT",
    },
}

PBR_MAP_ORDER = (
    "ALBEDO",
    "AO",
    "NORMAL",
    "ROUGHNESS",
    "METALLIC",
    "EMISSION",
)

MANAGED_NODE_NAMES = {
    TMP_NODE_NAME,
    FINAL_UV_NODE_NAME,
    FINAL_AO_MIX_NODE_NAME,
    FINAL_NORMALMAP_NODE_NAME,
    FINAL_NODE_PREFIX + "ALBEDO",
    FINAL_NODE_PREFIX + "AO",
    FINAL_NODE_PREFIX + "NORMAL",
    FINAL_NODE_PREFIX + "ROUGHNESS",
    FINAL_NODE_PREFIX + "METALLIC",
    FINAL_NODE_PREFIX + "EMISSION",
}


def _find_output_node(nodes):
    for node in nodes:
        if node.type == "OUTPUT_MATERIAL" and node.is_active_output:
            return node
    for node in nodes:
        if node.type == "OUTPUT_MATERIAL":
            return node
    return None


def _find_principled_node(nodes):
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def _find_socket_by_name(sockets, *names):
    wanted = {name.casefold() for name in names}
    for socket in sockets:
        if socket.name.casefold() in wanted:
            return socket
    return None


def _get_socket_by_identifier(sockets, identifier):
    for socket in sockets:
        if socket.identifier == identifier:
            return socket
    return None


def _copy_node(dst_nodes, node):
    try:
        new_node = dst_nodes.new(type=node.bl_idname)
    except Exception:
        return None
    for member in dir(node):
        try:
            value = getattr(node, member)
            if value is None:
                continue
            setattr(new_node, member, value)
        except Exception:
            pass
    for src_input in node.inputs:
        dst_input = _get_socket_by_identifier(new_node.inputs, src_input.identifier)
        if dst_input is not None and hasattr(src_input, "default_value") and hasattr(dst_input, "default_value"):
            try:
                dst_input.default_value = src_input.default_value
            except Exception:
                pass
    return new_node


def _extract_group_nodes_recursive(group_node, group_in, group_out, nodes, links, node_group, node_cache):
    if group_node.name in node_cache:
        return node_cache[group_node.name]

    node = _copy_node(nodes, group_node)
    node_cache[group_node.name] = node
    if node is None:
        return None

    for src_input in group_node.inputs:
        dst_input = _get_socket_by_identifier(node.inputs, src_input.identifier)
        if dst_input is None:
            continue
        for link in src_input.links:
            from_node = link.from_node
            if from_node == group_in:
                group_input = _get_socket_by_identifier(node_group.inputs, link.from_socket.identifier)
                if group_input is None:
                    continue
                if hasattr(dst_input, "default_value") and hasattr(group_input, "default_value"):
                    try:
                        dst_input.default_value = group_input.default_value
                    except Exception:
                        pass
                for group_link in group_input.links:
                    links.new(group_link.from_socket, dst_input)
            else:
                link_node = _extract_group_nodes_recursive(
                    from_node, group_in, group_out, nodes, links, node_group, node_cache
                )
                if link_node is not None:
                    link_output = _get_socket_by_identifier(link_node.outputs, link.from_socket.identifier)
                    if link_output is not None:
                        links.new(link_output, dst_input)

    for src_output in group_node.outputs:
        dst_output = _get_socket_by_identifier(node.outputs, src_output.identifier)
        if dst_output is None:
            continue
        for link in src_output.links:
            to_node = link.to_node
            if to_node == group_out:
                group_output = _get_socket_by_identifier(node_group.outputs, link.to_socket.identifier)
                if group_output is None:
                    continue
                for group_link in group_output.links:
                    links.new(dst_output, group_link.to_socket)
            else:
                link_node = _extract_group_nodes_recursive(
                    to_node, group_in, group_out, nodes, links, node_group, node_cache
                )
                if link_node is not None:
                    link_input = _get_socket_by_identifier(link_node.inputs, link.to_socket.identifier)
                    if link_input is not None:
                        links.new(dst_output, link_input)

    return node


def _ungroup_nodes(node_tree):
    nodes = node_tree.nodes
    links = node_tree.links
    while True:
        group_exists = False
        current_nodes = [node for node in nodes]
        for node in current_nodes:
            if node.type != "GROUP" or node.node_tree is None:
                continue
            group_exists = True
            group_nodes = node.node_tree.nodes
            group_in = None
            group_out = None
            for group_node in group_nodes:
                if group_node.type == "GROUP_INPUT":
                    group_in = group_node
                elif group_node.type == "GROUP_OUTPUT":
                    group_out = group_node
            if group_in is None or group_out is None:
                continue
            node_cache = {}
            for group_node in group_nodes:
                if group_node in {group_in, group_out}:
                    continue
                _extract_group_nodes_recursive(group_node, group_in, group_out, nodes, links, node, node_cache)
            nodes.remove(node)
        if not group_exists:
            break


def _rewire_recursive(node, dst_socket, nodes, links, pass_names):
    shader_inputs = [socket for socket in node.inputs if socket.type == "SHADER"]
    if not shader_inputs:
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs[0].default_value = (0, 0, 0, 1)
        if dst_socket is not None:
            links.new(emit.outputs[0], dst_socket)
        for pass_name in pass_names:
            for socket in node.inputs:
                if socket.name.casefold() != pass_name:
                    continue
                if socket.links:
                    links.new(socket.links[0].from_socket, emit.inputs[0])
                else:
                    if socket.type == "RGBA":
                        emit.inputs[0].default_value = tuple(socket.default_value)
                    elif socket.type == "VECTOR":
                        emit.inputs[0].default_value = (
                            socket.default_value[0],
                            socket.default_value[1],
                            socket.default_value[2],
                            1.0,
                        )
                    elif socket.type == "VALUE":
                        value = float(socket.default_value)
                        emit.inputs[0].default_value = (value, value, value, 1.0)
                return
        return

    for socket in shader_inputs:
        if socket.links:
            _rewire_recursive(socket.links[0].from_node, socket.links[0].to_socket, nodes, links, pass_names)


def _rewire_passes_to_emit(mat, pass_names):
    if mat.node_tree is None:
        return
    _ungroup_nodes(mat.node_tree)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    output = _find_output_node(nodes)
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs[0].default_value = (0, 0, 0, 1)
        links.new(emit.outputs[0], output.inputs[0])
        return
    _rewire_recursive(output, None, nodes, links, [name.casefold() for name in pass_names])


def _ensure_slots(obj):
    if len(obj.material_slots) == 0:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.material_slot_add()
    for slot in obj.material_slots:
        if slot.material is None:
            mat = bpy.data.materials.new(obj.name + BAKE_MAT_SUFFIX)
            mat.use_nodes = True
            slot.material = mat


def _capture_material_assignment(obj):
    return {
        "slot_count": len(obj.material_slots),
        "materials": [slot.material for slot in obj.material_slots],
    }


def _restore_material_assignment(obj, assignment):
    if obj is None or assignment is None or obj.name not in bpy.data.objects:
        return

    target_slot_count = assignment["slot_count"]
    target_materials = assignment["materials"]

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    while len(obj.material_slots) < target_slot_count:
        bpy.ops.object.material_slot_add()

    while len(obj.material_slots) > target_slot_count:
        obj.active_material_index = len(obj.material_slots) - 1
        bpy.ops.object.material_slot_remove()

    for index, material in enumerate(target_materials):
        obj.material_slots[index].material = material


def _pick_source_material(obj):
    if obj.active_material is not None:
        return obj.active_material
    for slot in obj.material_slots:
        if slot.material is not None:
            return slot.material
    return None


def _ensure_bake_material_assigned(lowpoly):
    _ensure_slots(lowpoly)

    source_material = _pick_source_material(lowpoly)
    original_materials = {slot.material for slot in lowpoly.material_slots if slot.material is not None}
    mat_name = lowpoly.name + BAKE_MAT_SUFFIX
    bake_material = bpy.data.materials.get(mat_name)
    if bake_material is not None and bake_material not in original_materials:
        try:
            bpy.data.materials.remove(bake_material)
        except Exception:
            pass
        bake_material = None
    if source_material is not None:
        bake_material = source_material.copy()
        bake_material.name = mat_name
    else:
        bake_material = bpy.data.materials.new(mat_name)
    bake_material.use_nodes = True

    for slot in lowpoly.material_slots:
        slot.material = bake_material

    return bake_material


def _reserve_materials(obj):
    slots = list(obj.material_slots)
    originals = [slot.material for slot in slots]
    copies = []
    for slot in slots:
        if slot.material is not None:
            copy_mat = slot.material.copy()
            copy_mat.name = slot.material.name + TMP_MAT_SUFFIX
            slot.material = copy_mat
            copies.append(copy_mat)
        else:
            copies.append(None)
    return slots, originals, copies


def _restore_materials(slots, originals, copies):
    for index, slot in enumerate(slots):
        slot.material = originals[index]
    for copy_mat in copies:
        if copy_mat is not None:
            try:
                bpy.data.materials.remove(copy_mat)
            except Exception:
                pass


def _insert_bake_target_node(mat, image, mesh_name):
    nodes = mat.node_tree.nodes
    for node_name in (TMP_NODE_NAME, f"{mesh_name}_BakeTarget"):
        node = nodes.get(node_name)
        if node is not None:
            try:
                nodes.remove(node)
            except Exception:
                pass
    node = nodes.new("ShaderNodeTexImage")
    node.name = f"{mesh_name}_BakeTarget"
    node.label = f"{mesh_name} Bake Target"
    node.location = (-400, 300)
    node.image = image
    for other in nodes:
        other.select = False
    node.select = True
    nodes.active = node


def _prepare_lowpoly_mats(lowpoly, image):
    _ensure_slots(lowpoly)
    for slot in lowpoly.material_slots:
        if slot.material is None:
            mat = bpy.data.materials.new(lowpoly.name + BAKE_MAT_SUFFIX)
            mat.use_nodes = True
            slot.material = mat
        mat = slot.material
        mat.use_nodes = True
        if mat.node_tree is None:
            continue
        output = _find_output_node(mat.node_tree.nodes)
        if output is None:
            output = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
        surface = _find_socket_by_name(output.inputs, "Surface")
        if surface is not None and not surface.links:
            principled = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
            mat.node_tree.links.new(principled.outputs["BSDF"], surface)
        _clear_managed_nodes(mat.node_tree.nodes)
        _insert_bake_target_node(mat, image, lowpoly.name)


def _set_image_colorspace(image, colorspace):
    try:
        image.colorspace_settings.name = colorspace
    except Exception:
        fallback = {
            "sRGB": "sRGB EOTF",
            "Non-Color": "Non-Colour Data",
        }.get(colorspace)
        if fallback:
            try:
                image.colorspace_settings.name = fallback
            except Exception:
                pass


def _create_bake_image(name, size, map_id):
    settings = MAP_SETTINGS[map_id]
    existing = bpy.data.images.get(name)
    if existing is not None:
        image = existing
        try:
            if image.size[0] != size or image.size[1] != size:
                image.scale(size, size)
        except Exception:
            pass
    else:
        image = bpy.data.images.new(
            name,
            width=size,
            height=size,
            alpha=False,
            float_buffer=settings["float_buffer"],
        )
    _set_image_colorspace(image, settings["colorspace"])
    return image


def _resolve_output_dir(props):
    if props.output_dir.strip():
        return bpy.path.abspath(props.output_dir.strip())
    blend_path = bpy.data.filepath
    if blend_path:
        return os.path.dirname(os.path.abspath(blend_path))
    return bpy.app.tempdir


def _save_image(image, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name + ".png")
    scene = bpy.context.scene
    original_format = scene.render.image_settings.file_format
    original_depth = scene.render.image_settings.color_depth
    original_color = scene.render.image_settings.color_mode
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "16" if image.is_float else "8"
    image.save_render(path)
    scene.render.image_settings.file_format = original_format
    scene.render.image_settings.color_depth = original_depth
    scene.render.image_settings.color_mode = original_color
    return path


def _load_saved_image(image, out_path, image_name, map_id):
    loaded_image = image
    try:
        loaded_image.filepath_raw = out_path
    except Exception:
        pass
    try:
        loaded_image.reload()
    except Exception:
        try:
            loaded_image = bpy.data.images.load(out_path, check_existing=True)
        except Exception:
            loaded_image = bpy.data.images.get(image_name) or image
    if loaded_image.name != image_name:
        try:
            loaded_image.name = image_name
        except Exception:
            pass
    loaded_image.filepath = out_path
    try:
        loaded_image.source = "FILE"
    except Exception:
        pass
    _set_image_colorspace(loaded_image, MAP_SETTINGS[map_id]["colorspace"])
    return loaded_image


def _map_suffix(map_id):
    return MAP_SETTINGS[map_id]["suffix"]


def _map_label(map_id):
    return MAP_SETTINGS[map_id]["label"]


def _collect_bake_queue(props):
    if props.bake_type != "PBR":
        return [props.bake_type]
    queue = []
    for map_id, attr in (
        ("ALBEDO", "pbr_use_albedo"),
        ("AO", "pbr_use_ao"),
        ("NORMAL", "pbr_use_normal"),
        ("ROUGHNESS", "pbr_use_roughness"),
        ("METALLIC", "pbr_use_metallic"),
        ("EMISSION", "pbr_use_emission"),
    ):
        if getattr(props, attr, False):
            queue.append(map_id)
    return queue


def _stash_context_state(context):
    scene = context.scene
    bake = scene.render.bake
    state = {
        "active_object": context.view_layer.objects.active,
        "selected_objects": list(context.selected_objects),
        "render_engine": scene.render.engine,
        "cycles_samples": getattr(scene.cycles, "samples", None),
        "bake": {},
    }
    for attr in (
        "use_selected_to_active",
        "use_clear",
        "use_cage",
        "cage_extrusion",
        "max_ray_distance",
        "margin",
        "normal_space",
        "use_pass_direct",
        "use_pass_indirect",
        "use_pass_color",
        "use_pass_diffuse",
        "use_pass_glossy",
        "use_pass_transmission",
        "use_pass_emit",
        "cage_object",
        "target",
    ):
        if hasattr(bake, attr):
            state["bake"][attr] = getattr(bake, attr)
    return state


def _restore_context_state(context, state):
    if not state:
        return
    scene = context.scene
    bake = scene.render.bake
    scene.render.engine = state["render_engine"]
    if state["cycles_samples"] is not None:
        try:
            scene.cycles.samples = state["cycles_samples"]
        except Exception:
            pass
    for attr, value in state["bake"].items():
        if hasattr(bake, attr):
            try:
                setattr(bake, attr, value)
            except Exception:
                pass
    bpy.ops.object.select_all(action="DESELECT")
    for obj in state["selected_objects"]:
        if obj is not None and obj.name in bpy.data.objects:
            obj.select_set(True)
    active_object = state["active_object"]
    if active_object is not None and active_object.name in bpy.data.objects:
        context.view_layer.objects.active = active_object


def _prepare_highpoly_for_map(highpoly, map_id):
    _ensure_slots(highpoly)
    for slot in highpoly.material_slots:
        if slot.material is None:
            continue
        material = slot.material
        material.use_nodes = True
        if material.node_tree is None:
            continue
        emit_passes = MAP_SETTINGS[map_id].get("emit_passes")
        if emit_passes:
            _rewire_passes_to_emit(material, emit_passes)


def _configure_bake_settings(context, props, map_id):
    scene = context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = props.samples

    bake = scene.render.bake
    bake.use_selected_to_active = True
    bake.use_clear = True
    if hasattr(bake, "use_cage"):
        bake.use_cage = True
    if hasattr(bake, "cage_object"):
        bake.cage_object = None
    bake.cage_extrusion = props.cage_extrusion
    bake.max_ray_distance = props.max_ray_distance
    bake.margin = props.margin
    if hasattr(bake, "normal_space"):
        bake.normal_space = props.normal_space
    if hasattr(bake, "margin_type"):
        try:
            bake.margin_type = "EXTEND"
        except Exception:
            pass
    if hasattr(bake, "target"):
        try:
            bake.target = "IMAGE_TEXTURES"
        except Exception:
            pass

    for attr in (
        "use_pass_direct",
        "use_pass_indirect",
        "use_pass_color",
        "use_pass_diffuse",
        "use_pass_glossy",
        "use_pass_transmission",
        "use_pass_emit",
    ):
        if hasattr(bake, attr):
            setattr(bake, attr, False)

    return MAP_SETTINGS[map_id]["blender_type"]


def _ensure_surface_material(mat):
    mat.use_nodes = True
    if mat.node_tree is None:
        return None, None, None
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    output = _find_output_node(nodes)
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (200, 0)
    principled = _find_principled_node(nodes)
    if principled is None:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        principled.location = (-100, 0)
    surface = _find_socket_by_name(output.inputs, "Surface")
    if surface is not None:
        for link in list(surface.links):
            if link.from_node == principled:
                break
        else:
            for link in list(surface.links):
                links.remove(link)
            links.new(principled.outputs["BSDF"], surface)
    return nodes, links, principled


def _link_socket(links, from_socket, to_socket):
    for link in list(to_socket.links):
        links.remove(link)
    links.new(from_socket, to_socket)


def _ensure_image_node(nodes, image, map_id, location):
    node_name = FINAL_NODE_PREFIX + map_id
    node = nodes.new("ShaderNodeTexImage")
    node.name = node_name
    node.label = _map_label(map_id)
    node.location = location
    node.image = image
    return node


def _clear_managed_nodes(nodes):
    for node_name in MANAGED_NODE_NAMES:
        node = nodes.get(node_name)
        if node is not None:
            nodes.remove(node)


def _apply_baked_maps_to_material(mat, baked_lookup, normal_space, uv_map_name):
    nodes, links, principled = _ensure_surface_material(mat)
    if nodes is None or principled is None:
        return

    base_color_socket = _find_socket_by_name(principled.inputs, "Base Color")
    roughness_socket = _find_socket_by_name(principled.inputs, "Roughness")
    metallic_socket = _find_socket_by_name(principled.inputs, "Metallic")
    normal_socket = _find_socket_by_name(principled.inputs, "Normal")
    emission_socket = _find_socket_by_name(principled.inputs, "Emission Color", "Emission")
    emission_strength_socket = _find_socket_by_name(principled.inputs, "Emission Strength")

    merged_lookup = {}
    for map_id in PBR_MAP_ORDER:
        existing_node = nodes.get(FINAL_NODE_PREFIX + map_id)
        if existing_node is not None and getattr(existing_node, "image", None) is not None:
            merged_lookup[map_id] = existing_node.image
    merged_lookup.update(baked_lookup)

    _clear_managed_nodes(nodes)

    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = FINAL_UV_NODE_NAME
    uv_node.location = (-1600, -200)
    if hasattr(uv_node, "uv_map") and uv_map_name:
        uv_node.uv_map = uv_map_name

    image_nodes = {}
    node_positions = {
        "ALBEDO": (-1200, 250),
        "AO": (-1200, 0),
        "NORMAL": (-1200, -500),
        "ROUGHNESS": (-1200, -200),
        "METALLIC": (-1200, -350),
        "EMISSION": (-1200, 450),
    }

    for map_id in PBR_MAP_ORDER:
        image = merged_lookup.get(map_id)
        if image is None:
            continue
        image_node = _ensure_image_node(nodes, image, map_id, node_positions[map_id])
        image_nodes[map_id] = image_node
        links.new(uv_node.outputs["UV"], image_node.inputs["Vector"])

    if base_color_socket is not None:
        if "ALBEDO" in image_nodes and "AO" in image_nodes:
            ao_mix = nodes.new("ShaderNodeMixRGB")
            ao_mix.name = FINAL_AO_MIX_NODE_NAME
            ao_mix.label = "AO x Albedo"
            ao_mix.blend_type = "MULTIPLY"
            ao_mix.inputs[0].default_value = 1.0
            ao_mix.location = (-850, 150)
            links.new(image_nodes["ALBEDO"].outputs["Color"], ao_mix.inputs[1])
            links.new(image_nodes["AO"].outputs["Color"], ao_mix.inputs[2])
            _link_socket(links, ao_mix.outputs["Color"], base_color_socket)
        elif "ALBEDO" in image_nodes:
            _link_socket(links, image_nodes["ALBEDO"].outputs["Color"], base_color_socket)
        elif "AO" in image_nodes:
            _link_socket(links, image_nodes["AO"].outputs["Color"], base_color_socket)

    if roughness_socket is not None and "ROUGHNESS" in image_nodes:
        _link_socket(links, image_nodes["ROUGHNESS"].outputs["Color"], roughness_socket)

    if metallic_socket is not None and "METALLIC" in image_nodes:
        _link_socket(links, image_nodes["METALLIC"].outputs["Color"], metallic_socket)

    if normal_socket is not None and "NORMAL" in image_nodes:
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = FINAL_NORMALMAP_NODE_NAME
        normal_map.location = (-900, -500)
        try:
            normal_map.space = normal_space
        except Exception:
            pass
        links.new(image_nodes["NORMAL"].outputs["Color"], normal_map.inputs["Color"])
        _link_socket(links, normal_map.outputs["Normal"], normal_socket)

    if emission_socket is not None and "EMISSION" in image_nodes:
        _link_socket(links, image_nodes["EMISSION"].outputs["Color"], emission_socket)
        if emission_strength_socket is not None and hasattr(emission_strength_socket, "default_value"):
            emission_strength_socket.default_value = 1.0


def _apply_baked_maps_to_lowpoly(lowpoly, baked_results, normal_space):
    _ensure_slots(lowpoly)
    baked_lookup = {result["map_id"]: result["image"] for result in baked_results}
    uv_map_name = None
    if lowpoly.data.uv_layers.active is not None:
        uv_map_name = lowpoly.data.uv_layers.active.name
    processed = set()
    for slot in lowpoly.material_slots:
        if slot.material is None:
            mat = bpy.data.materials.new(lowpoly.name + "_UAVBaked")
            mat.use_nodes = True
            slot.material = mat
        material = slot.material
        if material is None or material.as_pointer() in processed:
            continue
        processed.add(material.as_pointer())
        _apply_baked_maps_to_material(material, baked_lookup, normal_space, uv_map_name)


class UAV_OT_detail_baking(Operator):
    """Bake texture maps from the high-poly source to the active low-poly mesh."""

    bl_idname = "uav.detail_baking"
    bl_label = "Bake Texture"
    bl_description = (
        "Bake single maps or a full PBR set from the high-poly source to the active low-poly mesh. "
        "Albedo and metallic use BakeLab-style pass extraction, and the baked maps are linked "
        "back into the low-poly materials automatically."
    )
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _bake_gen = None

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "OBJECT"

    def _validate(self, props, lowpoly):
        errors = []
        if props.highpoly_object is None:
            errors.append("Defina o High-Poly Source no painel de Bake.")
        elif props.highpoly_object == lowpoly:
            errors.append("High-poly e low-poly nao podem ser o mesmo objeto.")
        if not lowpoly.data.uv_layers.active:
            errors.append(f"'{lowpoly.name}' nao tem UV map ativo.")
        bake_queue = _collect_bake_queue(props)
        if not bake_queue:
            errors.append("Ative pelo menos um mapa PBR antes de iniciar o bake.")
        return errors

    def _bake_pipeline(self, context):
        props = context.scene.uav_bake_props
        lowpoly = context.active_object
        highpoly = props.highpoly_object
        bake_queue = _collect_bake_queue(props)
        base_name = props.texture_name.strip() or lowpoly.name
        out_dir = _resolve_output_dir(props)
        size = int(props.texture_size)
        start_time = time.perf_counter()
        baked_results = []
        state = _stash_context_state(context)
        lowpoly_assignment = _capture_material_assignment(lowpoly)

        props.last_bake_ok = False
        props.last_bake_count = 0

        try:
            _ensure_bake_material_assigned(lowpoly)

            for map_id in bake_queue:
                image_name = base_name + _map_suffix(map_id)
                image = _create_bake_image(image_name, size, map_id)
                yield 1

                _ensure_slots(highpoly)
                _ensure_slots(lowpoly)

                hp_slots, hp_orig, hp_copies = _reserve_materials(highpoly)
                try:
                    _prepare_highpoly_for_map(highpoly, map_id)
                    yield 1

                    _prepare_lowpoly_mats(lowpoly, image)
                    yield 1

                    bpy.ops.object.select_all(action="DESELECT")
                    highpoly.select_set(True)
                    lowpoly.select_set(True)
                    context.view_layer.objects.active = lowpoly
                    yield 1

                    blender_type = _configure_bake_settings(context, props, map_id)

                    while bpy.ops.object.bake("INVOKE_DEFAULT", type=blender_type) != {"RUNNING_MODAL"}:
                        yield 1
                    while not image.is_dirty:
                        yield 1

                finally:
                    _restore_materials(hp_slots, hp_orig, hp_copies)

                out_path = _save_image(image, out_dir, image_name)
                image = _load_saved_image(image, out_path, image_name, map_id)

                baked_results.append({
                    "map_id": map_id,
                    "image": image,
                    "path": out_path,
                })
                yield 1

            _apply_baked_maps_to_lowpoly(lowpoly, baked_results, props.normal_space)

            props.last_bake_time = time.perf_counter() - start_time
            props.last_bake_count = len(baked_results)
            props.last_bake_type = "PBR Set" if len(baked_results) > 1 else _map_label(baked_results[0]["map_id"])
            props.last_bake_path = out_dir if len(baked_results) > 1 else baked_results[0]["path"]
            props.last_bake_ok = True

            self.report(
                {"INFO"},
                f"Bake concluido: {len(baked_results)} mapa(s) em {props.last_bake_time:.2f}s",
            )
            yield 0

        except Exception as exc:
            props.last_bake_ok = False
            props.last_bake_count = 0
            self.report({"ERROR"}, f"Bake falhou: {exc}")
            import traceback
            traceback.print_exc()
            yield -1

        finally:
            if not props.last_bake_ok:
                _restore_material_assignment(lowpoly, lowpoly_assignment)
            _restore_context_state(context, state)

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish(context)
            self.report({"WARNING"}, "Bake cancelado.")
            return {"CANCELLED"}

        if event.type == "TIMER":
            result = next(self._bake_gen, 0)
            if result == -1:
                self._finish(context)
                return {"CANCELLED"}
            if result == 0:
                self._finish(context)
                return {"FINISHED"}

        return {"PASS_THROUGH"}

    def _finish(self, context):
        wm = context.window_manager
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        if self._bake_gen and hasattr(self._bake_gen, "close"):
            try:
                self._bake_gen.close()
            except Exception:
                pass
        self._bake_gen = None

    def execute(self, context):
        props = context.scene.uav_bake_props
        lowpoly = context.active_object
        errors = self._validate(props, lowpoly)
        if errors:
            for error in errors:
                self.report({"ERROR"}, error)
            return {"CANCELLED"}

        self._bake_gen = self._bake_pipeline(context)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

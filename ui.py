import bpy
from bpy.types import Panel


class UAV_PT_main_panel(Panel):
    bl_label       = "UAV Post-Processing Pipeline"
    bl_idname      = "UAV_PT_main_panel"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'UAV Opt'

    def _draw_foldout_header(self, layout, props, attr, label, icon='NONE'):
        row = layout.row(align=True)
        is_open = getattr(props, attr)
        tri_icon = 'DISCLOSURE_TRI_DOWN' if is_open else 'DISCLOSURE_TRI_RIGHT'
        row.prop(props, attr, text=label, icon=tri_icon, emboss=False)
        if icon != 'NONE':
            row.label(text="", icon=icon)
        return is_open

    def draw(self, context):
        layout = self.layout
        props  = context.scene.uav_props
        qw     = context.scene.uav_quadwild_props
        uvp    = context.scene.uav_uvpack_props
        bake   = context.scene.uav_bake_props
        std_uv = context.scene.uav_std_uv_props

        # -- 1. Pre-Processing ----------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_preprocess", "1. Mesh Pre-Processing", icon='MOD_SMOOTH'):
            col = box.column(align=True)
            col.prop(props, "pre_merge_distance",        text="Merge Distance")
            col.prop(props, "pre_degenerate_threshold",  text="Degenerate Threshold")
            box.separator(factor=0.4)
            row = box.row(align=True)
            row.prop(props, "pre_smooth_iterations", text="Smooth Iters")
            row.prop(props, "pre_smooth_factor",     text="Factor")
            box.separator(factor=0.4)
            col = box.column(align=True)
            col.prop(props, "pre_despike_threshold", text="Despike Limit")
            row = col.row(align=True)
            row.prop(props, "pre_despike_passes", text="Passes")
            row.prop(props, "pre_despike_lerp",   text="Strength")
            box.operator("uav.preprocess", icon='PLAY', text="Run Pre-Processing")

        # -- 2. QEM --------------------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_qem", "2. QEM Simplification", icon='MOD_DECIM'):
            box.prop(props, "qem_engine", text="Engine")
            box.prop(props, "qem_target_mode", text="Target")

            if props.qem_target_mode == 'DENSITY':
                row = box.row(align=True)
                row.prop(props, "qem_target_density")
                row.prop(props, "qem_density_unit", text="")
            elif props.qem_target_mode == 'RATIO':
                box.prop(props, "qem_target_ratio", text="Keep Ratio")
            else:
                box.prop(props, "qem_target_vertex_count", text="Target Vertices")

            if props.qem_engine != 'FAST_DECIMATE':
                adv = box.box()
                adv.label(text="Imported mesh_simplification Options", icon='PREFERENCES')
                adv.prop(props, "qem_valence_aware", text="Valence Aware")
                if props.qem_engine == 'TRUE_QEM':
                    adv.prop(props, "qem_midpoint_fallback", text="Midpoint Fallback")
                adv.prop(props, "qem_boundary_action", text="Boundary Handling")

            col = box.column(align=True)
            col.prop(props, "qem_merge_distance",       text="Pre-Merge Distance")
            col.prop(props, "qem_post_merge_distance",  text="Post-Merge Distance")
            col.prop(props, "qem_degenerate_threshold", text="Degenerate Threshold")
            col.prop(props, "qem_sliver_filter",        text="Sliver Filter")
            box.prop(props, "qem_collection_suffix", text="Collection Suffix")
            box.operator("uav.qem_simplify", icon='PLAY', text="Run QEM")

        # -- 3. Quad Retopology ---------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_retopo", "3. Quad Retopology", icon='MOD_REMESH'):
            box.prop(props, "remesh_method", text="Algorithm")

            if props.remesh_method == 'QUADRIFLOW':
                box.prop(props, "target_quad_count")
                box.operator("uav.quadriflow_retopo", icon='PLAY', text="Run QuadriFlow")

            elif props.remesh_method == 'QUADWILD':
                self._draw_quadwild(box, qw)

            elif props.remesh_method == 'VOXEL':
                col = box.column(align=True)
                col.prop(props, "voxel_size")
                col.prop(props, "voxel_solidify_thickness", text="Solidify Thickness")
                box.operator("uav.voxel_retopo", icon='PLAY', text="Run Voxel Remesh")

            elif props.remesh_method == 'SHRINKWRAP':
                col = box.column(align=True)
                col.prop(props, "grid_resolution")
                col.prop(props, "grid_spawn_offset",   text="Spawn Offset")
                col.prop(props, "grid_miss_tolerance", text="Miss Tolerance")
                col.prop(props, "grid_safety_margin",  text="Safety Margin")
                box.operator("uav.shrinkwrap_retopo", icon='PLAY', text="Run Grid Projection")

        # -- 4. Grid Seams --------------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_grid_seams", "4. Generate UV Grid Seams", icon='MESH_GRID'):
            row = box.row()
            row.prop(props, "chunk_cols", text="Cols (X)")
            row.prop(props, "chunk_rows", text="Rows (Y)")
            box.prop(props, "chunk_timer_interval", text="Timer Interval (s)")
            box.operator("uav.split_chunks", icon='MOD_BOOLEAN', text="Trace Grid Seams")

        # -- 5. UV Unwrapping -----------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_uv_unwrap", "5. UV Unwrapping", icon='UV'):
            self._draw_uv_unwrap(box, std_uv)

        # -- 6. UV Island Packing -------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_uv_pack", "6. Island Packing", icon='GROUP_UVS'):
            self._draw_uv_pack(box, uvp)

        # -- 7. Baking ------------------------------------------------
        box = layout.box()
        if self._draw_foldout_header(box, props, "ui_show_bake", "7. Texture Baking", icon='RENDER_STILL'):
            self._draw_bake(box, bake)

    # -----------------------------------------------------------------
    # 7. Baking sub-panel
    # -----------------------------------------------------------------
    def _draw_bake(self, box, bake):
        col = box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False

        # -- Objects -----------------------------------------------
        col.prop(bake, "highpoly_object", text="High-Poly Source")
        col.separator(factor=0.3)

        # -- Bake type + size + name --------------------------------
        col.prop(bake, "bake_type",     text="Bake Type")
        col.prop(bake, "texture_size",  text="Texture Size")
        col.prop(bake, "texture_name",  text="Texture Name")
        col.separator(factor=0.3)

        # -- Normal space (only when baking normals) ----------------
        if bake.bake_type == 'NORMAL':
            col.prop(bake, "normal_space", text="Normal Space")
            col.separator(factor=0.3)

        # -- Quality -----------------------------------------------
        q_box = box.box()
        q_box.label(text="Quality", icon='SETTINGS')
        q_col = q_box.column(align=True)
        q_col.use_property_split    = True
        q_col.use_property_decorate = False
        q_col.prop(bake, "samples",          text="Samples")
        q_col.prop(bake, "margin",           text="Margin (px)")
        q_col.prop(bake, "cage_extrusion",   text="Cage Extrusion")
        q_col.prop(bake, "max_ray_distance", text="Max Ray Distance")

        # -- Output ------------------------------------------------
        out_box = box.box()
        out_box.label(text="Output", icon='FILE_FOLDER')
        out_col = out_box.column(align=True)
        out_col.use_property_split    = True
        out_col.use_property_decorate = False
        out_col.prop(bake, "output_dir", text="Output Folder")

        # -- Suffix preview ----------------------------------------
        suffix_map = {'ALBEDO': '_albedo', 'AO': '_ao', 'NORMAL': '_normal'}
        suffix = suffix_map.get(bake.bake_type, '')
        base   = bake.texture_name.strip() or "<object_name>"
        out_col.separator(factor=0.2)
        out_col.label(text=f"File: {base}{suffix}.png", icon='FILE_IMAGE')

        box.separator(factor=0.5)

        # -- Action button -----------------------------------------
        op_row = box.row(align=True)
        op_row.scale_y = 1.4
        op_row.operator("uav.detail_baking", icon='RENDER_STILL', text="Bake Texture")

        # -- Last result -------------------------------------------
        if bake.last_bake_ok and bake.last_bake_path:
            res_box = box.box()
            res_col = res_box.column(align=True)
            row = res_col.row()
            row.label(text="Last baked:", icon='CHECKMARK')
            row.label(text=bake.last_bake_type)
            row = res_col.row()
            row.label(text=f"Time: {bake.last_bake_time:.1f}s")
            res_col.separator(factor=0.2)
            res_col.label(text=bake.last_bake_path, icon='FILE_TICK')

    def _draw_uv_unwrap(self, box, std_uv):
        col = box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False

        col.prop(std_uv, "unwrap_method", text="Method")

        if std_uv.unwrap_method == 'SMART':
            col.prop(std_uv, "smart_uv_angle_limit", text="Angle Limit")
            col.prop(std_uv, "smart_uv_island_margin", text="Island Margin")
            col.prop(std_uv, "smart_uv_area_weight", text="Area Weight")
        else:
            col.prop(std_uv, "unwrap_fill_holes", text="Fill Holes")
            col.prop(std_uv, "unwrap_correct_aspect", text="Correct Aspect")
            col.prop(std_uv, "unwrap_use_subsurf", text="Use Subsurf Data")
            col.prop(std_uv, "unwrap_margin", text="Margin")

            if std_uv.unwrap_method == 'MINIMUM_STRETCH':
                col.prop(std_uv, "min_stretch_iterations", text="Iterations")
                col.prop(std_uv, "min_stretch_blend", text="Blend")
                box.label(text="Seeds Angle Based if no UVs exist", icon='INFO')

        box.separator(factor=0.5)

        run_row = box.row(align=True)
        run_row.scale_y = 1.3
        run_row.operator("uav.uv_unwrap", icon='PLAY', text="Run Native Unwrap")

        td_box = box.box()
        td_box.label(text="Texel Density", icon='TEXTURE')
        td_col = td_box.column(align=True)
        td_col.use_property_split    = True
        td_col.use_property_decorate = False
        td_col.prop(std_uv, "density_mode", text="Mode")
        if std_uv.density_mode == 'MANUAL':
            td_col.prop(std_uv, "target_density", text="Target (px/m)")
            td_col.prop(std_uv, "density_bake_resolution", text="Reference Resolution")
        td_box.operator("uav.uv_equalize_texel", icon='MOD_UVPROJECT', text="Equalize Density")

        box.operator("uav.uv_island_stats", icon='INFO', text="Refresh UV Stats")

        if std_uv.last_islands > 0 or std_uv.last_time > 0.01:
            res_box = box.box()
            res_col = res_box.column(align=True)

            row = res_col.row()
            row.label(text="Method:")
            row.label(text=std_uv.last_method_used or "Not run yet")

            row = res_col.row()
            row.label(text="Islands:")
            row.label(text=str(std_uv.last_islands))

            row = res_col.row()
            row.label(text="Coverage:")
            row.label(text=f"{std_uv.last_coverage:.1f}%")

            row = res_col.row()
            row.label(text="Avg Stretch:")
            row.label(text=f"{std_uv.last_stretch:.3f}")

            row = res_col.row()
            row.label(text="Avg Density:")
            row.label(text=f"{std_uv.last_avg_density:.4f}")

            row = res_col.row()
            row.label(text="Min / Max Density:")
            row.label(text=f"{std_uv.last_min_density:.4f} / {std_uv.last_max_density:.4f}")

            row = res_col.row()
            row.label(text="Time:")
            row.label(text=f"{std_uv.last_time:.2f}s")

            if std_uv.last_flipped > 0:
                res_col.label(text=f"{std_uv.last_flipped} flipped faces", icon='ERROR')
            if std_uv.last_oob > 0:
                res_col.label(text=f"{std_uv.last_oob} faces out of bounds", icon='ERROR')

    def _draw_uv_pack(self, box, uvp):
        col = box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False

        col.prop(uvp, "packing_method",      text="Algorithm")
        if uvp.packing_method == 'MAXRECTS':
            col.prop(uvp, "maxrects_heuristic", text="Heuristic")

        col.prop(uvp, "optimizer",       text="Optimizer")
        col.prop(uvp, "precision",       text="Precision")
        col.prop(uvp, "margin",          text="Margin (UV)")
        col.prop(uvp, "rotation_enable", text="Allow Rotation")
        if uvp.rotation_enable:
            col.prop(uvp, "rotation_step", text="Rotation Step")

        col.prop(uvp, "scale_mode", text="Scale Mode")
        if uvp.scale_mode == 'CUSTOM':
            col.prop(uvp, "custom_scale", text="Custom Scale")

        col.prop(uvp, "pixel_margin_enable", text="Use Pixel Margin")
        if uvp.pixel_margin_enable:
            col.prop(uvp, "pixel_margin", text="Margin (px)")
            col.prop(uvp, "texture_size", text="Texture Size")

        col.prop(uvp, "search_time",        text="Search Time (s)")
        col.prop(uvp, "advanced_heuristic", text="Advanced Heuristic")

        if uvp.optimizer == 'SA':
            sa_box = box.box()
            sa_box.label(text="Simulated Annealing", icon='MOD_PHYSICS')
            sa_col = sa_box.column(align=True)
            sa_col.use_property_split    = True
            sa_col.use_property_decorate = False
            sa_col.prop(uvp, "sa_initial_temp", text="Initial Temp")
            sa_col.prop(uvp, "sa_cooling_rate", text="Cooling Rate")

        box.separator(factor=0.5)

        row = box.row(align=True)
        row.scale_y = 1.3
        row.operator("uav.uv_pack",       icon='FULLSCREEN_ENTER', text="Pack Islands")
        row.operator("uav.uv_pack_reset", icon='LOOP_BACK',        text="Reset Best")

        if uvp.last_iterations > 0:
            res_box = box.box()
            res_col = res_box.column(align=True)
            row = res_col.row()
            row.label(text="Occupancy:")
            row.label(text=f"{uvp.last_occupancy:.1f}%")

            row = res_col.row()
            row.label(text="Best Ever:")
            row.label(text=f"{uvp.best_ever_occupancy * 100:.1f}%")

            row = res_col.row()
            row.label(text="Iterations:")
            row.label(text=str(uvp.last_iterations))

            row = res_col.row()
            row.label(text="Method:")
            row.label(text=uvp.last_method)

            row = res_col.row()
            row.label(text="Time:")
            row.label(text=f"{uvp.last_time:.2f}s")

    # -----------------------------------------------------------------
    # QuadWild sub-panel (UNCHANGED)
    # -----------------------------------------------------------------
    def _draw_quadwild(self, box, qw):
        col = box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False

        row = col.row(align=True)
        row.prop(qw, "enable_preprocess", text="Preprocess")
        row.prop(qw, "enable_smoothing",  text="Smoothing")
        col.prop(qw, "scale_fact", text="Scale / Density")

        box.separator(factor=0.4)

        row = box.row(align=True)
        row.prop(qw, "enable_sharp", text="Sharp Detection")
        if qw.enable_sharp:
            sub = box.column(align=True)
            sub.use_property_split    = True
            sub.use_property_decorate = False
            sub.prop(qw, "sharp_angle", text="Angle")

        box.separator(factor=0.4)

        row = box.row(align=True)
        row.label(text="Symmetry:")
        row.prop(qw, "symmetry_x", toggle=True)
        row.prop(qw, "symmetry_y", toggle=True)
        row.prop(qw, "symmetry_z", toggle=True)

        box.separator(factor=0.4)

        col = box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False
        col.prop(qw, "alpha")
        col.prop(qw, "ilp_method")
        col.prop(qw, "time_limit")
        col.prop(qw, "gap_limit")
        col.prop(qw, "minimum_gap")
        col.prop(qw, "fixed_chart_clusters")

        box.separator(factor=0.4)

        q_box = box.box()
        q_box.label(text="Quality", icon='SETTINGS')
        col = q_box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False
        col.prop(qw, "isometry",                       text="Isometry")
        col.prop(qw, "regularity_quads",                text="Regularity Quads")
        col.prop(qw, "regularity_non_quads",             text="Regularity Non-Quads")
        col.prop(qw, "regularity_non_quads_weight",      text="  Weight")
        col.prop(qw, "align_singularities",              text="Align Singularities")
        col.prop(qw, "align_singularities_weight",       text="  Weight")
        col.prop(qw, "hard_parity",                      text="Hard Parity Constraint")

        rl_box = box.box()
        rl_box.label(text="Repeat Losing Constraints", icon='CON_ROTLIMIT')
        col = rl_box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False
        col.prop(qw, "repeat_losing_iters",     text="Iterations")
        col.prop(qw, "repeat_losing_quads",     text="Quads")
        col.prop(qw, "repeat_losing_non_quads", text="Non-Quads")
        col.prop(qw, "repeat_losing_align",     text="Align")

        box.separator(factor=0.4)

        col = box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False
        col.prop(qw, "flow_config",    text="Flow Config")
        col.prop(qw, "satsuma_config", text="Satsuma Config")

        cb_box = box.box()
        cb_box.label(text="Callback Schedule (8 checkpoints)", icon='TIME')
        col = cb_box.column(align=True)
        col.use_property_split    = True
        col.use_property_decorate = False
        col.prop(qw, "callback_time_limit", text="Time (s)")
        col.prop(qw, "callback_gap_limit",  text="Gap")

        box.separator(factor=0.4)

        row = box.row(align=True)
        row.prop(qw, "debug",     toggle=True, icon='HIDE_OFF',   text="Debug")
        row.prop(qw, "use_cache", toggle=True, icon='FILE_CACHE', text="Use Cache")

        box.separator(factor=0.4)
        box.operator("uav.quadwild_retopo", icon='PLAY', text="Run QuadWild")


import bpy
from bpy.props import (
    IntProperty, FloatProperty, BoolProperty,
    EnumProperty, StringProperty, FloatVectorProperty,
    PointerProperty,
)
from bpy.types import Collection, PropertyGroup


UV_PACK_ENGINE_ITEMS = (
    ('AUTO', "Auto (Optimized)",
     "Prefer UVPackmaster addon, then C++ Native, then Blender Native"),
    ('UVPACKMASTER_ADDON', "UVPackmaster Addon",
     "Delegate packing to the UVPackmaster addon installed in Blender"),
    ('BLENDER_NATIVE', "Blender Native",
     "Blender's built-in Pack Islands operator - reliable baseline"),
    ('CPP_NATIVE', "C++ Native (fast)",
     "Same algorithm compiled to native C++ - 80-100x faster than Python. "
     "Requires lib_uvpack compiled from uvpack_cpp/ with CMake"),
)

class UAVOptimizerProperties(PropertyGroup):

    # ==========================================
    # UI Foldouts
    # ==========================================
    ui_show_preprocess: BoolProperty(
        name="Show Pre-Processing",
        description="Expand or collapse the mesh cleanup section",
        default=True,
    )
    ui_show_qem: BoolProperty(
        name="Show QEM",
        description="Expand or collapse the QEM simplification section",
        default=True,
    )
    ui_show_retopo: BoolProperty(
        name="Show Retopology",
        description="Expand or collapse the quad retopology section",
        default=False,
    )
    ui_show_grid_seams: BoolProperty(
        name="Show Grid Seams",
        description="Expand or collapse the UV grid seam generation section",
        default=False,
    )
    ui_show_uv_unwrap: BoolProperty(
        name="Show UV Unwrap",
        description="Expand or collapse the native UV unwrapping section",
        default=False,
    )
    ui_show_uv_pack: BoolProperty(
        name="Show UV Pack",
        description="Expand or collapse the island packing section",
        default=False,
    )
    ui_show_bake: BoolProperty(
        name="Show Bake",
        description="Expand or collapse the texture baking section",
        default=False,
    )
    ui_show_lod: BoolProperty(
        name="Show LOD Generation",
        description="Expand or collapse the LOD generation section",
        default=False,
    )
    ui_show_export: BoolProperty(
        name="Show Engine Export",
        description="Expand or collapse the engine export section",
        default=False,
    )


    # ==========================================
    # 1. Pre-Processing (Cleanup)
    # ==========================================
    pre_smooth_iterations: IntProperty(
        name="Smooth Iterations",
        description="Fixes 'sunken' vertices and surface noise. High values may melt real details (Recommended: 1-3)",
        default=2, min=0, max=20
    )
    pre_smooth_factor: FloatProperty(
        name="Smooth Factor",
        description="Strength of the smoothing (0.0 to 1.0)",
        default=0.5, min=0.0, max=1.0, precision=2
    )
    pre_merge_distance: FloatProperty(
        name="Merge Distance",
        description="Threshold for welding overlapping vertices in the pre-processing step",
        default=0.001, min=0.0, max=1.0, precision=5, subtype='DISTANCE', unit='LENGTH'
    )
    pre_degenerate_threshold: FloatProperty(
        name="Degenerate Threshold",
        description="Minimum edge length below which degenerate geometry is dissolved during pre-processing",
        default=0.0001, min=0.0, max=0.1, precision=6, subtype='DISTANCE', unit='LENGTH'
    )
    pre_despike_threshold: FloatProperty(
        name="Despike Threshold",
        description="Flattens extreme spikes. Set to 0 to disable. (Try 0.2m)",
        default=0.2, min=0.0, max=10.0, subtype='DISTANCE', unit='LENGTH'
    )
    pre_despike_passes: IntProperty(
        name="Despike Passes",
        description="Number of smoothing passes applied to spike vertices. More passes = stronger correction, but may erode real details (Recommended: 1-3)",
        default=2, min=1, max=10
    )
    pre_despike_lerp: FloatProperty(
        name="Despike Strength",
        description="How aggressively a spike vertex is pulled towards its neighbours' average (0.0 = no move, 1.0 = snap to average)",
        default=0.8, min=0.0, max=1.0, precision=2
    )
    pre_topology_enable: BoolProperty(
        name="Topology Check",
        description="Analyze mesh topology during pre-processing and store a readiness report on the generated _PREP object",
        default=True,
    )
    pre_repair_mode: EnumProperty(
        name="Repair Mode",
        description="Topology repair policy applied inside pre-processing before simplification and retopology",
        items=[
            ('DIAGNOSE', "Diagnose Only", "Analyze topology but do not repair it"),
            ('SAFE', "Safe Repair", "Remove loose/degenerate geometry and recalculate normals"),
            ('SURFACE_REPAIR', "Surface Repair", "Safe repair plus optional small hole filling"),
            ('VOXEL_PREP', "Voxel Prep", "Prepare open surfaces more aggressively for voxel remeshing"),
            ('AGGRESSIVE', "Aggressive", "Attempt stronger cleanup; may alter photogrammetry surfaces"),
        ],
        default='SAFE',
    )
    pre_delete_loose_geometry: BoolProperty(
        name="Delete Loose Geometry",
        description="Remove vertices and edges that are not part of any valid surface before retopology",
        default=True,
    )
    pre_recalculate_normals: BoolProperty(
        name="Recalculate Normals",
        description="Recalculate face normals after cleanup to reduce shading, unwrap and baking errors",
        default=True,
    )
    pre_remove_small_components: BoolProperty(
        name="Remove Small Components",
        description="Remove tiny disconnected mesh fragments after cleanup. Disabled by default because photogrammetry details may be real geometry",
        default=False,
    )
    pre_min_component_faces: IntProperty(
        name="Min Component Faces",
        description="Connected components with fewer faces than this value may be removed when Remove Small Components is enabled",
        default=32,
        min=1,
        max=100000,
    )
    pre_fill_small_holes: BoolProperty(
        name="Fill Small Holes",
        description="Fill only small boundary loops. Keep disabled for open terrain unless the asset is expected to be a closed object",
        default=False,
    )
    pre_fill_hole_max_edges: IntProperty(
        name="Max Hole Edges",
        description="Maximum number of sides in holes eligible for automatic filling. Do not set to zero for terrain unless you want Blender to fill all holes",
        default=8,
        min=0,
        max=1000,
    )
    pre_warn_if_not_watertight: BoolProperty(
        name="Warn If Not Watertight",
        description="Store a warning when the preprocessed mesh is open. This is useful for voxel remesh, but open terrain should not fail automatically",
        default=True,
    )
    pre_store_health_report: BoolProperty(
        name="Store Health Report",
        description="Write topology analysis results as custom properties on the generated _PREP object",
        default=True,
    )
    pre_last_report_title: StringProperty(
        name="Last Preprocess Report Title",
        description="UI title for the last preprocess or diagnose report",
        default="",
    )
    pre_last_report_status: StringProperty(
        name="Last Preprocess Report Status",
        description="Aggregated status from the last preprocess or diagnose run",
        default="",
    )
    pre_last_report_body: StringProperty(
        name="Last Preprocess Report Body",
        description="Detailed preprocess or diagnose report shown below the run button",
        default="",
    )

    # ==========================================
    # 2. QEM Simplification
    # ==========================================
    qem_engine: EnumProperty(
        name="Engine",
        description="Simplification backend. Fast Decimate uses Blender's native modifier; True QEM uses an explicit quadric-error solver; Edge Length uses the imported isotropic-style heap collapse",
        items=[
            ('FAST_DECIMATE', "Fast Decimate", "Stable fallback using Blender's Decimate Collapse modifier"),
            ('TRUE_QEM', "True QEM", "Explicit quadric error metric simplification adapted from mesh_simplification"),
            ('EDGE_LENGTH', "Edge Length", "Edge-length / isotropic heap simplification adapted from mesh_simplification"),
        ],
        default='FAST_DECIMATE'
    )
    qem_target_mode: EnumProperty(
        name="Target Mode",
        description="How the simplification target is defined",
        items=[
            ('DENSITY', "Density", "Compute the target from triangle density and surface area"),
            ('RATIO', "Ratio", "Keep a percentage of the current triangles"),
            ('TRIANGLE_COUNT', "Triangle Count", "Use an explicit target triangle count"),
            ('VERTEX_COUNT', "Vertex Count", "Use an explicit target vertex count"),
        ],
        default='DENSITY'
    )
    qem_density_unit: EnumProperty(
        name="Unit",
        description="Surface-area unit used by Density target mode",
        items=[('M2', "m^2", "Triangles per square meter"),
               ('CM2', "cm^2", "Triangles per square centimeter")],
        default='M2'
    )
    qem_target_density: FloatProperty(
        name="Density",
        description="Target triangle density used to compute the simplification target automatically",
        default=4.0, min=0.0001, max=1000000.0
    )
    qem_target_ratio: FloatProperty(
        name="Keep Ratio",
        description="Fraction of the current vertices to keep when Target Mode = Ratio",
        default=0.5, min=0.001, max=1.0, precision=4
    )
    qem_target_vertex_count: IntProperty(
        name="Target Vertices",
        description="Explicit target vertex count used by the true QEM / edge-length solvers",
        default=10000, min=4, max=10000000
    )
    qem_target_triangle_count: IntProperty(
        name="Target Triangles",
        description="Explicit target triangle count. Ratio and Density targets are also enforced as triangle counts",
        default=50000, min=4, max=10000000
    )
    qem_valence_aware: BoolProperty(
        name="Valence Aware",
        description="Penalise collapses that create poor valence, especially valence 3",
        default=True
    )
    qem_midpoint_fallback: BoolProperty(
        name="Midpoint Fallback",
        description="When the optimal quadric solve is singular, place the merged vertex at the edge midpoint",
        default=True
    )
    qem_preserve_seams: BoolProperty(
        name="Preserve Seams",
        description="Protect UV seam edges during simplification. Disable this for seam-free LiDAR meshes to reduce overhead and simplify more freely",
        default=True
    )
    qem_boundary_action: EnumProperty(
        name="Boundary Handling",
        description="The imported mesh_simplification core assumes closed two-manifold topology. Choose how open boundaries are handled",
        items=[
            ('FALLBACK', "Fallback to Fast Decimate", "Use Blender Decimate whenever an open boundary is detected"),
            ('CANCEL', "Cancel", "Abort the operation if an open boundary is detected"),
        ],
        default='FALLBACK'
    )
    qem_merge_distance: FloatProperty(
        name="Pre-Merge Distance",
        description="Weld threshold applied before decimation to avoid degenerate input to QEM",
        default=0.001, min=0.0, max=100.0, subtype='DISTANCE', unit='LENGTH'
    )
    qem_post_merge_distance: FloatProperty(
        name="Post-Merge Distance",
        description="Weld threshold applied after decimation to clean up micro-slivers created by QEM",
        default=0.0001, min=0.0, max=1.0, precision=6, subtype='DISTANCE', unit='LENGTH'
    )
    qem_degenerate_threshold: FloatProperty(
        name="Degenerate Threshold",
        description="Edge-length limit for dissolving degenerate faces in both pre and post QEM passes",
        default=0.0001, min=0.0, max=0.1, precision=6
    )
    qem_sliver_filter: FloatProperty(
        name="Sliver Filter",
        description="Post-QEM dissolve threshold that removes needle-thin triangles left by aggressive decimation",
        default=0.001, min=0.0, max=1.0, precision=4
    )
    qem_collection_suffix: StringProperty(
        name="Collection Suffix",
        description="Text appended to the output collection name. Change this when running QEM multiple times to avoid overwriting previous results",
        default="QEM_Simplified"
    )

    # ==========================================
    # 3. Quad Retopology
    # ==========================================
    remesh_method: EnumProperty(
        name="Algorithm",
        description="Select the mathematical algorithm used to generate the quad-based mesh",
        items=[
            ('QUADRIFLOW', "QuadriFlow", "Native flow-based algorithm. Excellent for organic terrain"),
            ('QUADWILD',   "QuadWild",   "Feature-preserving algorithm. Best for architecture and sharp cliffs"),
            ('VOXEL',      "Voxel Remesh","Blender's native fast projection. Best for quick prototyping"),
            ('SHRINKWRAP', "Grid Projection","Top-down Z-axis projection. Perfect XYZ alignment for terrains, but stretches on vertical cliffs"),
        ],
        default='QUADRIFLOW'
    )
    target_quad_count: IntProperty(
        name="Target Quads", default=50000, min=100, max=1000000,
        description="Total quad count for QuadriFlow/QuadWild"
    )
    quadriflow_target_mode: EnumProperty(
        name="Target Mode",
        description="How the QuadriFlow target is defined",
        items=[
            ('QUAD_COUNT', "Quad Count", "Use an explicit target quad count"),
            ('RATIO', "Ratio", "Keep an approximate percentage of the current triangle-equivalent count"),
            ('DENSITY', "Density", "Compute an approximate target from triangle density and surface area"),
        ],
        default='QUAD_COUNT',
    )
    quadriflow_target_ratio: FloatProperty(
        name="Keep Ratio",
        description="Approximate fraction of the current triangle-equivalent count to keep before converting to quads",
        default=1.0, min=0.001, max=1.0, precision=4,
    )
    quadriflow_density_unit: EnumProperty(
        name="Unit",
        description="Surface-area unit used by QuadriFlow density targeting",
        items=[
            ('M2', "m^2", "Triangles per square meter"),
            ('CM2', "cm^2", "Triangles per square centimeter"),
        ],
        default='M2',
    )
    quadriflow_target_density: FloatProperty(
        name="Density",
        description="Approximate triangle density used to compute the QuadriFlow target automatically",
        default=4.0, min=0.0001, max=1000000.0,
    )
    feature_angle: FloatProperty(
        name="Feature Angle", default=45.0, min=0.0, max=180.0,
        description="Angle threshold to preserve sharp edges in QuadWild"
    )

    # --- Voxel ---
    voxel_size: FloatProperty(
        name="Voxel Size", default=0.1, min=0.001, max=10.0, subtype='DISTANCE', unit='LENGTH',
        description="Physical size of each voxel. Smaller = more detail, heavier mesh"
    )
    voxel_solidify_thickness: FloatProperty(
        name="Solidify Thickness",
        description="Thickness (metres) added downward before Voxel Remesh to close open terrain surfaces and prevent holes",
        default=2.0, min=0.01, max=50.0, subtype='DISTANCE', unit='LENGTH'
    )

    # --- Grid Projection (Shrinkwrap) ---
    grid_resolution: IntProperty(
        name="Grid Resolution", default=500, min=10, max=5000,
        description="Number of subdivisions for the projection grid. Higher = more detail but heavier mesh"
    )
    grid_spawn_offset: FloatProperty(
        name="Spawn Height Offset",
        description="How many metres above the terrain's highest peak the projection grid is spawned. Increase for very mountainous terrain to ensure full coverage",
        default=10.0, min=0.1, max=500.0, subtype='DISTANCE', unit='LENGTH'
    )
    grid_miss_tolerance: FloatProperty(
        name="Miss Tolerance",
        description="Vertices still within this distance of the spawn height after projection are considered 'misses' and deleted. Increase if flat areas are incorrectly removed",
        default=1.0, min=0.01, max=50.0, subtype='DISTANCE', unit='LENGTH'
    )
    grid_safety_margin: FloatProperty(
        name="Safety Margin",
        description="Extra scale factor applied to the grid so its edges always cover the full terrain bounding box (1.02 = 2% larger). Prevents floating-point gaps at borders",
        default=1.02, min=1.0, max=1.5, precision=3
    )

    # ==========================================
    # 4. Grid Seams
    # ==========================================
    chunk_cols: IntProperty(
        name="Columns (X)",
        description="Number of vertical slices along the X-axis to mathematically cut the mesh and trace UV seams",
        default=2, min=1, max=100
    )
    chunk_rows: IntProperty(
        name="Rows (Y)",
        description="Number of horizontal slices along the Y-axis to mathematically cut the mesh and trace UV seams",
        default=2, min=1, max=100
    )
    chunk_levels: IntProperty(
        name="Levels (Z)",
        description="Number of depth slices along the Z-axis to mathematically cut the mesh and trace UV seams",
        default=1, min=1, max=100
    )
    chunk_timer_interval: FloatProperty(
        name="Timer Interval (s)",
        description="Seconds between each bisect cut in the modal loop. Lower = faster total time but less UI responsiveness on heavy meshes",
        default=0.01, min=0.001, max=1.0, precision=3
    )

    # ==========================================
    # 5 & 6. UV Mapping & Packing
    # ==========================================
    uv_method: EnumProperty(
        name="Method",
        description="Mathematical approach used to flatten the 3D mesh into 2D space",
        items=[
            ('ANGLE_BASED', "Angle Based", "Minimises angular distortion. Best for organic shapes, mountains, and natural terrain"),
            ('CONFORMAL',   "Conformal",   "Preserves original edge lengths and proportions. Best for architecture and hard-surface models"),
        ],
        default='ANGLE_BASED'
    )
    uv_margin: FloatProperty(
        name="Unwrap Margin",
        description="Initial microscopic spacing generated between UV islands during the flattening process to prevent texture bleeding",
        default=0.001, min=0.0, max=1.0, precision=4
    )
    pack_margin: FloatProperty(
        name="Pack Margin",
        description="Safety gap between packed islands in the final UV space. Crucial to avoid mip-map bleeding in game engines",
        default=0.005, min=0.0, max=1.0, precision=4
    )

    # ==========================================
    # 7. Detail Baking
    # ==========================================
    bake_resolution: EnumProperty(
        name="Resolution",
        description="Resolution of the output baked textures (Normals, Albedo, etc.)",
        items=[
            ('1024', "1K (1024x1024)",  "Fastest bake, low detail"),
            ('2048', "2K (2048x2048)",  "Good balance for medium assets"),
            ('4096', "4K (4096x4096)",  "Industry standard for high quality"),
            ('8192', "8K (8192x8192)",  "Maximum fidelity for massive terrains (Requires high VRAM)"),
        ],
        default='4096'
    )
    use_mikktspace: BoolProperty(
        name="MikkTSpace Normal Basis",
        description="Computes tangent space using the industry standard MikkTSpace. Leave this ON to guarantee correct shading in Unreal Engine and Unity",
        default=True
    )

    # UV Pack and QuadWild settings live in their own PropertyGroups
    # (UAVUVPackProperties in op_uv.py, UAVQuadWildProperties below).

    # -- Placeholder to avoid blank class body -----------------
    # (bpy.props are defined above; this comment keeps the block valid)



class UAVQuadWildProperties(PropertyGroup):

    # -- General ----------------------------------------------
    enable_preprocess: BoolProperty(
        name="Preprocess",
        description="Decimate, triangulate and fix common geometry issues before field computation",
        default=True,
    )
    enable_smoothing: BoolProperty(
        name="Smoothing",
        description="Apply Laplacian smoothing after quadrangulation",
        default=True,
    )
    enable_sharp: BoolProperty(
        name="Sharp Detection",
        description="Detect sharp features from angle threshold, seams, boundaries and material/face-set changes",
        default=True,
    )
    sharp_angle: FloatProperty(
        name="Angle Threshold",
        description="Dihedral angle above which an edge is considered sharp",
        min=0.0, soft_min=0.1, max=180.0, soft_max=179.9,
        default=35.0, precision=1, step=10, subtype='UNSIGNED',
    )

    # -- Symmetry ---------------------------------------------
    symmetry_x: BoolProperty(name="X", description="Enable symmetry on the X axis", default=False)
    symmetry_y: BoolProperty(name="Y", description="Enable symmetry on the Y axis", default=False)
    symmetry_z: BoolProperty(name="Z", description="Enable symmetry on the Z axis", default=False)

    # -- Cache / Debug -----------------------------------------
    use_cache: BoolProperty(
        name="Use Cache",
        description="Skip remeshAndField+trace and reuse intermediate files on disk. "
                    "Must have run the full pipeline at least once first",
        default=False,
    )
    debug: BoolProperty(
        name="Debug Mode",
        description="Import intermediate OBJ files as hidden objects for inspection",
        default=False,
    )

    # -- Quad density -----------------------------------------
    target_mode: EnumProperty(
        name="Target Mode",
        description="How the approximate QuadWild density target is defined",
        items=[
            ('RATIO', "Ratio", "Keep an approximate percentage of the current triangle-equivalent count"),
            ('DENSITY', "Density", "Compute an approximate target from triangle density and surface area"),
            ('TRIANGLE_COUNT', "Triangle Count", "Use an explicit approximate triangle-equivalent target"),
            ('VERTEX_COUNT', "Vertex Count", "Use an explicit approximate vertex target"),
        ],
        default='RATIO',
    )
    density_unit: EnumProperty(
        name="Unit",
        description="Surface-area unit used by Density target mode",
        items=[
            ('M2', "m^2", "Triangles per square meter"),
            ('CM2', "cm^2", "Triangles per square centimeter"),
        ],
        default='M2',
    )
    target_density: FloatProperty(
        name="Density",
        description="Approximate target triangle density used to compute QuadWild scale",
        default=4.0, min=0.0001, max=1000000.0,
    )
    target_ratio: FloatProperty(
        name="Keep Ratio",
        description="Approximate fraction of the current triangle-equivalent count to keep",
        default=1.0, min=0.001, max=1.0, precision=4,
    )
    target_vertex_count: IntProperty(
        name="Target Vertices",
        description="Approximate final vertex target. QuadWild maps this to a scale factor internally",
        default=10000, min=4, max=10000000,
    )
    target_triangle_count: IntProperty(
        name="Target Triangles",
        description="Approximate final triangle-equivalent target. QuadWild maps this to a scale factor internally",
        default=50000, min=4, max=10000000,
    )
    scale_fact: FloatProperty(
        name="Scale Factor",
        description="Values >1 produce larger quads; <1 preserves more detail",
        min=0.01, max=10.0, default=1.0, subtype='FACTOR',
    )
    fixed_chart_clusters: IntProperty(
        name="Fixed Chart Clusters",
        description="Fix the number of chart clusters (0 = automatic)",
        min=0, default=0,
    )

    # -- ILP solver -------------------------------------------
    alpha: FloatProperty(
        name="Alpha",
        description="Blends between isometry (alpha) and regularity (1-alpha)",
        default=0.005, min=0.0, max=0.999, precision=3, step=0.5, subtype='FACTOR',
    )
    ilp_method: EnumProperty(
        name="ILP Method",
        description="Integer Linear Programming solver variant",
        items=[
            ('LEASTSQUARES', "Least Squares", "Use least-squares ILP", 1),
            ('ABS',          "Absolute",      "Use absolute ILP",       2),
        ],
        default='LEASTSQUARES',
    )
    time_limit: IntProperty(
        name="Time Limit (s)",
        description="Maximum solver time in seconds",
        default=200, min=1,
    )
    gap_limit: FloatProperty(
        name="Gap Limit",
        description="Solver stops when optimality gap reaches this value",
        default=0.0, min=0.0,
    )
    minimum_gap: FloatProperty(
        name="Minimum Gap",
        description="Solver must reach at least this gap before early stopping",
        default=0.4, min=0.0,
    )

    # -- Solver flags -----------------------------------------
    isometry: BoolProperty(
        name="Isometry", description="Enable isometry term", default=True)
    regularity_quads: BoolProperty(
        name="Regularity Quads", description="Enable regularity for quadrilaterals", default=True)
    regularity_non_quads: BoolProperty(
        name="Regularity Non-Quads", description="Enable regularity for non-quadrilaterals", default=True)
    regularity_non_quads_weight: FloatProperty(
        name="Non-Quad Regularity Weight",
        description="Weight applied to the non-quad regularity term",
        default=0.9, min=0.0, max=1.0,
    )
    align_singularities: BoolProperty(
        name="Align Singularities", description="Enable singularity alignment", default=True)
    align_singularities_weight: FloatProperty(
        name="Singularity Alignment Weight",
        description="Weight for the singularity alignment term",
        default=0.1, min=0.0, max=1.0,
    )
    repeat_losing_iters: BoolProperty(
        name="Repeat Losing Iters",
        description="Repeat iterations when constraints are lost", default=True)
    repeat_losing_quads: BoolProperty(
        name="Repeat Losing Quads",
        description="Retry when quad regularity constraints are lost",
        default=False,
    )
    repeat_losing_non_quads: BoolProperty(
        name="Repeat Losing Non-Quads",
        description="Retry when non-quad regularity constraints are lost",
        default=False,
    )
    repeat_losing_align: BoolProperty(
        name="Repeat Losing Align",
        description="Retry when singularity alignment constraints are lost",
        default=True,
    )
    hard_parity: BoolProperty(
        name="Hard Parity Constraint", description="Enforce hard parity constraint", default=True)

    # -- Flow / Satsuma configs --------------------------------
    flow_config: EnumProperty(
        name="Flow Config",
        description="Preset used for the flow field stage of QuadWild",
        items=[
            ("SIMPLE", "Simple", "flow_virtual_simple.json", 1),
            ("HALF",   "Half",   "flow_virtual_half.json",   2),
        ],
        default="SIMPLE",
    )
    satsuma_config: EnumProperty(
        name="Satsuma Config",
        description="Clustering algorithm for Satsuma solver",
        items=[
            ("DEFAULT",    "Default",          "Default clustering algorithm"),
            ("MST",        "Approx-MST",       "Approximate Minimum Spanning Tree"),
            ("ROUND2EVEN", "Approx-Round2Even", "Round-to-Even approximation"),
            ("SYMMDC",     "Approx-Symmdc",    "Symmetric decomposition"),
            ("EDGETHRU",   "Edge Through",     "Edge-through clustering"),
            ("LEMON",      "Lemon",            "Lemon algorithm"),
            ("NODETHRU",   "Node Through",     "Node-through clustering"),
        ],
        default="DEFAULT",
    )

    # -- Solver callback schedule (8 checkpoints) --------------------
    callback_time_limit: FloatVectorProperty(
        name="Callback Time Limit",
        description="8 time checkpoints (seconds) at which the solver re-evaluates the gap",
        size=8,
        default=[3.0, 5.0, 10.0, 20.0, 30.0, 60.0, 90.0, 120.0],
    )
    callback_gap_limit: FloatVectorProperty(
        name="Callback Gap Limit",
        description="Gap thresholds corresponding to each time checkpoint",
        size=8, precision=3,
        default=[0.005, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.3],
    )


class UAVUVStandardMethodsProperties(PropertyGroup):
    """Properties for the native Blender UV tools exposed by the addon."""

    unwrap_method: EnumProperty(
        name="Method",
        description="Native Blender UV tool to execute",
        items=[
            ('SMART', "Smart UV Project", "Automatic seam placement based on angle"),
            ('ANGLE_BASED', "Angle Based", "ABF++ unwrap that favors low angular distortion"),
            ('CONFORMAL', "Conformal", "LSCM unwrap that preserves local proportions"),
            ('MINIMUM_STRETCH', "Minimum Stretch", "Relax an unwrap to minimize distortion"),
        ],
        default='SMART',
    )

    smart_uv_angle_limit: FloatProperty(
        name="Angle Limit",
        description="Angle threshold used by Smart UV Project",
        default=66.0, min=1.0, max=180.0, precision=1,
    )
    smart_uv_island_margin: FloatProperty(
        name="Island Margin",
        description="Gap created between islands by Smart UV Project",
        default=0.0, min=0.0, max=1.0, precision=4,
    )
    smart_uv_area_weight: FloatProperty(
        name="Area Weight",
        description="Area weighting used by Smart UV Project when clustering faces",
        default=0.0, min=0.0, max=1.0, precision=2,
    )

    unwrap_fill_holes: BoolProperty(
        name="Fill Holes",
        description="Fill holes while running unwrap/minimum stretch",
        default=True,
    )
    unwrap_correct_aspect: BoolProperty(
        name="Correct Aspect",
        description="Correct for image aspect ratio during unwrap",
        default=True,
    )
    unwrap_use_subsurf: BoolProperty(
        name="Use Subsurf Data",
        description="Use subdivision data while unwrapping",
        default=False,
    )
    unwrap_margin: FloatProperty(
        name="Margin",
        description="Island margin used by Angle Based and Conformal unwrap",
        default=0.001, min=0.0, max=1.0, precision=4,
    )

    min_stretch_iterations: IntProperty(
        name="Iterations",
        description="Iterations used by Blender's Minimum Stretch solver",
        default=10, min=1, max=1000,
    )
    min_stretch_blend: FloatProperty(
        name="Blend",
        description="Blend between the current layout and the relaxed result",
        default=0.0, min=0.0, max=1.0, precision=2,
    )

    density_mode: EnumProperty(
        name="Density Mode",
        description="How the texel density target is computed",
        items=[
            ('UNIFORM', "Uniform", "Match density across all islands"),
            ('ADAPTIVE', "Adaptive", "Give larger islands slightly more density"),
            ('MANUAL', "Manual", "Use an explicit pixels-per-meter target"),
        ],
        default='UNIFORM',
    )
    target_density: FloatProperty(
        name="Target Density (px/m)",
        description="Pixels per meter used by the manual texel density mode",
        default=512.0, min=1.0, max=16384.0,
    )
    density_bake_resolution: IntProperty(
        name="Reference Resolution",
        description="Texture resolution used to interpret the manual density target",
        default=4096, min=64, max=8192,
    )

    last_method_used: StringProperty(
        name="Last Method",
        description="Last native unwrap method executed by the addon",
        default="",
    )
    last_islands: IntProperty(
        name="Islands",
        description="Number of UV islands measured in the last analysis run",
        default=0,
    )
    last_stretch: FloatProperty(
        name="Stretch",
        description="Average UV stretch measured in the last analysis run",
        default=0.0, precision=3,
    )
    last_coverage: FloatProperty(
        name="Coverage",
        description="Atlas coverage percentage measured in the last analysis run",
        default=0.0, precision=1,
    )
    last_time: FloatProperty(
        name="Time",
        description="Execution time of the last unwrap-related operation",
        default=0.0, precision=2,
    )
    last_flipped: IntProperty(
        name="Flipped",
        description="Number of flipped UV faces detected in the last analysis run",
        default=0,
    )
    last_oob: IntProperty(
        name="OOB",
        description="Number of faces found outside the 0-1 UV range in the last analysis run",
        default=0,
    )
    last_avg_density: FloatProperty(
        name="Avg Density",
        description="Average texel density from the last analysis run",
        default=0.0, precision=4,
    )
    last_min_density: FloatProperty(
        name="Min Density",
        description="Lowest texel density from the last analysis run",
        default=0.0, precision=4,
    )
    last_max_density: FloatProperty(
        name="Max Density",
        description="Highest texel density from the last analysis run",
        default=0.0, precision=4,
    )



class UAVUVPackProperties(PropertyGroup):
    """All UV packing parameters. Registered as Scene.uav_uvpack_props."""

    pack_engine: EnumProperty(
        name="Engine",
        description="Which packing backend to use",
        items=UV_PACK_ENGINE_ITEMS,
        default='AUTO',
    )
    uvpm_engine_path: StringProperty(
        name="UVPackmaster Path",
        description=(
            "Optional UVPackmaster install root or direct engine3 path. "
            "If empty, the addon auto-detects the installation from registry or the default Program Files path"
        ),
        default="",
        subtype='DIR_PATH',
    )
    native_shape_method: EnumProperty(
        name="Shape Method",
        description="Island shape used by Blender's native packer",
        items=[
            ('CONCAVE', "Concave",      "Best fit using concave outlines"),
            ('CONVEX',  "Convex",       "Fit using convex hulls"),
            ('AABB',    "Bounding Box", "Fast axis-aligned bounding boxes"),
        ],
        default='CONCAVE',
    )
    native_merge_overlap: BoolProperty(
        name="Merge Overlap",
        description="Treat overlapping islands as a single unit before packing",
        default=False,
    )
    lock_overlapping_enable: BoolProperty(
        name="Lock Overlapping",
        description="Forward overlapping-island lock mode to UVPackmaster addon",
        default=False,
    )
    lock_overlapping_mode: EnumProperty(
        name="Lock Overlapping Mode",
        description="UVPackmaster overlapping-island lock mode",
        items=[
            ('0', "Any Part", "Lock islands when any UV area overlaps"),
            ('1', "Exact", "Lock exactly overlapping islands"),
            ('2', "UV Island", "Use UV island based overlap locking"),
        ],
        default='0',
    )
    uvp3_packing_method: StringProperty(
        name="UVPM3 Mode",
        description="UVPackmaster 3 mode_id used for versions before the 3.4 option-set API",
        default="pack.single_tile",
    )

    packing_method: EnumProperty(
        name="Algorithm",
        description="Base rectangle-packing algorithm",
        items=[
            ('MAXRECTS', "MaxRects",
             "Maximum Rectangles: tracks all free regions and picks the best fit. "
             "Generally achieves the highest packing density"),
            ('SKYLINE',  "Skyline",
             "Skyline Bottom-Left: fast heuristic that maintains a horizon line. "
             "Good results with lower overhead"),
            ('PIXEL',    "Pixel Perfect",
             "Rasterized island packing with pixel-accurate overlap tests"),
            ('HORIZON',  "Horizon Best Fit",
             "Mask-based horizon search that scores candidate placements to minimize final atlas height. "
             "Best choice when you want the packer to occupy as much UV space as possible"),
        ],
        default='MAXRECTS',
    )
    maxrects_heuristic: EnumProperty(
        name="Heuristic",
        description="Scoring function used by MaxRects to choose a free rectangle",
        items=[
            ('BSSF', "Best Short Side",  "Minimizes the shorter leftover side - usually the best default"),
            ('BLSF', "Best Long Side",   "Minimises the longer leftover side"),
            ('BAF',  "Best Area Fit",    "Minimises wasted area in the chosen free rectangle"),
            ('BL',   "Bottom-Left",      "Lowest then leftmost position"),
            ('CP',   "Contact Point",    "Maximises contact perimeter with borders and islands"),
        ],
        default='BSSF',
    )
    optimizer: EnumProperty(
        name="Optimizer",
        description="Search strategy for island order and rotation",
        items=[
            ('ITERATIVE', "Iterative",
             "Systematic search through sort strategies and random variations. Fast"),
            ('SA',        "Simulated Annealing",
             "Physics-inspired optimizer that escapes local optima. "
             "Slower but often finds better solutions"),
            ('NONE',      "None",
             "No optimization - area-descending order, no rotation. Fastest"),
        ],
        default='ITERATIVE',
    )
    precision: IntProperty(
        name="Precision",
        description="Maximum number of optimisation iterations",
        default=500, min=1, max=10000,
    )
    margin: FloatProperty(
        name="Margin (UV)",
        description="Gap between UV islands in UV space to prevent texture bleeding",
        default=0.003, min=0.0, max=0.1, precision=4, step=0.01,
    )
    rotation_enable: BoolProperty(
        name="Allow Rotation",
        description="Allow islands to be rotated for a better fit",
        default=True,
    )
    rotation_step: EnumProperty(
        name="Rotation Step",
        description="Angle increment tested during rotation search",
        items=[
            ('90', "90 deg", "Test 0 and 90 degrees only - fastest"),
            ('45', "45 deg", "Test every 45 degrees"),
            ('30', "30 deg", "Test every 30 degrees"),
            ('15', "15 deg", "Test every 15 degrees - slowest"),
        ],
        default='90',
    )
    scale_mode: EnumProperty(
        name="Scale Mode",
        description="How to scale islands after packing",
        items=[
            ('MAX_SCALE', "Max Scale",
             "Scale up to fill the entire UV 0-1 space. Maximizes texel density"),
            ('LOCKED',    "Locked",
             "Keep the relative scale from packing; do not enlarge"),
            ('CUSTOM',    "Custom",
             "Apply a user-defined scale factor after packing"),
        ],
        default='MAX_SCALE',
    )
    custom_scale: FloatProperty(
        name="Custom Scale",
        description="Manual scale factor applied after packing (Scale Mode = Custom)",
        default=1.0, min=0.01, max=10.0, precision=3,
    )
    density_weight: FloatProperty(
        name="Density Weight",
        description="Blend between the current UV scale and a texel-density-aware island scale",
        default=0.0, min=0.0, max=1.0, precision=2,
    )
    pixel_margin_enable: BoolProperty(
        name="Pixel Margin",
        description="Define margin in pixels instead of UV units",
        default=False,
    )
    pixel_margin: IntProperty(
        name="Margin (px)",
        description="Gap between islands in pixels",
        default=5, min=0, max=64,
    )
    texture_size: IntProperty(
        name="Texture Size",
        description="Target texture resolution used to convert pixel margin to UV units",
        default=1024, min=64, max=8192,
    )
    pixel_resolution: IntProperty(
        name="Pixel Resolution",
        description="Resolution of the pixel-accurate raster mask used by the Pixel Perfect solver",
        default=64, min=32, max=256,
    )
    search_time: FloatProperty(
        name="Search Time (s)",
        description=(
            "Maximum wall-clock time for the optimiser. 0 = no limit for C++; "
            "UVPackmaster addon direct calls use a safe 10s heuristic timeout"
        ),
        default=0.0, min=0.0, max=120.0, precision=1,
    )
    advanced_heuristic: BoolProperty(
        name="Advanced Heuristic",
        description="Enable UVPackmaster heuristic search and the C++ per-island rotation refinement pass",
        default=True,
    )
    sa_initial_temp: FloatProperty(
        name="Initial Temperature",
        description="Starting temperature for Simulated Annealing",
        default=1.0, min=0.01, max=10.0, precision=2,
    )
    sa_cooling_rate: FloatProperty(
        name="Cooling Rate",
        description="Temperature multiplier per step (0.9-0.999)",
        default=0.997, min=0.9, max=0.9999, precision=4,
    )
    last_occupancy: FloatProperty(
        name="Last Occupancy",
        description="Occupancy reached by the last completed packing run",
        default=0.0, precision=2,
    )
    last_iterations: IntProperty(
        name="Last Iterations",
        description="Number of iterations executed in the last completed packing run",
        default=0,
    )
    last_time: FloatProperty(
        name="Last Time",
        description="Execution time of the last completed packing run",
        default=0.0, precision=2,
    )
    last_method: StringProperty(
        name="Last Method",
        description="Packing method or backend used in the last completed run",
        default="",
    )
    run_counter: IntProperty(
        name="Run Counter",
        description="How many packing runs have been executed in this session",
        default=0,
    )
    best_ever_occupancy: FloatProperty(
        name="Best Ever Occupancy",
        description="Best UV occupancy achieved across all packing runs.",
        default=0.0, precision=4,
    )


class UAVBakeProperties(PropertyGroup):
    """All baking parameters. Registered as Scene.uav_bake_props."""

    # -- Source / target objects ---------------------------------
    highpoly_object: PointerProperty(
        name="High-Poly Source",
        description="The dense source mesh to project detail FROM. "
                    "Select the low-poly object as active before baking",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'MESH',
    )

    # -- Bake type -----------------------------------------------
    bake_type: EnumProperty(
        name="Bake Type",
        description="Which map to bake",
        items=[
            ('ALBEDO', "Albedo",
             "Diffuse colour only (no lighting). "
             "Saved with suffix _albedo"),
            ('AO',     "Ambient Occlusion",
             "Occlusion pass. Saved with suffix _ao"),
            ('NORMAL', "Normal",
             "Tangent-space normal map. Saved with suffix _normal"),
            ('ROUGHNESS', "Roughness",
             "Surface roughness. Saved with suffix _roughness"),
            ('METALLIC', "Metallic",
             "Metallic / metalness mask. Saved with suffix _metallic"),
            ('EMISSION', "Emission",
             "Emission colour. Saved with suffix _emission"),
            ('PBR', "PBR Set",
             "Bake a full PBR texture set and wire the maps into the low-poly materials"),
        ],
        default='NORMAL',
    )
    pbr_use_albedo: BoolProperty(
        name="Albedo",
        description="Bake the base colour map in PBR mode",
        default=True,
    )
    pbr_use_ao: BoolProperty(
        name="AO",
        description="Bake ambient occlusion in PBR mode",
        default=True,
    )
    pbr_use_normal: BoolProperty(
        name="Normal",
        description="Bake the normal map in PBR mode",
        default=True,
    )
    pbr_use_roughness: BoolProperty(
        name="Roughness",
        description="Bake roughness in PBR mode",
        default=True,
    )
    pbr_use_metallic: BoolProperty(
        name="Metallic",
        description="Bake metallic / metalness in PBR mode",
        default=False,
    )
    pbr_use_emission: BoolProperty(
        name="Emission",
        description="Bake emission colour in PBR mode",
        default=False,
    )

    # -- Output --------------------------------------------------
    texture_name: StringProperty(
        name="Texture Name",
        description="Base name for the baked texture. "
                    "The appropriate suffix is appended automatically",
        default="",
    )
    texture_size: EnumProperty(
        name="Texture Size",
        description="Resolution of the output texture",
        items=[
            ('512',  "512 x 512",   "Low resolution - fast bake"),
            ('1024', "1K (1024)",   "Medium resolution"),
            ('2048', "2K (2048)",   "High resolution - recommended"),
            ('4096', "4K (4096)",   "Ultra - requires more VRAM and time"),
        ],
        default='2048',
    )
    output_dir: StringProperty(
        name="Output Folder",
        description="Where to save the PNG. Leave empty to save next to the .blend file",
        default="",
        subtype='DIR_PATH',
    )

    # -- Bake quality --------------------------------------------
    samples: IntProperty(
        name="Samples",
        description="Cycles samples used during baking. "
                    "Higher = less noise (AO). Normal/Albedo only need 1-4",
        default=16, min=1, max=1024,
    )
    margin: IntProperty(
        name="Margin (px)",
        description="Island edge bleed in pixels to avoid seam artefacts",
        default=16, min=0, max=64,
    )
    cage_extrusion: FloatProperty(
        name="Cage Extrusion",
        description="How far rays are cast outward from the low-poly surface "
                    "to intersect the high-poly. Increase for meshes with large "
                    "displacement",
        default=0.05, min=0.0, max=10.0, precision=3,
        subtype='DISTANCE', unit='LENGTH',
    )
    max_ray_distance: FloatProperty(
        name="Max Ray Distance",
        description="Maximum ray length for selected-to-active projection. "
                    "0 = unlimited",
        default=0.0, min=0.0, max=100.0, precision=3,
        subtype='DISTANCE', unit='LENGTH',
    )

    # -- Normal map options --------------------------------------
    normal_space: EnumProperty(
        name="Normal Space",
        description="Coordinate space for the normal map",
        items=[
            ('TANGENT', "Tangent", "Standard tangent-space normals (for game engines)"),
            ('OBJECT',  "Object",  "Object-space normals"),
        ],
        default='TANGENT',
    )

    # -- Results (read-only display) -----------------------------
    last_bake_type: StringProperty(
        name="Last Type",
        description="Type of map baked in the most recent bake run",
        default="",
    )
    last_bake_path: StringProperty(
        name="Last Path",
        description="Output path from the most recent bake run",
        default="",
    )
    last_bake_time: FloatProperty(
        name="Last Time (s)",
        description="Execution time of the most recent bake run",
        default=0.0, precision=2,
    )
    last_bake_count: IntProperty(
        name="Last Count",
        description="Number of maps produced in the most recent bake run",
        default=0,
    )
    last_bake_ok: BoolProperty(
        name="Last OK",
        description="Whether the most recent bake run finished successfully",
        default=False,
    )


class UAVLODProperties(PropertyGroup):
    """Parameters for LOD generation. Registered as Scene.uav_lod_props."""

    lod_ratio: FloatProperty(
        name="Reduction Ratio",
        description=(
            "Fraction of triangles kept at each level. "
            "0.5 means each new LOD keeps about half of the previous triangle count"
        ),
        default=0.5, min=0.1, max=0.9, precision=2, step=5, subtype='FACTOR',
    )
    lod_min_polycount: IntProperty(
        name="Min Polycount (Final LOD)",
        description="Target triangle count for the simplest generated LOD",
        default=1000, min=4, max=10000000,
    )
    lod_max_levels: IntProperty(
        name="Max Levels",
        description="Maximum number of generated LOD levels",
        default=8, min=1, max=16,
    )
    lod_collection_name: StringProperty(
        name="Collection Name",
        description="Collection used to store generated LOD objects. Leave empty to use '<object>_LOD'",
        default="",
    )

    preview_base_tris: IntProperty(
        name="Base Tris",
        description="Triangle count of the source mesh used for the last preview",
        default=0,
    )
    preview_levels: IntProperty(
        name="Levels",
        description="How many LOD levels would be generated by the last preview",
        default=0,
    )
    preview_final_tris: IntProperty(
        name="Final Tris",
        description="Estimated triangle count of the final generated LOD from the last preview",
        default=0,
    )


class UAVExportProperties(PropertyGroup):
    """Parameters for engine export. Registered as Scene.uav_export_props."""

    target_engine: EnumProperty(
        name="Target Engine",
        description="Engine preset used for FBX axis, scale and tangent export",
        items=[
            ("UNREAL", "Unreal Engine", "Z-up FBX preset with -X forward"),
            ("UNITY", "Unity", "Y-up FBX preset with -Z forward"),
        ],
        default="UNREAL",
    )
    scope: EnumProperty(
        name="Scope",
        description="Which objects are exported",
        items=[
            ("ACTIVE", "Active Object", "Export only the active object"),
            ("SELECTED", "Selected Objects", "Export all selected mesh, armature and empty objects"),
            ("LOD_COLLECTION", "LOD Collection", "Export the generated LOD collection"),
        ],
        default="LOD_COLLECTION",
    )
    output_dir: StringProperty(
        name="Output Folder",
        description="Destination folder for the FBX package. Leave empty to use the .blend folder",
        default="",
        subtype="DIR_PATH",
    )
    asset_name: StringProperty(
        name="Asset Name",
        description="Base filename for the exported FBX. Leave empty to derive it from the object or LOD collection",
        default="",
    )
    collection_name: StringProperty(
        name="LOD Collection",
        description="Collection exported when Scope is LOD Collection. Leave empty to reuse the LOD stage collection",
        default="",
    )
    collection_ref: PointerProperty(
        name="LOD Collection",
        description="Collection exported when Scope is LOD Collection",
        type=Collection,
    )
    global_scale: FloatProperty(
        name="Global Scale",
        description="Scale multiplier passed to Blender's FBX exporter",
        default=1.0, min=0.0001, max=100000.0, precision=4,
    )
    include_textures: BoolProperty(
        name="Copy Material Textures",
        description="Copy image textures referenced by exported materials next to the FBX package",
        default=True,
    )
    texture_subdir: StringProperty(
        name="Texture Folder",
        description="Subfolder used for copied material textures",
        default="Textures",
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Evaluate mesh modifiers during FBX export",
        default=True,
    )
    export_tangents: BoolProperty(
        name="Export Tangents",
        description="Export tangent-space data for normal maps",
        default=True,
    )
    triangulate: BoolProperty(
        name="Triangulate",
        description="Triangulate faces during FBX export. Keep off if the engine importer should triangulate",
        default=False,
    )
    use_custom_props: BoolProperty(
        name="Custom Properties",
        description="Include Blender custom properties in the FBX metadata",
        default=False,
    )
    last_export_path: StringProperty(
        name="Last Path",
        description="FBX path produced by the most recent engine export",
        default="",
    )
    last_texture_dir: StringProperty(
        name="Last Texture Folder",
        description="Texture folder produced by the most recent engine export",
        default="",
    )
    last_export_time: FloatProperty(
        name="Last Time (s)",
        description="Execution time of the most recent engine export",
        default=0.0, precision=2,
    )
    last_object_count: IntProperty(
        name="Last Object Count",
        description="Number of objects exported in the most recent engine export",
        default=0,
    )
    last_export_ok: BoolProperty(
        name="Last OK",
        description="Whether the most recent engine export finished successfully",
        default=False,
    )

import bpy
from bpy.props import (
    IntProperty, FloatProperty, BoolProperty,
    EnumProperty, StringProperty, FloatVectorProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup

class UAVOptimizerProperties(PropertyGroup):

    # ==========================================
    # UI Foldouts
    # ==========================================
    ui_show_preprocess: BoolProperty(name="Show Pre-Processing", default=True)
    ui_show_qem: BoolProperty(name="Show QEM", default=True)
    ui_show_retopo: BoolProperty(name="Show Retopology", default=False)
    ui_show_grid_seams: BoolProperty(name="Show Grid Seams", default=False)
    ui_show_uv_unwrap: BoolProperty(name="Show UV Unwrap", default=False)
    ui_show_uv_pack: BoolProperty(name="Show UV Pack", default=False)
    ui_show_bake: BoolProperty(name="Show Bake", default=False)


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
            ('RATIO', "Ratio", "Keep a percentage of the current vertices"),
            ('VERTEX_COUNT', "Vertex Count", "Use an explicit target vertex count"),
        ],
        default='DENSITY'
    )
    qem_density_unit: EnumProperty(
        name="Unit",
        items=[('M2', "m²", "Triangles per square metre"),
               ('CM2', "cm²", "Triangles per square centimetre")],
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
        name="Repeat Losing Quads", default=False)
    repeat_losing_non_quads: BoolProperty(
        name="Repeat Losing Non-Quads", default=False)
    repeat_losing_align: BoolProperty(
        name="Repeat Losing Align", default=True)
    hard_parity: BoolProperty(
        name="Hard Parity Constraint", description="Enforce hard parity constraint", default=True)

    # -- Flow / Satsuma configs --------------------------------
    flow_config: EnumProperty(
        name="Flow Config",
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

    last_method_used: StringProperty(name="Last Method", default="")
    last_islands: IntProperty(name="Islands", default=0)
    last_stretch: FloatProperty(name="Stretch", default=0.0, precision=3)
    last_coverage: FloatProperty(name="Coverage", default=0.0, precision=1)
    last_time: FloatProperty(name="Time", default=0.0, precision=2)
    last_flipped: IntProperty(name="Flipped", default=0)
    last_oob: IntProperty(name="OOB", default=0)
    last_avg_density: FloatProperty(name="Avg Density", default=0.0, precision=4)
    last_min_density: FloatProperty(name="Min Density", default=0.0, precision=4)
    last_max_density: FloatProperty(name="Max Density", default=0.0, precision=4)



class UAVUVPackProperties(PropertyGroup):
    """All UV packing parameters. Registered as Scene.uav_uvpack_props."""

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
        ],
        default='MAXRECTS',
    )
    maxrects_heuristic: EnumProperty(
        name="Heuristic",
        description="Scoring function used by MaxRects to choose a free rectangle",
        items=[
            ('BSSF', "Best Short Side",  "Minimises the shorter leftover side — usually best"),
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
             "No optimisation — area-descending order, no rotation. Fastest"),
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
            ('90', "90°", "Test 0° and 90° only — fast"),
            ('45', "45°", "Test every 45°"),
            ('30', "30°", "Test every 30°"),
            ('15', "15°", "Test every 15° — slowest"),
        ],
        default='90',
    )
    scale_mode: EnumProperty(
        name="Scale Mode",
        description="How to scale islands after packing",
        items=[
            ('MAX_SCALE', "Max Scale",
             "Scale up to fill the entire UV 0–1 space. Maximises texel density"),
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
    search_time: FloatProperty(
        name="Search Time (s)",
        description="Maximum wall-clock time for the optimiser. 0 = no limit",
        default=0.0, min=0.0, max=120.0, precision=1,
    )
    advanced_heuristic: BoolProperty(
        name="Advanced Heuristic",
        description="Extra per-island rotation refinement pass after main optimisation",
        default=False,
    )
    sa_initial_temp: FloatProperty(
        name="Initial Temperature",
        description="Starting temperature for Simulated Annealing",
        default=1.0, min=0.01, max=10.0, precision=2,
    )
    sa_cooling_rate: FloatProperty(
        name="Cooling Rate",
        description="Temperature multiplier per step (0.9–0.999)",
        default=0.997, min=0.9, max=0.9999, precision=4,
    )
    last_occupancy:  FloatProperty(name="Last Occupancy",   default=0.0, precision=2)
    last_iterations: IntProperty(  name="Last Iterations",  default=0)
    last_time:       FloatProperty(name="Last Time",        default=0.0, precision=2)
    last_method:     StringProperty(name="Last Method",     default="")
    run_counter:     IntProperty(  name="Run Counter",      default=0)
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
        ],
        default='NORMAL',
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
            ('512',  "512 x 512",   "Low resolution — fast bake"),
            ('1024', "1K (1024)",   "Medium resolution"),
            ('2048', "2K (2048)",   "High resolution — recommended"),
            ('4096', "4K (4096)",   "Ultra — requires more VRAM and time"),
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
    last_bake_type:  StringProperty(name="Last Type",    default="")
    last_bake_path:  StringProperty(name="Last Path",    default="")
    last_bake_time:  FloatProperty( name="Last Time (s)", default=0.0, precision=2)
    last_bake_ok:    BoolProperty(  name="Last OK",      default=False)


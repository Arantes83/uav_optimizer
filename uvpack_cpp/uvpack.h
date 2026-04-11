#pragma once

#ifdef _WIN32
  #define UVPACK_API extern "C" __declspec(dllexport)
#else
  #define UVPACK_API extern "C" __attribute__((visibility("default")))
#endif

struct UVIsland {
    int   id;
    float w;
    float h;
    float area;
};

struct UVPlacement {
    int   id;
    float x;
    float y;
    float angle;
};

enum UVMethod    { UV_MAXRECTS = 0, UV_SKYLINE = 1 };
enum UVHeuristic { UV_BSSF = 0, UV_BLSF = 1, UV_BAF = 2, UV_BL = 3, UV_CP = 4 };
enum UVOptimizer { UV_OPT_NONE = 0, UV_OPT_ITERATIVE = 1, UV_OPT_SA = 2 };

struct UVPackConfig {
    int   method;
    int   heuristic;
    int   optimizer;
    float margin;
    int   max_iter;
    float time_limit;
    int   rotation_step;
    float sa_initial_temp;
    float sa_cooling_rate;
    float min_occupancy;
};

UVPACK_API float       uvpack_run(const UVIsland* islands, int n_islands,
                                  const UVPackConfig* config, UVPlacement* out_placements);
UVPACK_API const char* uvpack_version(void);

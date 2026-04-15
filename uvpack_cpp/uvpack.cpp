#include "uvpack.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <limits>
#include <numeric>
#include <random>
#include <utility>
#include <vector>

static const float INF = std::numeric_limits<float>::infinity();

struct IslandInfo {
    float w;
    float h;
    float area;
};

struct Place {
    float x;
    float y;
    float angle;
};

struct SkySeg {
    float x;
    float y;
    float w;
};

struct Rect {
    float x;
    float y;
    float w;
    float h;
};

struct PixelMask {
    std::vector<uint8_t> data;
    int w = 0;
    int h = 0;
};

struct PixelVariant {
    float angle = 0.0f;
    PixelMask mask;
    PixelMask padded_mask;
    std::vector<int> bottom;
    std::vector<int> top;
    std::vector<int> padded_bottom;
    std::vector<int> padded_top;
};

struct PixelIsland {
    std::vector<PixelVariant> variants;
};

static void rotdims(float w, float h, float deg, float& rw, float& rh) {
    if (std::abs(deg) < 0.01f) {
        rw = w;
        rh = h;
        return;
    }
    if (std::abs(deg - 90.0f) < 0.01f || std::abs(deg - 270.0f) < 0.01f) {
        rw = h;
        rh = w;
        return;
    }
    const float rad = deg * 3.14159265358979323846f / 180.0f;
    const float ca = std::abs(std::cos(rad));
    const float sa = std::abs(std::sin(rad));
    rw = w * ca + h * sa;
    rh = w * sa + h * ca;
}

static int mask_size_px(float length, int res) {
    return std::max(1, std::min(res, static_cast<int>(std::ceil(std::max(0.0f, length) * res))));
}

struct Skyline {
    std::vector<SkySeg> sky;

    Skyline() { sky.push_back({0.0f, 0.0f, 1.0f}); }

    bool insert(float rw, float rh, float& ox, float& oy) {
        float best_y = INF;
        float best_x = 0.0f;
        int best_index = -1;

        for (int index = 0; index < static_cast<int>(sky.size()); ++index) {
            if (sky[index].x + rw > 1.0f + 1e-9f) {
                continue;
            }

            float max_y = 0.0f;
            float remaining = rw;
            int cursor = index;
            while (remaining > 1e-9f && cursor < static_cast<int>(sky.size())) {
                max_y = std::max(max_y, sky[cursor].y);
                remaining -= sky[cursor].w;
                ++cursor;
            }
            if (remaining > 1e-9f) {
                continue;
            }

            if (max_y < best_y - 1e-9f ||
                (std::abs(max_y - best_y) < 1e-9f && sky[index].x < best_x)) {
                best_y = max_y;
                best_x = sky[index].x;
                best_index = index;
            }
        }

        if (best_index == -1) {
            best_y = 0.0f;
            for (const auto& segment : sky) {
                best_y = std::max(best_y, segment.y);
            }
            best_x = 0.0f;
        }

        ox = best_x;
        oy = best_y;

        const float top = best_y + rh;
        const float placed_end = best_x + rw;
        std::vector<SkySeg> next;
        bool inserted = false;
        for (const auto& segment : sky) {
            const float segment_end = segment.x + segment.w;
            if (segment_end <= best_x + 1e-9f) {
                next.push_back(segment);
            } else if (segment.x >= placed_end - 1e-9f) {
                if (!inserted) {
                    next.push_back({best_x, top, rw});
                    inserted = true;
                }
                next.push_back(segment);
            } else {
                if (segment.x < best_x - 1e-9f) {
                    next.push_back({segment.x, segment.y, best_x - segment.x});
                }
                if (!inserted) {
                    next.push_back({best_x, top, rw});
                    inserted = true;
                }
                if (segment_end > placed_end + 1e-9f) {
                    next.push_back({placed_end, segment.y, segment_end - placed_end});
                }
            }
        }
        if (!inserted) {
            next.push_back({best_x, top, rw});
        }

        sky.clear();
        for (const auto& segment : next) {
            if (!sky.empty() &&
                std::abs(sky.back().y - segment.y) < 1e-9f &&
                std::abs(sky.back().x + sky.back().w - segment.x) < 1e-9f) {
                sky.back().w += segment.w;
            } else {
                sky.push_back(segment);
            }
        }
        return true;
    }

    float height() const {
        float h = 0.0f;
        for (const auto& segment : sky) {
            h = std::max(h, segment.y);
        }
        return h;
    }
};

struct MaxRects {
    std::vector<Rect> free_rects;
    std::vector<Rect> used_rects;

    MaxRects() { free_rects.push_back({0.0f, 0.0f, 1.0f, 1e9f}); }

    std::pair<float, float> score(const Rect& rect, float rw, float rh, int heuristic) const {
        const float leftover_w = rect.w - rw;
        const float leftover_h = rect.h - rh;
        switch (heuristic) {
            case UV_BSSF:
                return {std::min(leftover_w, leftover_h), std::max(leftover_w, leftover_h)};
            case UV_BLSF:
                return {std::max(leftover_w, leftover_h), std::min(leftover_w, leftover_h)};
            case UV_BAF:
                return {leftover_w * leftover_h, std::min(leftover_w, leftover_h)};
            case UV_BL:
                return {rect.y, rect.x};
            case UV_CP: {
                float contact = 0.0f;
                if (rect.x < 1e-9f) contact += rh;
                if (rect.y < 1e-9f) contact += rw;
                if (std::abs(rect.x + rw - 1.0f) < 1e-9f) contact += rh;
                for (const auto& used : used_rects) {
                    if (std::abs(rect.x - (used.x + used.w)) < 1e-9f || std::abs(rect.x + rw - used.x) < 1e-9f) {
                        const float overlap = std::min(rect.y + rh, used.y + used.h) - std::max(rect.y, used.y);
                        if (overlap > 0.0f) {
                            contact += overlap;
                        }
                    }
                    if (std::abs(rect.y - (used.y + used.h)) < 1e-9f || std::abs(rect.y + rh - used.y) < 1e-9f) {
                        const float overlap = std::min(rect.x + rw, used.x + used.w) - std::max(rect.x, used.x);
                        if (overlap > 0.0f) {
                            contact += overlap;
                        }
                    }
                }
                return {-contact, std::min(leftover_w, leftover_h)};
            }
            default:
                return {std::min(leftover_w, leftover_h), std::max(leftover_w, leftover_h)};
        }
    }

    void split(const Rect& placed) {
        std::vector<Rect> next;
        next.reserve(free_rects.size() * 2);
        for (const auto& rect : free_rects) {
            if (placed.x >= rect.x + rect.w - 1e-9f || placed.x + placed.w <= rect.x + 1e-9f ||
                placed.y >= rect.y + rect.h - 1e-9f || placed.y + placed.h <= rect.y + 1e-9f) {
                next.push_back(rect);
                continue;
            }
            if (placed.x > rect.x + 1e-9f) {
                next.push_back({rect.x, rect.y, placed.x - rect.x, rect.h});
            }
            if (placed.x + placed.w < rect.x + rect.w - 1e-9f) {
                next.push_back({placed.x + placed.w, rect.y, rect.x + rect.w - placed.x - placed.w, rect.h});
            }
            if (placed.y > rect.y + 1e-9f) {
                next.push_back({rect.x, rect.y, rect.w, placed.y - rect.y});
            }
            if (placed.y + placed.h < rect.y + rect.h - 1e-9f) {
                next.push_back({rect.x, placed.y + placed.h, rect.w, rect.y + rect.h - placed.y - placed.h});
            }
        }
        free_rects = std::move(next);
    }

    void prune() {
        const int count = static_cast<int>(free_rects.size());
        std::vector<bool> skip(count, false);
        for (int i = 0; i < count; ++i) {
            if (skip[i]) {
                continue;
            }
            for (int j = 0; j < count; ++j) {
                if (i == j || skip[j]) {
                    continue;
                }
                const auto& a = free_rects[i];
                const auto& b = free_rects[j];
                if (a.x >= b.x - 1e-9f && a.y >= b.y - 1e-9f &&
                    a.x + a.w <= b.x + b.w + 1e-9f &&
                    a.y + a.h <= b.y + b.h + 1e-9f) {
                    skip[i] = true;
                    break;
                }
            }
        }

        std::vector<Rect> next;
        next.reserve(count);
        for (int i = 0; i < count; ++i) {
            if (!skip[i]) {
                next.push_back(free_rects[i]);
            }
        }
        free_rects = std::move(next);
    }

    bool insert(float rw, float rh, int heuristic, float& ox, float& oy) {
        int best_index = -1;
        std::pair<float, float> best_score = {INF, INF};
        for (int index = 0; index < static_cast<int>(free_rects.size()); ++index) {
            const auto& rect = free_rects[index];
            if (rw <= rect.w + 1e-9f && rh <= rect.h + 1e-9f) {
                const auto score_value = score(rect, rw, rh, heuristic);
                if (score_value < best_score) {
                    best_score = score_value;
                    best_index = index;
                }
            }
        }
        if (best_index == -1) {
            return false;
        }
        Rect placed = {
            free_rects[best_index].x,
            free_rects[best_index].y,
            rw,
            rh,
        };
        ox = placed.x;
        oy = placed.y;
        used_rects.push_back(placed);
        split(placed);
        prune();
        return true;
    }

    float height() const {
        float h = 0.0f;
        for (const auto& rect : used_rects) {
            h = std::max(h, rect.y + rect.h);
        }
        return h;
    }
};

struct PixelAtlas {
    int res;
    std::vector<uint8_t> data;

    explicit PixelAtlas(int resolution) : res(resolution), data(static_cast<size_t>(resolution) * resolution, 0) {}

    bool fits(const PixelMask& mask, int px, int py) const {
        if (mask.w > res || mask.h > res) {
            return false;
        }
        for (int row = 0; row < mask.h; ++row) {
            const uint8_t* src = mask.data.data() + row * res;
            const uint8_t* dst = data.data() + (py + row) * res + px;
            int col = 0;
            for (; col + 8 <= mask.w; col += 8) {
                uint64_t src_chunk = 0;
                uint64_t dst_chunk = 0;
                std::memcpy(&src_chunk, src + col, sizeof(uint64_t));
                std::memcpy(&dst_chunk, dst + col, sizeof(uint64_t));
                if ((src_chunk & dst_chunk) != 0) {
                    return false;
                }
            }
            for (; col < mask.w; ++col) {
                if (src[col] && dst[col]) {
                    return false;
                }
            }
        }
        return true;
    }

    void place(const PixelMask& mask, int px, int py) {
        for (int row = 0; row < mask.h; ++row) {
            const uint8_t* src = mask.data.data() + row * res;
            uint8_t* dst = data.data() + (py + row) * res + px;
            int col = 0;
            for (; col + 8 <= mask.w; col += 8) {
                uint64_t src_chunk = 0;
                uint64_t dst_chunk = 0;
                std::memcpy(&src_chunk, src + col, sizeof(uint64_t));
                std::memcpy(&dst_chunk, dst + col, sizeof(uint64_t));
                dst_chunk |= src_chunk;
                std::memcpy(dst + col, &dst_chunk, sizeof(uint64_t));
            }
            for (; col < mask.w; ++col) {
                dst[col] = static_cast<uint8_t>(dst[col] | src[col]);
            }
        }
    }

    std::pair<int, int> find_position(const PixelMask& mask) const {
        if (mask.w > res || mask.h > res) {
            return {-1, -1};
        }
        for (int py = 0; py <= res - mask.h; ++py) {
            for (int px = 0; px <= res - mask.w; ++px) {
                if (fits(mask, px, py)) {
                    return {px, py};
                }
            }
        }
        return {-1, -1};
    }
};

struct HorizonCandidate {
    int x = -1;
    int y = -1;
    int height = std::numeric_limits<int>::max();
    int gap = std::numeric_limits<int>::max();
    int contact = -1;
};

struct HorizonAtlas {
    int res;
    std::vector<uint8_t> data;
    std::vector<int> column_tops;
    int max_height = 0;

    explicit HorizonAtlas(int resolution)
        : res(resolution),
          data(static_cast<size_t>(resolution) * resolution, 0),
          column_tops(resolution, 0) {}

    bool fits(const PixelMask& mask, int px, int py) const {
        if (mask.w > res || mask.h > res) {
            return false;
        }
        for (int row = 0; row < mask.h; ++row) {
            const uint8_t* src = mask.data.data() + row * res;
            const uint8_t* dst = data.data() + (py + row) * res + px;
            int col = 0;
            for (; col + 8 <= mask.w; col += 8) {
                uint64_t src_chunk = 0;
                uint64_t dst_chunk = 0;
                std::memcpy(&src_chunk, src + col, sizeof(uint64_t));
                std::memcpy(&dst_chunk, dst + col, sizeof(uint64_t));
                if ((src_chunk & dst_chunk) != 0) {
                    return false;
                }
            }
            for (; col < mask.w; ++col) {
                if (src[col] && dst[col]) {
                    return false;
                }
            }
        }
        return true;
    }

    HorizonCandidate find_position(const PixelMask& mask,
                                   const std::vector<int>& bottom,
                                   const std::vector<int>& top) const {
        HorizonCandidate best;
        if (mask.w > res || mask.h > res) {
            return best;
        }
        const int max_y = res - mask.h;
        for (int px = 0; px <= res - mask.w; ++px) {
            int py = 0;
            bool has_pixels = false;
            for (int col = 0; col < mask.w; ++col) {
                if (top[col] <= bottom[col]) {
                    continue;
                }
                has_pixels = true;
                py = std::max(py, column_tops[px + col] - bottom[col]);
            }
            if (!has_pixels || py > max_y) {
                continue;
            }
            while (py <= max_y && !fits(mask, px, py)) {
                ++py;
            }
            if (py > max_y) {
                continue;
            }

            int candidate_height = max_height;
            int gap = 0;
            int contact = 0;
            for (int col = 0; col < mask.w; ++col) {
                if (top[col] <= bottom[col]) {
                    continue;
                }
                const int atlas_top = column_tops[px + col];
                const int bottom_y = py + bottom[col];
                const int top_y = py + top[col];
                candidate_height = std::max(candidate_height, top_y);
                gap += std::max(0, bottom_y - atlas_top);
                if (bottom_y == atlas_top) {
                    contact += std::max(1, top[col] - bottom[col]);
                }
            }
            if (py == 0) {
                contact += mask.w;
            }
            if (px == 0) {
                contact += mask.h;
            }
            if (px + mask.w == res) {
                contact += mask.h;
            }

            const bool better =
                candidate_height < best.height ||
                (candidate_height == best.height && gap < best.gap) ||
                (candidate_height == best.height && gap == best.gap && contact > best.contact) ||
                (candidate_height == best.height && gap == best.gap && contact == best.contact &&
                 (py < best.y || (py == best.y && px < best.x)));
            if (better) {
                best = {px, py, candidate_height, gap, contact};
            }
        }
        return best;
    }

    void place(const PixelMask& mask, const std::vector<int>& top, int px, int py) {
        for (int row = 0; row < mask.h; ++row) {
            const uint8_t* src = mask.data.data() + row * res;
            uint8_t* dst = data.data() + (py + row) * res + px;
            int col = 0;
            for (; col + 8 <= mask.w; col += 8) {
                uint64_t src_chunk = 0;
                uint64_t dst_chunk = 0;
                std::memcpy(&src_chunk, src + col, sizeof(uint64_t));
                std::memcpy(&dst_chunk, dst + col, sizeof(uint64_t));
                dst_chunk |= src_chunk;
                std::memcpy(dst + col, &dst_chunk, sizeof(uint64_t));
            }
            for (; col < mask.w; ++col) {
                dst[col] = static_cast<uint8_t>(dst[col] | src[col]);
            }
        }
        for (int col = 0; col < mask.w; ++col) {
            if (top[col] <= 0) {
                continue;
            }
            column_tops[px + col] = std::max(column_tops[px + col], py + top[col]);
            max_height = std::max(max_height, column_tops[px + col]);
        }
    }

    int height() const {
        return max_height;
    }
};

static PixelMask make_base_mask(const UVIsland& island, int res) {
    PixelMask mask;
    mask.data.assign(static_cast<size_t>(res) * res, 0);
    mask.w = mask_size_px(island.w, res);
    mask.h = mask_size_px(island.h, res);
    if (!island.mask_data || island.mask_stride <= 0) {
        return mask;
    }
    for (int row = 0; row < res; ++row) {
        for (int col = 0; col < res; ++col) {
            mask.data[row * res + col] = island.mask_data[row * island.mask_stride + col];
        }
    }
    return mask;
}

static PixelMask rotate_mask(const PixelMask& base, float angle, int res) {
    if (std::abs(angle) < 0.01f) {
        return base;
    }

    const float radians = angle * 3.14159265358979323846f / 180.0f;
    const float cos_a = std::cos(radians);
    const float sin_a = std::sin(radians);
    const float center_x = (base.w - 1) * 0.5f;
    const float center_y = (base.h - 1) * 0.5f;

    std::vector<std::pair<float, float>> rotated_pixels;
    rotated_pixels.reserve(static_cast<size_t>(base.w) * base.h);
    float min_x = INF;
    float min_y = INF;
    float max_x = -INF;
    float max_y = -INF;

    for (int row = 0; row < base.h; ++row) {
        for (int col = 0; col < base.w; ++col) {
            if (!base.data[row * res + col]) {
                continue;
            }
            const float dx = col - center_x;
            const float dy = row - center_y;
            const float rx = dx * cos_a - dy * sin_a;
            const float ry = dx * sin_a + dy * cos_a;
            rotated_pixels.push_back({rx, ry});
            min_x = std::min(min_x, rx);
            min_y = std::min(min_y, ry);
            max_x = std::max(max_x, rx);
            max_y = std::max(max_y, ry);
        }
    }

    PixelMask mask;
    mask.data.assign(static_cast<size_t>(res) * res, 0);
    mask.w = 0;
    mask.h = 0;
    if (rotated_pixels.empty()) {
        return mask;
    }

    for (const auto& pixel : rotated_pixels) {
        const int new_x = static_cast<int>(std::lround(pixel.first - min_x));
        const int new_y = static_cast<int>(std::lround(pixel.second - min_y));
        if (new_x < 0 || new_x >= res || new_y < 0 || new_y >= res) {
            continue;
        }
        mask.data[new_y * res + new_x] = 1;
        mask.w = std::max(mask.w, new_x + 1);
        mask.h = std::max(mask.h, new_y + 1);
    }

    return mask;
}

static PixelMask pad_mask(const PixelMask& base, int res, int margin_px) {
    if (margin_px <= 0) {
        return base;
    }
    PixelMask padded;
    padded.data.assign(static_cast<size_t>(res) * res, 0);
    padded.w = std::max(0, std::min(res, base.w + margin_px * 2));
    padded.h = std::max(0, std::min(res, base.h + margin_px * 2));
    for (int row = 0; row < base.h; ++row) {
        for (int col = 0; col < base.w; ++col) {
            if (!base.data[row * res + col]) {
                continue;
            }
            const int new_x = col + margin_px;
            const int new_y = row + margin_px;
            if (new_x >= 0 && new_x < res && new_y >= 0 && new_y < res) {
                padded.data[new_y * res + new_x] = 1;
            }
        }
    }
    return padded;
}


static void build_mask_profile(const PixelMask& mask,
                               int res,
                               std::vector<int>& bottom,
                               std::vector<int>& top) {
    const int safe_w = std::max(0, std::min(mask.w, res));
    const int safe_h = std::max(0, std::min(mask.h, res));
    bottom.assign(safe_w, 0);
    top.assign(safe_w, 0);
    for (int col = 0; col < safe_w; ++col) {
        int column_bottom = safe_h;
        int column_top = -1;
        for (int row = 0; row < safe_h; ++row) {
            if (!mask.data[row * res + col]) {
                continue;
            }
            column_bottom = std::min(column_bottom, row);
            column_top = std::max(column_top, row + 1);
        }
        if (column_top >= 0) {
            bottom[col] = column_bottom;
            top[col] = column_top;
        }
    }
}

static std::vector<float> get_angles(int step) {
    if (step <= 0) {
        return {0.0f};
    }
    std::vector<float> angles;
    for (int angle = 0; angle < 360; angle += step) {
        angles.push_back(static_cast<float>(angle));
    }
    return angles;
}

static const PixelVariant& pixel_variant_for(const PixelIsland& island, float angle) {
    for (const auto& variant : island.variants) {
        if (std::abs(variant.angle - angle) < 0.01f) {
            return variant;
        }
    }
    return island.variants.front();
}

static float attempt_rect(const std::vector<IslandInfo>& data,
                          const std::vector<int>& order,
                          const std::vector<float>& rots,
                          const UVPackConfig& cfg,
                          std::vector<Place>& out) {
    out.assign(data.size(), {0.0f, 0.0f, 0.0f});
    Skyline skyline;
    MaxRects max_rects;
    for (int index : order) {
        float rw = 0.0f;
        float rh = 0.0f;
        rotdims(data[index].w, data[index].h, rots[index], rw, rh);
        const float pw = rw + cfg.margin * 2.0f;
        const float ph = rh + cfg.margin * 2.0f;
        float px = 0.0f;
        float py = 0.0f;
        bool ok = false;
        if (cfg.method == UV_SKYLINE) {
            ok = skyline.insert(pw, ph, px, py);
        } else {
            ok = max_rects.insert(pw, ph, cfg.heuristic, px, py);
        }
        if (!ok) {
            return -1.0f;
        }
        out[index] = {px + cfg.margin, py + cfg.margin, rots[index]};
    }

    const float height = (cfg.method == UV_SKYLINE) ? skyline.height() : max_rects.height();
    if (height < 1e-9f) {
        return 0.0f;
    }
    float total_area = 0.0f;
    for (const auto& island : data) {
        total_area += island.area;
    }
    return total_area / height;
}

static float attempt_pixel(const std::vector<IslandInfo>& data,
                           const std::vector<PixelIsland>& pixel_islands,
                           const std::vector<int>& order,
                           const std::vector<float>& rots,
                           const UVPackConfig& cfg,
                           std::vector<Place>& out) {
    const int res = std::max(1, cfg.resolution);
    const int margin_px = std::max(0, static_cast<int>(std::ceil(cfg.margin * res)));
    PixelAtlas atlas(res);
    out.assign(data.size(), {0.0f, 0.0f, 0.0f});

    float total_area = 0.0f;
    for (const auto& island : data) {
        total_area += island.area;
    }

    int used_height_px = 0;
    for (int index : order) {
        const auto& variant = pixel_variant_for(pixel_islands[index], rots[index]);
        const PixelMask& mask = (margin_px > 0) ? variant.padded_mask : variant.mask;
        const auto pos = atlas.find_position(mask);
        if (pos.first < 0 || pos.second < 0) {
            return -1.0f;
        }
        atlas.place(mask, pos.first, pos.second);
        out[index] = {
            (pos.first + margin_px) / static_cast<float>(res),
            (pos.second + margin_px) / static_cast<float>(res),
            rots[index],
        };
        used_height_px = std::max(used_height_px, pos.second + mask.h);
    }

    if (used_height_px <= 0) {
        return 0.0f;
    }
    const float used_height = used_height_px / static_cast<float>(res);
    return (used_height > 1e-12f) ? (total_area / used_height) : 0.0f;
}

static float attempt_horizon(const std::vector<IslandInfo>& data,
                             const std::vector<PixelIsland>& pixel_islands,
                             const std::vector<int>& order,
                             const std::vector<float>& rots,
                             const UVPackConfig& cfg,
                             std::vector<Place>& out) {
    const int res = std::max(1, cfg.resolution);
    const int margin_px = std::max(0, static_cast<int>(std::ceil(cfg.margin * res)));
    HorizonAtlas atlas(res);
    out.assign(data.size(), {0.0f, 0.0f, 0.0f});

    float total_area = 0.0f;
    for (const auto& island : data) {
        total_area += island.area;
    }

    for (int index : order) {
        const auto& variant = pixel_variant_for(pixel_islands[index], rots[index]);
        const PixelMask& mask = (margin_px > 0) ? variant.padded_mask : variant.mask;
        const std::vector<int>& bottom = (margin_px > 0) ? variant.padded_bottom : variant.bottom;
        const std::vector<int>& top = (margin_px > 0) ? variant.padded_top : variant.top;
        const HorizonCandidate candidate = atlas.find_position(mask, bottom, top);
        if (candidate.x < 0 || candidate.y < 0) {
            return -1.0f;
        }
        atlas.place(mask, top, candidate.x, candidate.y);
        out[index] = {
            (candidate.x + margin_px) / static_cast<float>(res),
            (candidate.y + margin_px) / static_cast<float>(res),
            rots[index],
        };
    }

    if (atlas.height() <= 0) {
        return 0.0f;
    }
    const float used_height = atlas.height() / static_cast<float>(res);
    return (used_height > 1e-12f) ? (total_area / used_height) : 0.0f;
}

template <typename AttemptFn>
static float iter_opt(const std::vector<IslandInfo>& data,
                      const UVPackConfig& cfg,
                      float min_occ,
                      const std::vector<float>& angles,
                      AttemptFn attempt,
                      std::vector<Place>& best_pl) {
    const int n = static_cast<int>(data.size());
    float best_occ = min_occ;
    int iters = 0;
    const auto t0 = std::chrono::steady_clock::now();
    auto elapsed = [&]() {
        return std::chrono::duration<float>(std::chrono::steady_clock::now() - t0).count();
    };
    const bool stop_on_target = min_occ >= 0.0f;
    auto done = [&]() {
        const float time_limit = (cfg.time_limit > 0.01f) ? cfg.time_limit : 999999.0f;
        return iters >= cfg.max_iter || elapsed() >= time_limit || (stop_on_target && best_occ >= 0.98f);
    };

    auto update_best = [&](float occ, const std::vector<Place>& placements) {
        if (occ > best_occ + 1e-6f) {
            best_occ = occ;
            best_pl = placements;
        }
    };

    std::vector<std::function<bool(int, int)>> sorts = {
        [&](int a, int b) { return data[a].area > data[b].area; },
        [&](int a, int b) { return std::max(data[a].w, data[a].h) > std::max(data[b].w, data[b].h); },
        [&](int a, int b) { return data[a].h > data[b].h; },
        [&](int a, int b) { return data[a].w > data[b].w; },
        [&](int a, int b) { return (data[a].w + data[a].h) > (data[b].w + data[b].h); },
        [&](int a, int b) { return (data[a].w * data[a].h) > (data[b].w * data[b].h); },
        [&](int a, int b) {
            return std::max(data[a].w, data[a].h) / (std::min(data[a].w, data[a].h) + 1e-9f) >
                   std::max(data[b].w, data[b].h) / (std::min(data[b].w, data[b].h) + 1e-9f);
        },
    };

    auto try_attempt = [&](const std::vector<int>& order, const std::vector<float>& rots) {
        std::vector<Place> placements;
        const float occ = attempt(order, rots, placements);
        ++iters;
        if (occ >= 0.0f) {
            update_best(occ, placements);
        }
    };

    for (const auto& sort_fn : sorts) {
        if (done()) {
            break;
        }

        std::vector<int> order(n);
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(), sort_fn);
        try_attempt(order, std::vector<float>(n, 0.0f));
        if (done()) {
            break;
        }

        if (angles.size() > 1) {
            std::vector<std::vector<Place>> parallel_places(angles.size());
            std::vector<float> parallel_occ(angles.size(), -1.0f);
#pragma omp parallel for if (angles.size() > 1)
            for (int angle_index = 0; angle_index < static_cast<int>(angles.size()); ++angle_index) {
                if (std::abs(angles[angle_index]) < 0.01f) {
                    continue;
                }
                std::vector<float> rots(n, angles[angle_index]);
                parallel_occ[angle_index] = attempt(order, rots, parallel_places[angle_index]);
            }
            for (int angle_index = 0; angle_index < static_cast<int>(angles.size()); ++angle_index) {
                if (std::abs(angles[angle_index]) < 0.01f) {
                    continue;
                }
                ++iters;
                if (parallel_occ[angle_index] >= 0.0f) {
                    update_best(parallel_occ[angle_index], parallel_places[angle_index]);
                }
                if (done()) {
                    break;
                }
            }

            if (done()) {
                break;
            }

            std::vector<float> smart_rots(n, 0.0f);
            for (int island_index = 0; island_index < n; ++island_index) {
                float best_angle = 0.0f;
                float best_metric = INF;
                for (float angle : angles) {
                    float rw = 0.0f;
                    float rh = 0.0f;
                    rotdims(data[island_index].w, data[island_index].h, angle, rw, rh);
                    const float metric = std::max(rw, rh);
                    if (metric < best_metric - 1e-9f) {
                        best_metric = metric;
                        best_angle = angle;
                    }
                }
                smart_rots[island_index] = best_angle;
            }
            try_attempt(order, smart_rots);
            if (done()) {
                break;
            }

            std::vector<float> portrait_rots(n, 0.0f);
            for (int island_index = 0; island_index < n; ++island_index) {
                portrait_rots[island_index] = (data[island_index].h > data[island_index].w) ? 0.0f : 90.0f;
            }
            try_attempt(order, portrait_rots);
        }
    }

    std::mt19937 base_rng(static_cast<unsigned>(
        std::chrono::high_resolution_clock::now().time_since_epoch().count()
    ));
    while (!done()) {
        const int remaining = cfg.max_iter - iters;
        const int batch = std::max(1, std::min(remaining, 16));
        std::vector<std::vector<Place>> batch_places(batch);
        std::vector<float> batch_occ(batch, -1.0f);

#pragma omp parallel for if (batch > 1)
        for (int batch_index = 0; batch_index < batch; ++batch_index) {
            std::mt19937 rng(base_rng());
            rng.seed(12345u + static_cast<unsigned>(iters + batch_index) * 7919u);
            std::uniform_real_distribution<float> choose(0.0f, 1.0f);
            std::vector<int> order(n);
            std::iota(order.begin(), order.end(), 0);
            if (choose(rng) < 0.7f) {
                std::uniform_real_distribution<float> jitter(0.8f, 1.2f);
                std::vector<float> weighted_area(n, 0.0f);
                for (int island_index = 0; island_index < n; ++island_index) {
                    weighted_area[island_index] = data[island_index].area * jitter(rng);
                }
                std::sort(order.begin(), order.end(), [&](int a, int b) {
                    return weighted_area[a] > weighted_area[b];
                });
            } else {
                std::shuffle(order.begin(), order.end(), rng);
            }

            std::uniform_int_distribution<int> angle_index(0, static_cast<int>(angles.size()) - 1);
            std::vector<float> rots(n, 0.0f);
            for (auto& rot : rots) {
                rot = angles[angle_index(rng)];
            }
            batch_occ[batch_index] = attempt(order, rots, batch_places[batch_index]);
        }

        for (int batch_index = 0; batch_index < batch; ++batch_index) {
            ++iters;
            if (batch_occ[batch_index] >= 0.0f) {
                update_best(batch_occ[batch_index], batch_places[batch_index]);
            }
            if (done()) {
                break;
            }
        }
    }

    return best_occ;
}

template <typename AttemptFn>
static float sa_opt(const std::vector<IslandInfo>& data,
                    const UVPackConfig& cfg,
                    float min_occ,
                    const std::vector<float>& angles,
                    AttemptFn attempt,
                    std::vector<Place>& best_pl) {
    const int n = static_cast<int>(data.size());
    const float time_limit = (cfg.time_limit > 0.01f) ? cfg.time_limit : 999999.0f;
    const auto t0 = std::chrono::steady_clock::now();
    auto elapsed = [&]() {
        return std::chrono::duration<float>(std::chrono::steady_clock::now() - t0).count();
    };

    const bool stop_on_target = min_occ >= 0.0f;
    std::mt19937 rng(static_cast<unsigned>(
        std::chrono::high_resolution_clock::now().time_since_epoch().count()
    ));
    std::uniform_real_distribution<float> choose(0.0f, 1.0f);
    std::uniform_int_distribution<int> index_pick(0, n - 1);
    std::uniform_int_distribution<int> angle_pick(0, static_cast<int>(angles.size()) - 1);

    std::vector<int> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](int a, int b) { return data[a].area > data[b].area; });
    std::vector<float> rotations(n, 0.0f);

    std::vector<Place> placements;
    float current = attempt(order, rotations, placements);
    float best_occ = min_occ;
    if (current > best_occ + 1e-6f) {
        best_occ = current;
        best_pl = placements;
    } else if (current < 0.0f) {
        current = min_occ;
    }

    float temperature = cfg.sa_initial_temp;
    int iterations = 0;
    while (iterations < cfg.max_iter && elapsed() < time_limit && (!stop_on_target || best_occ < 0.98f)) {
        auto next_order = order;
        auto next_rotations = rotations;
        const float action = choose(rng);
        if (n < 2 || action < 0.25f) {
            next_rotations[index_pick(rng)] = angles[angle_pick(rng)];
        } else if (action < 0.50f) {
            const int a = index_pick(rng);
            const int b = index_pick(rng);
            std::swap(next_order[a], next_order[b]);
        } else if (action < 0.75f) {
            const int from = index_pick(rng);
            const int to = index_pick(rng);
            const int value = next_order[from];
            next_order.erase(next_order.begin() + from);
            next_order.insert(next_order.begin() + to, value);
        } else {
            int a = index_pick(rng);
            int b = index_pick(rng);
            if (a > b) {
                std::swap(a, b);
            }
            std::reverse(next_order.begin() + a, next_order.begin() + b + 1);
        }

        float next = attempt(next_order, next_rotations, placements);
        if (next < 0.0f) {
            temperature *= cfg.sa_cooling_rate;
            ++iterations;
            continue;
        }

        const float delta = next - current;
        bool accept = delta > 0.0f;
        if (!accept && temperature > 1e-12f) {
            const float probability = std::exp(delta / temperature);
            accept = choose(rng) < probability;
        }
        if (accept) {
            order = std::move(next_order);
            rotations = std::move(next_rotations);
            current = next;
        }
        if (current > best_occ + 1e-6f) {
            best_occ = current;
            best_pl = placements;
        }
        temperature *= cfg.sa_cooling_rate;
        ++iterations;
    }

    return best_occ;
}

UVPACK_API float uvpack_run(const UVIsland* islands, int n_islands,
                            const UVPackConfig* cfg, UVPlacement* out) {
    if (!islands || n_islands <= 0 || !cfg || !out) {
        return 0.0f;
    }

    std::vector<IslandInfo> data(n_islands);
    for (int index = 0; index < n_islands; ++index) {
        data[index] = {islands[index].w, islands[index].h, islands[index].area};
    }

    const auto angles = get_angles(cfg->rotation_step);
    std::vector<PixelIsland> pixel_islands;
    if (cfg->method == UV_PIXEL || cfg->method == UV_HORIZON) {
        pixel_islands.resize(n_islands);
        const int res = std::max(1, cfg->resolution);
        const int margin_px = std::max(0, static_cast<int>(std::ceil(cfg->margin * res)));
        for (int index = 0; index < n_islands; ++index) {
            const PixelMask base_mask = make_base_mask(islands[index], res);
            auto& variants = pixel_islands[index].variants;
            variants.reserve(angles.size());
            for (float angle : angles) {
                PixelVariant variant;
                variant.angle = angle;
                variant.mask = rotate_mask(base_mask, angle, res);
                variant.padded_mask = pad_mask(variant.mask, res, margin_px);
                build_mask_profile(variant.mask, res, variant.bottom, variant.top);
                build_mask_profile(variant.padded_mask, res, variant.padded_bottom, variant.padded_top);
                variants.push_back(std::move(variant));
            }
        }
    }

    auto attempt = [&](const std::vector<int>& order,
                       const std::vector<float>& rots,
                       std::vector<Place>& placements) -> float {
        if (cfg->method == UV_PIXEL) {
            return attempt_pixel(data, pixel_islands, order, rots, *cfg, placements);
        }
        if (cfg->method == UV_HORIZON) {
            return attempt_horizon(data, pixel_islands, order, rots, *cfg, placements);
        }
        return attempt_rect(data, order, rots, *cfg, placements);
    };

    std::vector<Place> best_placements(n_islands, {0.0f, 0.0f, 0.0f});
    float best_occ = cfg->min_occupancy;

    if (cfg->optimizer == UV_OPT_NONE) {
        std::vector<int> order(n_islands);
        std::iota(order.begin(), order.end(), 0);
        std::sort(order.begin(), order.end(), [&](int a, int b) { return data[a].area > data[b].area; });
        std::vector<float> rotations(n_islands, 0.0f);
        const float occ = attempt(order, rotations, best_placements);
        best_occ = (occ < 0.0f) ? cfg->min_occupancy : occ;
    } else if (cfg->optimizer == UV_OPT_ITERATIVE) {
        best_occ = iter_opt(data, *cfg, cfg->min_occupancy, angles, attempt, best_placements);
    } else {
        best_occ = sa_opt(data, *cfg, cfg->min_occupancy, angles, attempt, best_placements);
    }

    for (int index = 0; index < n_islands; ++index) {
        out[index] = {islands[index].id, best_placements[index].x, best_placements[index].y, best_placements[index].angle};
    }
    return best_occ;
}

UVPACK_API const char* uvpack_version(void) {
    return "uvpack 1.2.1";
}

#include <cstdint>
#include <cmath>
#include <algorithm>
#ifdef _OPENMP
#include <omp.h>
#endif

extern "C" void first_hit_many(
    const double* high,
    const double* low,
    std::int64_t n_bars,
    const std::int64_t* entry_idx,
    const double* stop,
    const double* target,
    const std::int8_t* side,
    std::int64_t n_events,
    std::int64_t max_scan,
    std::int64_t* exit_idx,
    std::int8_t* outcome
) {
    #pragma omp parallel for schedule(dynamic, 512)
    for (std::int64_t i = 0; i < n_events; ++i) {
        const std::int64_t start = entry_idx[i];
        if (start < 0 || start >= n_bars || !std::isfinite(stop[i]) || !std::isfinite(target[i])) {
            exit_idx[i] = -1;
            outcome[i] = 0;
            continue;
        }
        std::int64_t end = n_bars;
        if (max_scan > 0 && start + max_scan < end) end = start + max_scan;
        std::int64_t found = -1;
        std::int8_t hit = 0;
        if (side[i] > 0) {
            for (std::int64_t j = start; j < end; ++j) {
                const double h = high[j], l = low[j];
                if (!std::isfinite(h) || !std::isfinite(l)) continue;
                const bool hs = l <= stop[i];
                const bool ht = h >= target[i];
                if (hs || ht) {
                    found = j;
                    hit = hs ? -1 : 1; // adverse stop-first ambiguity
                    break;
                }
            }
        } else {
            for (std::int64_t j = start; j < end; ++j) {
                const double h = high[j], l = low[j];
                if (!std::isfinite(h) || !std::isfinite(l)) continue;
                const bool hs = h >= stop[i];
                const bool ht = l <= target[i];
                if (hs || ht) {
                    found = j;
                    hit = hs ? -1 : 1;
                    break;
                }
            }
        }
        exit_idx[i] = found;
        outcome[i] = hit;
    }
}

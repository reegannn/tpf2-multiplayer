// stopconfig_format.h -- a line stop's maxLoad vector (Line.StopConfig) as the wire's
// "/"-joined numbers. Shared by the Windows slice (slice/lines.inl) and the Linux one
// (linux/src/slice/slice_lines.cpp), so both write the same text.
//
// The element type is not proven. The API calls maxLoad "for each cargo type, its max
// allowed fraction of total capacity (from 0 to 1)", but lists every StopConfig field
// as {int,...}, and the two flag fields beside it are bit vectors. So it is recognised
// from the bytes, in this order, and anything else is refused:
//   1. floats:   every 4-byte word is 0 or a float in [1e-30, 1]. A real fraction is
//                never a smaller bit pattern than 1e-30's (0x0DA24260);
//   2. integers: every 4-byte word is an int in 0..100000, which as a float is a
//                denormal below 1.5e-40 -- no fraction anyone sets;
//   3. doubles:  8 bytes per cargo type (nTypes, from the load bits), each in [0, 1].
// Case 1 writes exactly what the first version of the decoder wrote (%.9g of the float).
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

inline bool StopConfigFormatMaxLoad(const uint8_t* data, size_t bytes, size_t nTypes,
                                    std::string* out, char* why, size_t whyLen)
{
    out->clear();
    if (bytes == 0) return true;
    char num[48];
    if (bytes % 4 == 0) {
        const size_t n = bytes / 4;
        bool asFloat = true, asInt = true;
        uint32_t firstBad = 0;
        for (size_t k = 0; k < n; k++) {
            uint32_t w;
            memcpy(&w, data + k * 4, 4);
            float f;
            memcpy(&f, &w, 4);
            const int32_t i = (int32_t)w;
            const bool okF = (w == 0) || (f >= 1e-30f && f <= 1.f);
            const bool okI = (i >= 0 && i <= 100000);
            if (!okF && !okI && firstBad == 0) firstBad = w;   // 0 is never bad
            if (!okF) asFloat = false;
            if (!okI) asInt = false;
        }
        if (asFloat || asInt) {
            for (size_t k = 0; k < n; k++) {
                if (asFloat) {
                    float f;
                    memcpy(&f, data + k * 4, 4);
                    snprintf(num, sizeof(num), "%s%.9g", k ? "/" : "", f);
                } else {
                    int32_t i;
                    memcpy(&i, data + k * 4, 4);
                    snprintf(num, sizeof(num), "%s%d", k ? "/" : "", (int)i);
                }
                out->append(num);
            }
            return true;
        }
        if (!(nTypes && bytes == nTypes * 8)) {
            snprintf(why, whyLen, "maxLoad: %zu bytes that are neither fractions nor small integers (word %08x)",
                     bytes, (unsigned)firstBad);
            return false;
        }
    }
    if (nTypes && bytes == nTypes * 8) {
        for (size_t k = 0; k < nTypes; k++) {
            double v;
            memcpy(&v, data + k * 8, 8);
            if (!(v >= 0.0 && v <= 1.0) || (v != 0.0 && v < 1e-30)) {
                out->clear();
                snprintf(why, whyLen, "maxLoad[%zu] = %g as a double: not a fraction", k + 1, v);
                return false;
            }
            snprintf(num, sizeof(num), "%s%.9g", k ? "/" : "", v);
            out->append(num);
        }
        return true;
    }
    snprintf(why, whyLen, "maxLoad spans %zu bytes for %zu cargo types", bytes, nTypes);
    return false;
}

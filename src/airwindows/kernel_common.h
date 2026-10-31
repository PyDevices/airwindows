// What every generated plug-in kernel under plugins/ shares: the
// descriptor a binding reads, the int16 in and out, the seeds, and the
// arithmetic the fast variant uses in place of libm and the divide.
//
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett

#pragma once

// Multiply-adds stay two roundings, as they are on every interpreter and
// target this runs on, so a render is the same bytes everywhere. Upstream's
// integer noise sources overflow int on purpose; wrapping is what it means.
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC optimize("fp-contract=off")
#pragma GCC optimize("wrapv")
// A few plug-ins read a float's bits through a pointer cast, as upstream does.
#pragma GCC optimize("no-strict-aliasing")
#elif defined(__clang__)
#pragma clang fp contract(off)
#endif

// Upstream's code is kept as it reads, layout and all, so warnings a
// firmware build turns into errors are about upstream's style, not the
// translation. The reference tests are what hold the code to account.
#if defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wmisleading-indentation"
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wunused-but-set-variable"
#pragma GCC diagnostic ignored "-Wunused-function"
#pragma GCC diagnostic ignored "-Wunused-value"
#pragma GCC diagnostic ignored "-Wunused-label"
#pragma GCC diagnostic ignored "-Wparentheses"
#pragma GCC diagnostic ignored "-Wdangling-else"
#pragma GCC diagnostic ignored "-Wsign-compare"
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#pragma GCC diagnostic ignored "-Wuninitialized"
#pragma GCC diagnostic ignored "-Wfloat-conversion"
#pragma GCC diagnostic ignored "-Wtype-limits"
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#pragma GCC diagnostic ignored "-Wempty-body"
#pragma GCC diagnostic ignored "-Wsequence-point"
#pragma GCC diagnostic ignored "-Wstrict-aliasing"
#pragma GCC diagnostic ignored "-Wabsolute-value"
#if !defined(__clang__)
#pragma GCC diagnostic ignored "-Wmaybe-uninitialized"
#endif
// tools/awgen counts the double arithmetic left in each fast loop with
// this warning, so it stays on there.
#ifndef AW_COUNT_DOUBLES
#pragma GCC diagnostic ignored "-Wdouble-promotion"
#endif
#endif

#include <math.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "airwindows/plugin.h"

// Which variants a build compiles. The reference is upstream's arithmetic
// (double where upstream has double); the fast variant is single precision
// with no divide or libm call in the loop where it can be helped, for parts
// whose FPU has neither (every ESP32). A desktop build has both, so a test
// can hold one against the other; a board build has one.
#ifndef AW_BUILD_REF
#define AW_BUILD_REF 1
#endif
#ifndef AW_BUILD_FAST
#define AW_BUILD_FAST 1
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#ifndef M_PI_2
#define M_PI_2 1.57079632679489661923
#endif
#ifndef M_PI_4
#define M_PI_4 0.78539816339744830962
#endif
#ifndef M_E
#define M_E 2.7182818284590452354
#endif
#ifndef M_SQRT2
#define M_SQRT2 1.41421356237309504880
#endif
#ifndef M_SQRT1_2
#define M_SQRT1_2 0.70710678118654752440
#endif
#ifndef M_LN2
#define M_LN2 0.69314718055994530942
#endif
#ifndef M_LN10
#define M_LN10 2.30258509299404568402
#endif

typedef int32_t VstInt32;

// --- seeds and noise -----------------------------------------------------------

// Upstream seeds each xorshift generator from rand(), anything at or above
// 16386. These are fixed so a node renders the same take twice; the
// reference harness gives upstream the same ones.
#define AW_SEED_LEFT 2463534242u
#define AW_SEED_RIGHT 1588635695u

static inline uint32_t aw_seed(int index) {
    if (index == 0) {
        return AW_SEED_LEFT;
    }
    uint32_t x = AW_SEED_RIGHT;
    while (--index > 0) {
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
    }
    return x;
}

// rand() for the few plug-ins that call it as they run: a fixed generator,
// per node, which the harness also gives upstream.
#define AW_RAND_SEED 12345u
#define AW_RAND_MAX 2147483647

static inline int aw_rand_next(uint32_t *state) {
    *state = *state * 1103515245u + 12345u;
    return (int)(*state >> 1);
}

// --- int16 in and out -----------------------------------------------------------

#define AW_IN_L(p) ((float)(p)[0] * (1.0f / 32768.0f))
#define AW_IN_R(p, ch) ((float)(p)[(ch) - 1] * (1.0f / 32768.0f))

static inline int16_t aw_to_s16(float sample) {
    float scaled = floorf(sample * 32768.0f + 0.5f);
    if (scaled > 32767.0f) {
        return 32767;
    }
    if (scaled < -32768.0f) {
        return -32768;
    }
    return (int16_t)scaled;
}

// aw_to_s16 with no floorf call: the same result for every input but NaN.
static inline int16_t aw_to_s16_fast(float sample) {
    const float scaled = sample * 32768.0f + 0.5f;
    if (scaled >= 32767.0f) {
        return 32767;
    }
    if (scaled < -32768.0f) {
        return -32768;
    }
    int32_t whole = (int32_t)scaled;
    if ((float)whole > scaled) {
        whole -= 1;
    }
    return (int16_t)whole;
}

// A mono node runs the stereo loop with its one channel on both sides and
// keeps the average.
#define AW_OUT_REF(p, ch, l, r) do { \
        if ((ch) == 2) { \
            (p)[0] = aw_to_s16(l); \
            (p)[1] = aw_to_s16(r); \
        } else { \
            (p)[0] = aw_to_s16(((l) + (r)) * 0.5f); \
        } \
} while (0)

#define AW_OUT_FAST(p, ch, l, r) do { \
        if ((ch) == 2) { \
            (p)[0] = aw_to_s16_fast(l); \
            (p)[1] = aw_to_s16_fast(r); \
        } else { \
            (p)[0] = aw_to_s16_fast(((l) + (r)) * 0.5f); \
        } \
} while (0)

// --- arithmetic --------------------------------------------------------------------

// abs() on a double is fabs() in upstream's C++.
#define aw_abs(x) _Generic((x), \
    float: fabsf, \
    double: fabs, \
    long double: fabsl, \
    default: abs)(x)

#define AW_PI_F 3.14159265358979323846f
#define AW_TWO_PI_F 6.28318530717958647692f
#define AW_HALF_PI_F 1.57079632679489661923f

// floor() with no call, for |x| < 2^31; beyond that a float is whole.
static inline float aw_floorf(float x) {
    if (!(fabsf(x) < 2147483648.0f)) {
        return x;
    }
    float whole = (float)(int32_t)x;
    return whole > x ? whole - 1.0f : whole;
}

static inline float aw_ceilf(float x) {
    return -aw_floorf(-x);
}

// sin(x) for |x| <= pi/2: the odd Taylor series to x^9, Horner order. Worst
// error 1.6e-7 at the ends. A polynomial in a fixed order is the same
// function on every target, where sinf() is several that nearly agree.
static inline float aw_sin_quarter(float x) {
    const float x2 = x * x;
    return x * (1.0f + x2 * (-1.0f / 6.0f + x2 * (1.0f / 120.0f
        + x2 * (-1.0f / 5040.0f + x2 * (1.0f / 362880.0f)))));
}

static inline float aw_sinf(float x) {
    if (x > AW_PI_F || x < -AW_PI_F) {
        x -= AW_TWO_PI_F * aw_floorf(x * (1.0f / AW_TWO_PI_F) + 0.5f);
        // Far from zero a float's step outgrows pi and that reduction leaves
        // a remainder of any size; fmodf's is exact. Upstream lets a few
        // phases grow without bound, and a sine must stay a sine.
        if (x > AW_PI_F || x < -AW_PI_F) {
            x = fmodf(x, AW_TWO_PI_F);
            if (x > AW_PI_F) {
                x -= AW_TWO_PI_F;
            } else if (x < -AW_PI_F) {
                x += AW_TWO_PI_F;
            }
        }
    }
    if (x > AW_HALF_PI_F) {
        x = AW_PI_F - x;
    } else if (x < -AW_HALF_PI_F) {
        x = -AW_PI_F - x;
    }
    return aw_sin_quarter(x);
}

static inline float aw_cosf(float x) {
    return aw_sinf(x + AW_HALF_PI_F);
}

static inline float aw_pow2i(float x) {
    return x * x;
}

static inline float aw_pow3i(float x) {
    return x * x * x;
}

static inline float aw_pow4i(float x) {
    const float x2 = x * x;
    return x2 * x2;
}

// A phase the fast variant keeps in Q4.60 fixed point (policy.json, "phase"):
// one that only grows by a step and wraps to zero below 8, as a vibrato's
// does. Adding a step to it is two integer adds where a double is a libgcc
// call. A step of 7 or more wraps the phase at once, so it is held at 7,
// which keeps the phase under 16.
#define AW_Q60_ONE 1152921504606846976.0
#define AW_Q60(x) ((uint64_t)((x) * AW_Q60_ONE))
#define AW_Q60_STEP(x) ((x) < 7.0 ? AW_Q60(x) : AW_Q60(7.0))

// The phase as a float: its top 32 bits are Q4.28, more than a float holds.
static inline float aw_q60f(uint64_t q) {
    return (float)(uint32_t)(q >> 32) * (1.0f / 268435456.0f);
}

// 1 / d in multiplies and adds: an estimate from the exponent bits, then
// three Newton steps, within two float ulps. The ESP32's FPU has no divide,
// so `/` is a libgcc call that costs several times this. Zero, denormals
// and the very large take the divide, which gives their infinities and
// zeros exactly.
static inline float aw_recipf(float d) {
    union {
        float f;
        uint32_t u;
    } g = {d};
    const uint32_t sign = g.u & 0x80000000u;
    g.u &= 0x7fffffffu;
    if (g.u - 0x00800000u >= 0x7e000000u) {
        return 1.0f / d;
    }
    const float a = g.f;
    g.u = 0x7ef311c7u - g.u;
    float x = g.f;
    x = x * (2.0f - a * x);
    x = x * (2.0f - a * x);
    x = x * (2.0f - a * x);
    g.f = x;
    g.u |= sign;
    return g.f;
}

// The descriptor each generated plug-in kernel exports, which the bindings
// and the reference harness read. C and C++ both include it.
//
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett

#pragma once

#include <stdint.h>

// Whether the fast path runs the kernels written by hand for the ESP32-S3
// where a plug-in has one (policy.json, "tuned"): on Xtensa, where each was
// measured cheaper than the translated loop. Elsewhere, the P4 among them,
// the translated loop runs. A desktop build may set it to test what the S3
// runs.
#ifndef AW_TUNED
#if defined(__XTENSA__)
#define AW_TUNED 1
#else
#define AW_TUNED 0
#endif
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *py;      // the Python keyword
    const char *name;    // upstream's display name
    float def;           // upstream's default, 0..1
} aw_param_t;

typedef struct {
    uint32_t size;
    void (*init)(void *state, double sample_rate);
    void (*process)(void *state, int16_t *out, const int16_t *in,
        int32_t frames, uint32_t channels);
    // Where each parameter's float lives in the state.
    const uint32_t *offsets;
} aw_variant_t;

typedef struct {
    const char *name;
    uint32_t param_count;
    const aw_param_t *params;
    aw_variant_t ref;
    aw_variant_t fast;
} aw_plugin_t;

#ifdef __cplusplus
}
#endif

// audioairwindows' node types -- MicroPython bindings over the generated
// kernels in airwindows/plugins/.
//
// One object layout and one set of methods for every plug-in; the type a node
// was built as picks the kernel (types.c, generated, pairs each type with
// its descriptor) and the names of its parameters.
//
// SPDX-License-Identifier: MIT

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "audiocore/__init__.h"
#include "py/obj.h"
#include "airwindows/plugin.h"

// Frames per block a node hands its player.
#define AW_FRAMES 256u

// The variant a node runs. AW_FAST_DEFAULT=1 picks the fast one, as every
// ESP32 build does (micropython.cmake); a build that compiled only one
// variant runs that one.
#ifndef AW_FAST_DEFAULT
#define AW_FAST_DEFAULT 0
#endif

typedef struct {
    audiosample_base_t base;
    mp_obj_t source;
    const aw_plugin_t *plugin;
    const aw_variant_t *variant;
    // The kernel's state, variant->size bytes: its lines, filters and knobs.
    uint8_t *state;
    int16_t buffer[AW_FRAMES * 2];
    // Source frames fetched but not yet consumed, carried across blocks.
    const int16_t *pending;
    uint32_t pending_frames;
    // The source handed its last buffer with GET_BUFFER_DONE; it is let go
    // of once that buffer is used up.
    bool source_done;
} audioairwindows_obj_t;

typedef struct {
    const mp_obj_type_t *type;
    const aw_plugin_t *plugin;
} audioairwindows_entry_t;

// From types.c.
extern const audioairwindows_entry_t audioairwindows_entries[];
extern const size_t audioairwindows_entry_count;

// For types.c's type definitions.
mp_obj_t audioairwindows_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args);
extern const mp_obj_dict_t audioairwindows_locals;
extern const audiosample_p_t audioairwindows_proto;

// audioairwindows' node: one implementation behind every plug-in's type.
// See Airwindows.h.
// SPDX-License-Identifier: MIT

#include "audioairwindows/Airwindows.h"

#include <string.h>

// From audiodsp, which this module builds beside: the context-manager
// helpers, its audiocore sample protocol (through Airwindows.h) and the pump
// lock that keeps a live change out of a block being rendered.
#include "cp_compat/context_manager_helpers.h"
#include "cp_compat/objproperty.h"
#include "py/runtime.h"
#include "shared/audiodsp_pump_lock.h"

// No plug-in has more knobs than this; tools/awgen checks.
#define AW_MAX_PARAMS 64

// The block a node renders when its source has ended or run short.
static const int16_t airwindows_silence[AW_FRAMES * 2];

static const aw_plugin_t *airwindows_plugin(const mp_obj_type_t *type) {
    for (size_t i = 0; i < audioairwindows_entry_count; ++i) {
        if (audioairwindows_entries[i].type == type) {
            return audioairwindows_entries[i].plugin;
        }
    }
    mp_raise_TypeError(MP_ERROR_TEXT("not an Airwindows type"));
}

static const aw_variant_t *airwindows_variant(const aw_plugin_t *plugin) {
    #if AW_FAST_DEFAULT
    return plugin->fast.process ? &plugin->fast : &plugin->ref;
    #else
    return plugin->ref.process ? &plugin->ref : &plugin->fast;
    #endif
}

static float *airwindows_knob(audioairwindows_obj_t *self, uint32_t index) {
    return (float *)(self->state + self->variant->offsets[index]);
}

// Every keyword is checked and staged before the running state changes, so a
// bad keyword after a good one changes nothing and a pull between two
// keywords never plays half a change. Knobs are 0..1, as upstream's are;
// values outside are clamped.
static void airwindows_apply_kwargs(audioairwindows_obj_t *self,
    const mp_map_t *kw, bool live) {
    const aw_plugin_t *plugin = self->plugin;
    float values[AW_MAX_PARAMS];
    bool given[AW_MAX_PARAMS] = {false};
    for (size_t i = 0; i < kw->alloc; ++i) {
        if (!mp_map_slot_is_filled(kw, i)) {
            continue;
        }
        qstr name = mp_obj_str_get_qstr(kw->table[i].key);
        if (name == MP_QSTR_sample_rate || name == MP_QSTR_channel_count) {
            if (live) {
                mp_raise_msg_varg(&mp_type_TypeError,
                    MP_ERROR_TEXT("'%q' is fixed at construction"), name);
            }
            continue;
        }
        const char *text = qstr_str(name);
        uint32_t index = 0;
        while (index < plugin->param_count &&
               strcmp(plugin->params[index].py, text) != 0) {
            ++index;
        }
        if (index == plugin->param_count) {
            mp_raise_msg_varg(&mp_type_TypeError,
                MP_ERROR_TEXT("unknown %q option '%q'"),
                (qstr)self->base.self.type->name, name);
        }
        float value = (float)mp_obj_get_float(kw->table[i].value);
        values[index] = value < 0.0f ? 0.0f : (value > 1.0f ? 1.0f : value);
        given[index] = true;
    }
    if (live) {
        audiodsp_pump_lock_acquire();
    }
    for (uint32_t index = 0; index < plugin->param_count; ++index) {
        if (given[index]) {
            *airwindows_knob(self, index) = values[index];
        }
    }
    if (live) {
        audiodsp_pump_lock_release();
    }
}

mp_obj_t audioairwindows_make_new(const mp_obj_type_t *type,
    size_t n_args, size_t n_kw, const mp_obj_t *all_args) {
    mp_arg_check_num(n_args, n_kw, 0, 0, true);
    mp_map_t kw_map;
    mp_map_init_fixed_table(&kw_map, n_kw, all_args + n_args);

    uint32_t sample_rate = 48000;
    uint32_t channel_count = 2;
    for (size_t i = 0; i < kw_map.alloc; ++i) {
        if (!mp_map_slot_is_filled(&kw_map, i)) {
            continue;
        }
        qstr name = mp_obj_str_get_qstr(kw_map.table[i].key);
        if (name == MP_QSTR_sample_rate) {
            sample_rate = (uint32_t)mp_obj_get_int(kw_map.table[i].value);
        } else if (name == MP_QSTR_channel_count) {
            channel_count = (uint32_t)mp_obj_get_int(kw_map.table[i].value);
        }
    }
    if (sample_rate < 1) {
        mp_raise_ValueError(MP_ERROR_TEXT("sample_rate must be at least 1"));
    }
    if (channel_count < 1u || channel_count > 2u) {
        mp_raise_ValueError(MP_ERROR_TEXT("channel_count must be 1 or 2"));
    }
    const aw_plugin_t *plugin = airwindows_plugin(type);

    audioairwindows_obj_t *self = mp_obj_malloc(audioairwindows_obj_t, type);
    self->base.sample_rate = sample_rate;
    self->base.max_buffer_length = sizeof(self->buffer);
    self->base.bits_per_sample = 16;
    self->base.channel_count = (uint8_t)channel_count;
    self->base.samples_signed = 1;
    self->base.single_buffer = false;
    self->source = MP_OBJ_NULL;
    self->pending = NULL;
    self->pending_frames = 0;
    self->source_done = false;
    self->plugin = plugin;
    self->variant = airwindows_variant(plugin);
    self->state = m_malloc(self->variant->size);
    self->variant->init(self->state, (double)sample_rate);
    airwindows_apply_kwargs(self, &kw_map, false);
    return MP_OBJ_FROM_PTR(self);
}

static mp_obj_t audioairwindows_play(mp_obj_t self_in, mp_obj_t sample) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(&self->base);
    (void)audiosample_check(sample);
    audiodsp_pump_lock_acquire();
    self->source = sample;
    self->pending = NULL;
    self->pending_frames = 0;
    self->source_done = false;
    audiodsp_pump_lock_release();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(audioairwindows_play_obj,
    audioairwindows_play);

// Lets go of the source. The node keeps rendering (silence, and a reverb's
// tail) for whoever plays it.
static mp_obj_t audioairwindows_stop(mp_obj_t self_in) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(&self->base);
    audiodsp_pump_lock_acquire();
    self->source = MP_OBJ_NULL;
    self->pending = NULL;
    self->pending_frames = 0;
    self->source_done = false;
    audiodsp_pump_lock_release();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audioairwindows_stop_obj,
    audioairwindows_stop);

static mp_obj_t audioairwindows_get_playing(mp_obj_t self_in) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(&self->base);
    return mp_obj_new_bool(self->source != MP_OBJ_NULL);
}
static MP_DEFINE_CONST_FUN_OBJ_1(audioairwindows_get_playing_obj,
    audioairwindows_get_playing);
MP_PROPERTY_GETTER(audioairwindows_playing_obj,
    (mp_obj_t)&audioairwindows_get_playing_obj);

static mp_obj_t audioairwindows_set(size_t n_args, const mp_obj_t *args,
    mp_map_t *kw_args) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    audiosample_check_for_deinit(&self->base);
    (void)n_args;
    airwindows_apply_kwargs(self, kw_args, true);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(audioairwindows_set_obj, 1,
    audioairwindows_set);

// What a screen needs to draw the knobs: each parameter's keyword, upstream's
// display name and its default, in upstream's order.
static mp_obj_t audioairwindows_parameters(mp_obj_t self_in) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(&self->base);
    const aw_plugin_t *plugin = self->plugin;
    mp_obj_tuple_t *out = MP_OBJ_TO_PTR(mp_obj_new_tuple(plugin->param_count, NULL));
    for (uint32_t i = 0; i < plugin->param_count; ++i) {
        const aw_param_t *p = &plugin->params[i];
        mp_obj_t item[3] = {
            mp_obj_new_str(p->py, strlen(p->py)),
            mp_obj_new_str(p->name, strlen(p->name)),
            mp_obj_new_float((mp_float_t)p->def),
        };
        out->items[i] = mp_obj_new_tuple(3, item);
    }
    return MP_OBJ_FROM_PTR(out);
}
static MP_DEFINE_CONST_FUN_OBJ_1(audioairwindows_parameters_obj,
    audioairwindows_parameters);

// One knob where it is now, 0..1.
static mp_obj_t audioairwindows_get(mp_obj_t self_in, mp_obj_t name_in) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(&self->base);
    const aw_plugin_t *plugin = self->plugin;
    const char *text = mp_obj_str_get_str(name_in);
    for (uint32_t i = 0; i < plugin->param_count; ++i) {
        if (strcmp(plugin->params[i].py, text) == 0) {
            return mp_obj_new_float((mp_float_t)*airwindows_knob(self, i));
        }
    }
    mp_raise_msg_varg(&mp_type_KeyError,
        MP_ERROR_TEXT("unknown %q option '%s'"),
        (qstr)self->base.self.type->name, text);
}
static MP_DEFINE_CONST_FUN_OBJ_2(audioairwindows_get_obj, audioairwindows_get);

// The state as a newly built node's, with the knobs where they are.
static void airwindows_reset(audioairwindows_obj_t *self) {
    float knobs[AW_MAX_PARAMS];
    const uint32_t count = self->plugin->param_count;
    for (uint32_t i = 0; i < count; ++i) {
        knobs[i] = *airwindows_knob(self, i);
    }
    self->variant->init(self->state, (double)self->base.sample_rate);
    for (uint32_t i = 0; i < count; ++i) {
        *airwindows_knob(self, i) = knobs[i];
    }
}

static mp_obj_t audioairwindows_clear(mp_obj_t self_in) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiosample_check_for_deinit(&self->base);
    audiodsp_pump_lock_acquire();
    airwindows_reset(self);
    audiodsp_pump_lock_release();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audioairwindows_clear_obj,
    audioairwindows_clear);

static audioio_get_buffer_result_t audioairwindows_get_buffer(
    mp_obj_t self_in, bool single_channel_output, uint8_t channel,
    uint8_t **buffer, uint32_t *buffer_length) {
    (void)single_channel_output;
    (void)channel;
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    const uint32_t channels = self->base.channel_count;
    uint32_t produced = 0;
    while (produced < AW_FRAMES) {
        if (self->pending_frames == 0) {
            if (self->source_done) {
                self->source = MP_OBJ_NULL;
                self->source_done = false;
            }
            if (self->source == MP_OBJ_NULL) {
                break;
            }
            uint8_t *raw = NULL;
            uint32_t raw_bytes = 0;
            audioio_get_buffer_result_t result = audiosample_get_buffer(
                self->source, false, 0, &raw, &raw_bytes);
            const uint32_t width = 2u * channels;
            if (result == GET_BUFFER_ERROR || raw == NULL || raw_bytes < width) {
                if (result == GET_BUFFER_DONE) {
                    self->source = MP_OBJ_NULL;
                }
                break;
            }
            self->pending = (const int16_t *)raw;
            self->pending_frames = raw_bytes / width;
            self->source_done = (result == GET_BUFFER_DONE);
        }
        uint32_t run = AW_FRAMES - produced;
        if (run > self->pending_frames) {
            run = self->pending_frames;
        }
        self->variant->process(self->state,
            &self->buffer[produced * channels], self->pending,
            (int32_t)run, channels);
        self->pending += run * channels;
        self->pending_frames -= run;
        produced += run;
    }
    // What the source did not fill is rendered from silence, so the block is
    // always full and a reverb's tail rings out after its source ends. A node
    // in the middle of a live graph never reports itself finished.
    if (produced < AW_FRAMES) {
        self->variant->process(self->state,
            &self->buffer[produced * channels], airwindows_silence,
            (int32_t)(AW_FRAMES - produced), channels);
        produced = AW_FRAMES;
    }
    *buffer = (uint8_t *)self->buffer;
    *buffer_length = produced * 2u * channels;
    return GET_BUFFER_MORE_DATA;
}

static void audioairwindows_reset_buffer(mp_obj_t self_in,
    bool single_channel_output, uint8_t channel) {
    (void)single_channel_output;
    (void)channel;
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    // A host reset clears what this node holds of its own and keeps the
    // source frames it has already taken.
    airwindows_reset(self);
}

// Releases the source and the state and marks the node deinitialised, which
// is what makes every guarded entry point raise afterwards.
static mp_obj_t audioairwindows_deinit(mp_obj_t self_in) {
    audioairwindows_obj_t *self = MP_OBJ_TO_PTR(self_in);
    audiodsp_pump_lock_acquire();
    audiosample_mark_deinit(&self->base);
    self->source = MP_OBJ_NULL;
    self->pending = NULL;
    self->pending_frames = 0;
    self->source_done = false;
    self->state = NULL;
    audiodsp_pump_lock_release();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audioairwindows_deinit_obj,
    audioairwindows_deinit);

static const mp_rom_map_elem_t audioairwindows_locals_table[] = {
    { MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&audioairwindows_deinit_obj) },
    { MP_ROM_QSTR(MP_QSTR___enter__), MP_ROM_PTR(&default___enter___obj) },
    { MP_ROM_QSTR(MP_QSTR___exit__), MP_ROM_PTR(&default___exit___obj) },
    { MP_ROM_QSTR(MP_QSTR_play), MP_ROM_PTR(&audioairwindows_play_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop), MP_ROM_PTR(&audioairwindows_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_playing), MP_ROM_PTR(&audioairwindows_playing_obj) },
    { MP_ROM_QSTR(MP_QSTR_set), MP_ROM_PTR(&audioairwindows_set_obj) },
    { MP_ROM_QSTR(MP_QSTR_clear), MP_ROM_PTR(&audioairwindows_clear_obj) },
    { MP_ROM_QSTR(MP_QSTR_parameters), MP_ROM_PTR(&audioairwindows_parameters_obj) },
    { MP_ROM_QSTR(MP_QSTR_get), MP_ROM_PTR(&audioairwindows_get_obj) },
    AUDIOSAMPLE_FIELDS,
};
MP_DEFINE_CONST_DICT(audioairwindows_locals, audioairwindows_locals_table);

static mp_obj_t audioairwindows_sources(mp_obj_t self_in, uint8_t index) {
    return index == 0 ? ((audioairwindows_obj_t *)MP_OBJ_TO_PTR(self_in))->source
                      : MP_OBJ_NULL;
}

const audiosample_p_t audioairwindows_proto = {
    MP_PROTO_IMPLEMENT(MP_QSTR_protocol_audiosample)
    .reset_buffer = audioairwindows_reset_buffer,
    .get_buffer = audioairwindows_get_buffer,
    .sources = audioairwindows_sources,
};

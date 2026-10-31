// _audioairwindows: the CPython extension under audioairwindows.py. One state
// type for every plug-in, told apart by the name it was built with.
// It renders int16 frames; the audiocore node around it lives in Python.
//
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <string.h>

#include "airwindows/registry.h"

#define AW_FRAMES 256
#ifndef AW_FAST_DEFAULT
#define AW_FAST_DEFAULT 0
#endif

#ifndef AW_VERSION
#define AW_VERSION "unknown"
#endif
#ifndef AW_REVISION
#define AW_REVISION "unknown"
#endif

// On a free-threaded build each call holds the object's own lock, so two
// threads sharing a node can't render into one state at once. Older Pythons
// have the GIL and no critical sections, and need nothing.
#ifndef Py_BEGIN_CRITICAL_SECTION
#define Py_BEGIN_CRITICAL_SECTION(op) {
#define Py_END_CRITICAL_SECTION() }
#endif

#define AW_LOCKED_ARGS(name, type) \
    static PyObject *name##_locked(PyObject *self, PyObject *arg) { \
        PyObject *result; \
        Py_BEGIN_CRITICAL_SECTION(self); \
        result = name((type *)self, arg); \
        Py_END_CRITICAL_SECTION(); \
        return result; \
    }
#define AW_LOCKED_INIT(name, type) \
    static int name##_locked(PyObject *self, PyObject *args, \
        PyObject *kwargs) { \
        int result; \
        Py_BEGIN_CRITICAL_SECTION(self); \
        result = name((type *)self, args, kwargs); \
        Py_END_CRITICAL_SECTION(); \
        return result; \
    }

// One state type for every plug-in, told apart by the descriptor it was
// built from (airwindows/registry.c lists them).
typedef struct {
    PyObject_HEAD
    const aw_plugin_t *plugin;
    const aw_variant_t *variant;
    unsigned int sample_rate;
    unsigned int channel_count;
    uint8_t *state;
} aw_object_t;

static const int16_t aw_silence[AW_FRAMES * 2];

static int airwindows_state_init(aw_object_t *self,
    PyObject *args, PyObject *kwargs) {
    const char *name = NULL;
    unsigned int sample_rate = 48000;
    unsigned int channel_count = 2;
    int fast = AW_FAST_DEFAULT;
    static char *keywords[] = {
        "name", "sample_rate", "channel_count", "fast", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|IIp:State",
        keywords, &name, &sample_rate, &channel_count, &fast)) return -1;
    const aw_plugin_t *plugin = NULL;
    for (const aw_plugin_t *const *p = aw_plugins; *p != NULL; ++p) {
        if (strcmp((*p)->name, name) == 0) {
            plugin = *p;
            break;
        }
    }
    if (plugin == NULL) {
        PyErr_Format(PyExc_ValueError, "no Airwindows plug-in %s in this build",
            name);
        return -1;
    }
    if (sample_rate < 1) {
        PyErr_SetString(PyExc_ValueError, "sample_rate must be at least 1");
        return -1;
    }
    if (channel_count < 1 || channel_count > 2) {
        PyErr_SetString(PyExc_ValueError, "channel_count must be 1 or 2");
        return -1;
    }
    const aw_variant_t *variant = fast ? &plugin->fast : &plugin->ref;
    if (variant->process == NULL) {
        variant = fast ? &plugin->ref : &plugin->fast;
    }
    uint8_t *state = PyMem_Calloc(1, variant->size);
    if (state == NULL) {
        PyErr_NoMemory();
        return -1;
    }
    variant->init(state, (double)sample_rate);
    PyMem_Free(self->state);
    self->state = state;
    self->plugin = plugin;
    self->variant = variant;
    self->sample_rate = sample_rate;
    self->channel_count = channel_count;
    return 0;
}

static void airwindows_state_dealloc(aw_object_t *self) {
    PyTypeObject *type = Py_TYPE(self);
    PyMem_Free(self->state);
    self->state = NULL;
    type->tp_free((PyObject *)self);
    Py_DECREF(type);
}

static int airwindows_state_ready(aw_object_t *self) {
    if (self->state == NULL) {
        PyErr_SetString(PyExc_ValueError, "State was never initialised");
        return 0;
    }
    return 1;
}

static float *airwindows_knob(aw_object_t *self, uint32_t index) {
    return (float *)(self->state + self->variant->offsets[index]);
}

// Knobs are 0..1, as upstream's are; values outside are clamped.
static PyObject *airwindows_state_configure(aw_object_t *self,
    PyObject *args) {
    int index;
    double value;
    if (!PyArg_ParseTuple(args, "id:configure", &index, &value)) return NULL;
    if (!airwindows_state_ready(self)) return NULL;
    if (index < 0 || (uint32_t)index >= self->plugin->param_count) {
        PyErr_SetString(PyExc_ValueError, "unknown Airwindows parameter");
        return NULL;
    }
    float knob = (float)value;
    *airwindows_knob(self, (uint32_t)index) =
        knob < 0.0f ? 0.0f : (knob > 1.0f ? 1.0f : knob);
    Py_RETURN_NONE;
}

// The state as a newly built one's, with the knobs where they are.
static PyObject *airwindows_state_reset(aw_object_t *self,
    PyObject *unused) {
    (void)unused;
    if (!airwindows_state_ready(self)) return NULL;
    float knobs[64];
    const uint32_t count = self->plugin->param_count;
    for (uint32_t i = 0; i < count; ++i) knobs[i] = *airwindows_knob(self, i);
    self->variant->init(self->state, (double)self->sample_rate);
    for (uint32_t i = 0; i < count; ++i) *airwindows_knob(self, i) = knobs[i];
    Py_RETURN_NONE;
}

static void airwindows_render(aw_object_t *self, int16_t *out,
    const int16_t *in, Py_ssize_t frames) {
    while (frames > 0) {
        const int32_t run = frames > AW_FRAMES ? AW_FRAMES : (int32_t)frames;
        self->variant->process(self->state, out, in ? in : aw_silence, run,
            self->channel_count);
        out += run * self->channel_count;
        if (in) in += run * self->channel_count;
        frames -= run;
    }
}

static PyObject *airwindows_state_process(aw_object_t *self,
    PyObject *argument) {
    if (!airwindows_state_ready(self)) return NULL;
    Py_buffer input = {0};
    if (PyObject_GetBuffer(argument, &input, PyBUF_SIMPLE) < 0) return NULL;
    const Py_ssize_t width = 2 * (Py_ssize_t)self->channel_count;
    if (input.len % width) {
        PyBuffer_Release(&input);
        PyErr_SetString(PyExc_ValueError,
            "input must be whole 16-bit frames for the configured channel count");
        return NULL;
    }
    PyObject *result = PyBytes_FromStringAndSize(NULL, input.len);
    if (result != NULL) {
        airwindows_render(self, (int16_t *)PyBytes_AS_STRING(result),
            (const int16_t *)input.buf, input.len / width);
    }
    PyBuffer_Release(&input);
    return result;
}

// `frames` of output from silence, for a node whose source has ended: a
// reverb's tail rings out.
static PyObject *airwindows_state_process_silence(
    aw_object_t *self, PyObject *argument) {
    if (!airwindows_state_ready(self)) return NULL;
    const Py_ssize_t frames = PyLong_AsSsize_t(argument);
    if (frames == -1 && PyErr_Occurred()) return NULL;
    if (frames < 0) {
        PyErr_SetString(PyExc_ValueError, "frames must not be negative");
        return NULL;
    }
    const Py_ssize_t width = 2 * (Py_ssize_t)self->channel_count;
    PyObject *result = PyBytes_FromStringAndSize(NULL, frames * width);
    if (result != NULL) {
        airwindows_render(self, (int16_t *)PyBytes_AS_STRING(result), NULL,
            frames);
    }
    return result;
}

AW_LOCKED_ARGS(airwindows_state_configure, aw_object_t)
AW_LOCKED_ARGS(airwindows_state_reset, aw_object_t)
AW_LOCKED_ARGS(airwindows_state_process, aw_object_t)
AW_LOCKED_ARGS(airwindows_state_process_silence, aw_object_t)
static PyMethodDef airwindows_state_methods[] = {
    {"configure", (PyCFunction)airwindows_state_configure_locked, METH_VARARGS, NULL},
    {"reset", (PyCFunction)airwindows_state_reset_locked, METH_NOARGS, NULL},
    {"process", (PyCFunction)airwindows_state_process_locked, METH_O, NULL},
    {"process_silence", (PyCFunction)airwindows_state_process_silence_locked, METH_O, NULL},
    {NULL, NULL, 0, NULL},
};

AW_LOCKED_INIT(airwindows_state_init, aw_object_t)
static PyType_Slot airwindows_state_slots[] = {
    {Py_tp_new, PyType_GenericNew},
    {Py_tp_init, airwindows_state_init_locked},
    {Py_tp_dealloc, airwindows_state_dealloc},
    {Py_tp_methods, airwindows_state_methods},
    {0, NULL},
};

static PyType_Spec airwindows_state_spec = {
    .name = "_audioairwindows.State",
    .basicsize = sizeof(aw_object_t),
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HEAPTYPE,
    .slots = airwindows_state_slots,
};

static int aw_module_exec(PyObject *module) {
    PyObject *type = PyType_FromModuleAndSpec(module, &airwindows_state_spec,
        NULL);
    if (type == NULL) return -1;
    int failed = PyModule_AddObjectRef(module, "State", type) < 0;
    Py_DECREF(type);
    if (failed) return -1;
    if (PyModule_AddStringConstant(module, "__version__", AW_VERSION) < 0 ||
        PyModule_AddStringConstant(module, "__revision__", AW_REVISION) < 0 ||
        PyModule_AddIntConstant(module, "FRAMES", AW_FRAMES) < 0 ||
        PyModule_AddIntConstant(module, "FAST_DEFAULT", AW_FAST_DEFAULT) < 0) {
        return -1;
    }
    return 0;
}

static PyModuleDef_Slot aw_module_slots[] = {
    {Py_mod_exec, aw_module_exec},
#ifdef Py_mod_multiple_interpreters
    {Py_mod_multiple_interpreters, Py_MOD_PER_INTERPRETER_GIL_SUPPORTED},
#endif
#ifdef Py_GIL_DISABLED
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
#endif
    {0, NULL},
};

static struct PyModuleDef aw_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_audioairwindows",
    .m_doc = "The generated Airwindows kernels, as State objects.",
    .m_size = 0,
    .m_slots = aw_module_slots,
};

PyMODINIT_FUNC PyInit__audioairwindows(void) {
    return PyModuleDef_Init(&aw_module);
}

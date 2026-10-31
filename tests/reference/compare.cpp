// The reference harness: runs one upstream plug-in and its generated kernel
// (both variants) on the same int16 test signal and reports how far apart
// they are.
//
//   compare RATE FAULT P0 P1 ...
//
// RATE is the sample rate, FAULT 0 or a planted fault (see below), Pn the
// parameters in upstream's 0..1. It prints one line of JSON.
//
// Upstream runs exactly as a host would run it, in 256-frame blocks of
// float, from a zeroed object (a host's allocator gives no promise, but
// the generated kernels zero their state, and upstream's constructors leave
// a few members unset). Its random seeds and rand() are set to the
// generated kernel's, so dithered and noisy plug-ins compare sample for
// sample. Its float output is rounded to int16 the way the kernel rounds.
//
// Built by tests/reference/check.py with -DPLUGIN=Name, -DPLUGIN_H="Name.h",
// -DAW_DESC=aw_plugin_Name and -DAW_SET_SEEDS(p)=... from the generator.
//
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
#define private public
#define protected public
#include PLUGIN_H
#include "airwindows/plugin.h"
#include <cmath>
#include <new>
#include <vector>

extern "C" const aw_plugin_t AW_DESC;
extern "C" {
double aw_harness_sr = 44100.0;
static uint32_t harness_rand_state = 12345u;
int aw_harness_rand(void) {
    harness_rand_state = harness_rand_state * 1103515245u + 12345u;
    return (int)(harness_rand_state >> 1);
}
}

static uint32_t aw_seed(int index) {
    if (index == 0) {
        return 2463534242u;
    }
    uint32_t x = 1588635695u;
    while (--index > 0) {
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
    }
    return x;
}

static int16_t to_s16(float sample) {
    float scaled = floorf(sample * 32768.0f + 0.5f);
    if (scaled > 32767.0f) return 32767;
    if (scaled < -32768.0f) return -32768;
    return (int16_t)scaled;
}

// The test signal: two tones, a noise burst, a log sweep across the band, a
// square wave, an impulse, then silence so the tails are compared too.
static std::vector<int16_t> make_signal(double rate) {
    const size_t frames = (size_t)(1.5 * rate);
    std::vector<int16_t> pcm(frames * 2);
    uint32_t noise = 1;
    for (size_t i = 0; i < frames; ++i) {
        const double t = i / rate;
        double l = 0, r = 0;
        if (t < 0.30) {
            l = 0.5 * sin(2 * M_PI * 220 * t);
            r = 0.6 * sin(2 * M_PI * 331 * t + 1);
        } else if (t < 0.35) {
            noise = noise * 1664525u + 1013904223u;
            l = 0.3 * ((int32_t)noise / 2147483648.0);
            noise = noise * 1664525u + 1013904223u;
            r = 0.3 * ((int32_t)noise / 2147483648.0);
        } else if (t < 0.85) {
            const double u = (t - 0.35) / 0.5;
            const double k = log(1000.0);
            const double phase = 2 * M_PI * 20 * 0.5 * (exp(k * u) - 1) / k;
            l = 0.4 * sin(phase);
            r = -0.4 * sin(phase);
        } else if (t < 0.95) {
            l = r = sin(2 * M_PI * 100 * t) >= 0 ? 0.3 : -0.3;
        } else if (i == (size_t)(0.95 * rate)) {
            l = 0.9;
            r = -0.9;
        }
        pcm[2 * i] = (int16_t)lrint(l * 32767);
        pcm[2 * i + 1] = (int16_t)lrint(r * 32767);
    }
    return pcm;
}

static std::vector<float> run_upstream(double rate, const std::vector<float> &params,
    const std::vector<int16_t> &pcm, bool *finite) {
    aw_harness_sr = rate;
    void *mem = calloc(1, sizeof(PLUGIN));
    PLUGIN *p = new (mem) PLUGIN(nullptr);
    p->sr = rate;
    AW_SET_SEEDS(p);
    harness_rand_state = 12345u;
#ifndef AW_NO_PARAMS
    for (size_t i = 0; i < params.size(); ++i) {
        p->setParameter((VstInt32)i, params[i]);
    }
#endif
    const size_t frames = pcm.size() / 2;
    std::vector<float> l(frames), r(frames), ol(frames), orr(frames);
    for (size_t i = 0; i < frames; ++i) {
        l[i] = pcm[2 * i] * (1.0f / 32768.0f);
        r[i] = pcm[2 * i + 1] * (1.0f / 32768.0f);
    }
    for (size_t at = 0; at < frames; at += 256) {
        int n = (int)((frames - at) < 256 ? frames - at : 256);
        float *ins[2] = {&l[at], &r[at]};
        float *outs[2] = {&ol[at], &orr[at]};
        p->processReplacing(ins, outs, n);
    }
    std::vector<float> out(frames * 2);
    *finite = true;
    for (size_t i = 0; i < frames; ++i) {
        out[2 * i] = ol[i];
        out[2 * i + 1] = orr[i];
        if (!std::isfinite(ol[i]) || !std::isfinite(orr[i])) *finite = false;
    }
    return out;
}

static std::vector<int16_t> run_port(const aw_variant_t &v, double rate,
    const std::vector<float> &params, const std::vector<int16_t> &pcm,
    int fault) {
    std::vector<uint8_t> state(v.size + 16);
    v.init(state.data(), rate);
    for (size_t i = 0; i < params.size(); ++i) {
        memcpy(state.data() + v.offsets[i], &params[i], sizeof(float));
    }
    const size_t frames = pcm.size() / 2;
    std::vector<int16_t> out(frames * 2);
    for (size_t at = 0; at < frames; at += 256) {
        int n = (int)((frames - at) < 256 ? frames - at : 256);
        v.process(state.data(), &out[2 * at], &pcm[2 * at], n, 2);
    }
    if (fault == 1 || fault == 2) {
        // A gain error on one side: 1 part in 4096, or 1 in 256 for a
        // plug-in too quiet for the first to move a sample past the bar.
        const float g = 1.0f + (fault == 1 ? 1.0f / 4096 : 1.0f / 256);
        for (size_t i = 0; i < frames; ++i) {
            out[2 * i] = to_s16(out[2 * i] / 32768.0f * g);
        }
    }
    return out;
}

struct Stats {
    double peak_lsb;
    long max_lsb;
    long at;
    double err_db;
    double sig_db;
};

static Stats compare(const std::vector<int16_t> &port, const std::vector<float> &up) {
    Stats s = {0, 0, -1, -400, -400};
    double err = 0, sig = 0;
    for (size_t i = 0; i < port.size(); ++i) {
        const long q = to_s16(std::isfinite(up[i]) ? up[i] : 0.0f);
        const long d = labs((long)port[i] - q);
        if (d > s.max_lsb) {
            s.max_lsb = d;
            s.at = (long)(i / 2);
        }
        float u = std::isfinite(up[i]) ? up[i] : 0.0f;
        u = u > 32767.0f / 32768.0f ? 32767.0f / 32768.0f : (u < -1.0f ? -1.0f : u);
        const double e = port[i] / 32768.0 - u;
        if (fabs(e) * 32768.0 > s.peak_lsb) s.peak_lsb = fabs(e) * 32768.0;
        err += e * e;
        sig += (double)u * u;
    }
    const double n = port.size() ? port.size() : 1;
    if (err > 0) s.err_db = 10 * log10(err / n);
    if (sig > 0) s.sig_db = 10 * log10(sig / n);
    return s;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: compare RATE FAULT P0 P1 ...\n");
        return 2;
    }
    const double rate = atof(argv[1]);
    const int fault = atoi(argv[2]);
    std::vector<float> params;
    for (int i = 3; i < argc; ++i) params.push_back((float)atof(argv[i]));
    if (params.size() != AW_DESC.param_count) {
        fprintf(stderr, "%s takes %u parameters\n", AW_DESC.name,
            (unsigned)AW_DESC.param_count);
        return 2;
    }
    const std::vector<int16_t> pcm = make_signal(rate);
    bool finite = true;
    const std::vector<float> up = run_upstream(rate, params, pcm, &finite);
    printf("{\"rate\": %g, \"finite\": %s", rate, finite ? "true" : "false");
    const aw_variant_t *variants[2] = {&AW_DESC.ref, &AW_DESC.fast};
    const char *names[2] = {"ref", "fast"};
    for (int k = 0; k < 2; ++k) {
        if (!variants[k]->process) continue;
        const std::vector<int16_t> port = run_port(*variants[k], rate, params, pcm, fault);
        const Stats s = compare(port, up);
        if (getenv("AW_DUMP")) {
            // AW_DUMP=prefix writes prefix.up.f32, prefix.ref.s16, prefix.fast.s16.
            char path[512];
            snprintf(path, sizeof path, "%s.%s.s16", getenv("AW_DUMP"), names[k]);
            FILE *f = fopen(path, "wb");
            fwrite(port.data(), 2, port.size(), f);
            fclose(f);
            snprintf(path, sizeof path, "%s.up.f32", getenv("AW_DUMP"));
            f = fopen(path, "wb");
            fwrite(up.data(), 4, up.size(), f);
            fclose(f);
        }
        printf(", \"%s\": {\"max_lsb\": %ld, \"peak_lsb\": %.2f, \"at\": %ld, "
               "\"err_db\": %.1f, \"sig_db\": %.1f}", names[k], s.max_lsb,
               s.peak_lsb, s.at, s.err_db, s.sig_db);
    }
    printf("}\n");
    return 0;
}

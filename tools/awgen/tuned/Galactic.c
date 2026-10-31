// Galactic for the ESP32-S3 (plugin.h, AW_TUNED): upstream's float arithmetic
// in the translated loop's order, with its delay lines laid out for the S3.
// Each line holds its left and right side together, so one address serves
// both and they share a cache line, and the loop walks each line with a
// pointer rather than a counter and an offset into a 470 kB state, which on
// Xtensa costs a literal load and an add per access. 22.8 % of a core
// against 25.7 % for the translated loop. The same reverb in Q23 fixed point
// measured 23.0 %: the integer registers run out before the FPU's do.
//
// Upstream's denormal guard adds noise near 1e-17 to a zero input, which
// only the dry side of the mix would carry; it is left out there. Its
// generators still run, because the vibrato draws its next rate from fpdL.
typedef struct {
    float l, r;
} aw_pair_t;

typedef struct {
    double aw_sample_rate;
    uint32_t aw_rand;
    float iirAL;
    float iirBL;
    aw_pair_t aI[6480];
    aw_pair_t aJ[3660];
    aw_pair_t aK[1720];
    aw_pair_t aL[680];
    aw_pair_t aA[9700];
    aw_pair_t aB[6000];
    aw_pair_t aC[2320];
    aw_pair_t aD[940];
    aw_pair_t aE[15220];
    aw_pair_t aF[8460];
    aw_pair_t aG[4540];
    aw_pair_t aH[3200];
    float aML[3111];
    float aMR[3111];
    double oldfpd;
    float feedbackAL;
    float feedbackBL;
    float feedbackCL;
    float feedbackDL;
    float lastRefL[7];
    float iirAR;
    float iirBR;
    float feedbackAR;
    float feedbackBR;
    float feedbackCR;
    float feedbackDR;
    float lastRefR[7];
    int countA;
    int countB;
    int countC;
    int countD;
    int countE;
    int countF;
    int countG;
    int countH;
    int countI;
    int countJ;
    int countK;
    int countL;
    int countM;
    int cycle;
    uint64_t vibM;
    uint32_t fpdL;
    uint32_t fpdR;
    float A;
    float B;
    float C;
    float D;
    float E;
} aw_Galactic_fast_t;

static void aw_Galactic_init_fast(void *aw_state, double aw_rate) {
    aw_Galactic_fast_t *aw_s = (aw_Galactic_fast_t *)aw_state;
    // Every delay line, filter and feedback starts at zero.
    memset(aw_s, 0, sizeof(*aw_s));
    aw_s->aw_sample_rate = aw_rate;
    aw_s->aw_rand = AW_RAND_SEED;
    aw_s->A = 0.5f;
    aw_s->B = 0.5f;
    aw_s->C = 0.5f;
    aw_s->D = 1.0f;
    aw_s->E = 1.0f;
    aw_s->countI = aw_s->countJ = aw_s->countK = aw_s->countL = 1;
    aw_s->countA = aw_s->countB = aw_s->countC = aw_s->countD = 1;
    aw_s->countE = aw_s->countF = aw_s->countG = aw_s->countH = 1;
    aw_s->countM = 1;
    aw_s->vibM = AW_Q60(3.0);
    aw_s->oldfpd = 429496.7295;
    aw_s->fpdL = aw_seed(0);
    aw_s->fpdR = aw_seed(1);
}

// A delay line as the loop walks it: where it writes next, and its two ends.
// Stepping past `last` goes back to `base`, as upstream's counter does.
typedef struct {
    aw_pair_t *at, *base, *last;
} aw_line_t;

#define AW_G_STEP(line) do { \
        if (++(line).at > (line).last) (line).at = (line).base; \
} while (0)

// a - (b + c + d), Galactic's Householder row.
#define AW_G_ROW(a, b, c, d) ((a) - ((b) + (c) + (d)))

static void aw_Galactic_process_fast(void *aw_state, int16_t *aw_out,
    const int16_t *aw_in, int32_t sampleFrames, uint32_t aw_channels) {
    aw_Galactic_fast_t *s = (aw_Galactic_fast_t *)aw_state;
    const double overallscale = s->aw_sample_rate / 44100.0;
    int cycleEnd = (int)floor(overallscale);
    if (cycleEnd < 1) cycleEnd = 1;
    if (cycleEnd > 4) cycleEnd = 4;
    int cycle = s->cycle;
    if (cycle > cycleEnd - 1) cycle = cycleEnd - 1;

    const double A = s->A, B = s->B, C = s->C, D = s->D, E = s->E;
    const double regen = 0.0625 + ((1.0 - A) * 0.0625);
    const double attenuate = (1.0 - (regen / 0.125)) * 1.333;
    const double lowpass = pow(1.00001 - (1.0 - B), 2.0) / sqrt(overallscale);
    const double drift = pow(C, 3) * 0.001;
    const double size = (D * 1.77) + 0.1;
    const double wet = 1.0 - (pow(1.0 - E, 3));
    const int delayI = 3407.0 * size, delayJ = 1823.0 * size;
    const int delayK = 859.0 * size, delayL = 331.0 * size;
    const int delayA = 4801.0 * size, delayB = 2909.0 * size;
    const int delayC = 1153.0 * size, delayD = 461.0 * size;
    const int delayE = 7607.0 * size, delayF = 4217.0 * size;
    const int delayG = 2269.0 * size, delayH = 1597.0 * size;
    const int delayM = 256;

    const float regenF = (float)regen;
    const float attenuateF = (float)attenuate;
    const float lowpassF = (float)lowpass;
    const bool mix = wet < 1.0;
    const float wetF = (float)wet;

    float iirAL = s->iirAL, iirBL = s->iirBL, iirAR = s->iirAR, iirBR = s->iirBR;
    float feedbackAL = s->feedbackAL, feedbackBL = s->feedbackBL;
    float feedbackCL = s->feedbackCL, feedbackDL = s->feedbackDL;
    float feedbackAR = s->feedbackAR, feedbackBR = s->feedbackBR;
    float feedbackCR = s->feedbackCR, feedbackDR = s->feedbackDR;
    // I, J, K, L, A, B, C, D, E, F, G, H.
    aw_pair_t *const bases[12] = {s->aI, s->aJ, s->aK, s->aL, s->aA, s->aB,
                                  s->aC, s->aD, s->aE, s->aF, s->aG, s->aH};
    int *const counts[12] = {&s->countI, &s->countJ, &s->countK, &s->countL,
                             &s->countA, &s->countB, &s->countC, &s->countD,
                             &s->countE, &s->countF, &s->countG, &s->countH};
    const int delays[12] = {delayI, delayJ, delayK, delayL, delayA, delayB,
                            delayC, delayD, delayE, delayF, delayG, delayH};
    aw_line_t ln[12];
    for (int n = 0; n < 12; ++n) {
        ln[n].base = bases[n];
        ln[n].at = bases[n] + *counts[n];
        ln[n].last = bases[n] + delays[n];
    }
    int countM = s->countM;
    uint64_t vibM = s->vibM;
    double oldfpd = s->oldfpd;
    uint32_t fpdL = s->fpdL, fpdR = s->fpdR;
    float *lastRefL = s->lastRefL, *lastRefR = s->lastRefR;
    uint64_t stepM = AW_Q60_STEP(oldfpd * drift);

    while (--sampleFrames >= 0) {
        const int32_t inL = aw_in[0];
        const int32_t inR = aw_in[aw_channels - 1];

        vibM += stepM;
        if (vibM > AW_Q60(3.141592653589793238 * 2.0)) {
            vibM = AW_Q60(0.0);
            oldfpd = 0.4294967295 + (fpdL * 0.0000000000618);
            stepM = AW_Q60_STEP(oldfpd * drift);
        }

        // The vibrato predelay, in float as the translated variant has it.
        s->aML[countM] = aw_from_s16(inL) * attenuateF;
        s->aMR[countM] = aw_from_s16(inR) * attenuateF;
        countM++; if (countM < 0 || countM > delayM) countM = 0;
        const float phase = aw_q60f(vibM);
        const float offsetML = (aw_sinf(phase) + 1.0f) * 127;
        const float offsetMR = (aw_sinf(phase + 3.141592653589793238f * 0.5f) + 1.0f) * 127;
        const float floorML = aw_floorf(offsetML), floorMR = aw_floorf(offsetMR);
        const int workingML = countM + (int)floorML;
        const int workingMR = countM + (int)floorMR;
        const float *aML = s->aML, *aMR = s->aMR;
        float interpolML = aML[workingML - ((workingML > delayM) ? delayM + 1 : 0)] * (1 - (offsetML - floorML));
        interpolML += aML[workingML + 1 - ((workingML + 1 > delayM) ? delayM + 1 : 0)] * (offsetML - floorML);
        float interpolMR = aMR[workingMR - ((workingMR > delayM) ? delayM + 1 : 0)] * (1 - (offsetMR - floorMR));
        interpolMR += aMR[workingMR + 1 - ((workingMR + 1 > delayM) ? delayM + 1 : 0)] * (offsetMR - floorMR);

        iirAL = (iirAL * (1.0f - lowpassF)) + (interpolML * lowpassF);
        iirAR = (iirAR * (1.0f - lowpassF)) + (interpolMR * lowpassF);
        float sampleL, sampleR;

        cycle++;
        if (cycle == cycleEnd) {
            // The first block: write the input and the cross-fed feedback,
            // step, and read the oldest tap of each line.
            aw_pair_t *w;
            w = ln[0].at; w->l = iirAL + (feedbackAR * regenF); w->r = iirAR + (feedbackAL * regenF);
            w = ln[1].at; w->l = iirAL + (feedbackBR * regenF); w->r = iirAR + (feedbackBL * regenF);
            w = ln[2].at; w->l = iirAL + (feedbackCR * regenF); w->r = iirAR + (feedbackCL * regenF);
            w = ln[3].at; w->l = iirAL + (feedbackDR * regenF); w->r = iirAR + (feedbackDL * regenF);
            AW_G_STEP(ln[0]);
            AW_G_STEP(ln[1]);
            AW_G_STEP(ln[2]);
            AW_G_STEP(ln[3]);
            aw_pair_t i = *ln[0].at;
            aw_pair_t j = *ln[1].at;
            aw_pair_t k = *ln[2].at;
            aw_pair_t l = *ln[3].at;

            // Each later block is the Householder rows of the one before.
            w = ln[4].at; w->l = AW_G_ROW(i.l, j.l, k.l, l.l); w->r = AW_G_ROW(i.r, j.r, k.r, l.r);
            w = ln[5].at; w->l = AW_G_ROW(j.l, i.l, k.l, l.l); w->r = AW_G_ROW(j.r, i.r, k.r, l.r);
            w = ln[6].at; w->l = AW_G_ROW(k.l, i.l, j.l, l.l); w->r = AW_G_ROW(k.r, i.r, j.r, l.r);
            w = ln[7].at; w->l = AW_G_ROW(l.l, i.l, j.l, k.l); w->r = AW_G_ROW(l.r, i.r, j.r, k.r);
            AW_G_STEP(ln[4]);
            AW_G_STEP(ln[5]);
            AW_G_STEP(ln[6]);
            AW_G_STEP(ln[7]);
            i = *ln[4].at;
            j = *ln[5].at;
            k = *ln[6].at;
            l = *ln[7].at;

            w = ln[8].at; w->l = AW_G_ROW(i.l, j.l, k.l, l.l); w->r = AW_G_ROW(i.r, j.r, k.r, l.r);
            w = ln[9].at; w->l = AW_G_ROW(j.l, i.l, k.l, l.l); w->r = AW_G_ROW(j.r, i.r, k.r, l.r);
            w = ln[10].at; w->l = AW_G_ROW(k.l, i.l, j.l, l.l); w->r = AW_G_ROW(k.r, i.r, j.r, l.r);
            w = ln[11].at; w->l = AW_G_ROW(l.l, i.l, j.l, k.l); w->r = AW_G_ROW(l.r, i.r, j.r, k.r);
            AW_G_STEP(ln[8]);
            AW_G_STEP(ln[9]);
            AW_G_STEP(ln[10]);
            AW_G_STEP(ln[11]);
            i = *ln[8].at;
            j = *ln[9].at;
            k = *ln[10].at;
            l = *ln[11].at;

            feedbackAL = AW_G_ROW(i.l, j.l, k.l, l.l);
            feedbackBL = AW_G_ROW(j.l, i.l, k.l, l.l);
            feedbackCL = AW_G_ROW(k.l, i.l, j.l, l.l);
            feedbackDL = AW_G_ROW(l.l, i.l, j.l, k.l);
            feedbackAR = AW_G_ROW(i.r, j.r, k.r, l.r);
            feedbackBR = AW_G_ROW(j.r, i.r, k.r, l.r);
            feedbackCR = AW_G_ROW(k.r, i.r, j.r, l.r);
            feedbackDR = AW_G_ROW(l.r, i.r, j.r, k.r);

            // The four outputs' sum over 8.
            sampleL = (i.l + j.l + k.l + l.l) * 0.125f;
            sampleR = (i.r + j.r + k.r + l.r) * 0.125f;
            // Above 44.1 kHz the reverb runs every cycleEnd samples and the
            // samples between are straight lines from the last.
            if (cycleEnd == 4) {
                lastRefL[0] = lastRefL[4];
                lastRefL[2] = (lastRefL[0] + sampleL) * 0.5f;
                lastRefL[1] = (lastRefL[0] + lastRefL[2]) * 0.5f;
                lastRefL[3] = (lastRefL[2] + sampleL) * 0.5f;
                lastRefL[4] = sampleL;
                lastRefR[0] = lastRefR[4];
                lastRefR[2] = (lastRefR[0] + sampleR) * 0.5f;
                lastRefR[1] = (lastRefR[0] + lastRefR[2]) * 0.5f;
                lastRefR[3] = (lastRefR[2] + sampleR) * 0.5f;
                lastRefR[4] = sampleR;
            }
            if (cycleEnd == 3) {
                const float third = 1.0f / 3.0f;
                lastRefL[0] = lastRefL[3];
                lastRefL[2] = (lastRefL[0] + lastRefL[0] + sampleL) * third;
                lastRefL[1] = (lastRefL[0] + sampleL + sampleL) * third;
                lastRefL[3] = sampleL;
                lastRefR[0] = lastRefR[3];
                lastRefR[2] = (lastRefR[0] + lastRefR[0] + sampleR) * third;
                lastRefR[1] = (lastRefR[0] + sampleR + sampleR) * third;
                lastRefR[3] = sampleR;
            }
            if (cycleEnd == 2) {
                lastRefL[0] = lastRefL[2];
                lastRefL[1] = (lastRefL[0] + sampleL) * 0.5f;
                lastRefL[2] = sampleL;
                lastRefR[0] = lastRefR[2];
                lastRefR[1] = (lastRefR[0] + sampleR) * 0.5f;
                lastRefR[2] = sampleR;
            }
            if (cycleEnd == 1) {
                lastRefL[0] = sampleL;
                lastRefR[0] = sampleR;
            }
            cycle = 0;
            sampleL = lastRefL[cycle];
            sampleR = lastRefR[cycle];
        } else {
            sampleL = lastRefL[cycle];
            sampleR = lastRefR[cycle];
        }

        iirBL = (iirBL * (1.0f - lowpassF)) + (sampleL * lowpassF);
        iirBR = (iirBR * (1.0f - lowpassF)) + (sampleR * lowpassF);
        sampleL = iirBL;
        sampleR = iirBR;
        if (mix) {
            sampleL = (sampleL * wetF) + (aw_from_s16(inL) * (1.0f - wetF));
            sampleR = (sampleR * wetF) + (aw_from_s16(inR) * (1.0f - wetF));
        }
        fpdL ^= fpdL << 13; fpdL ^= fpdL >> 17; fpdL ^= fpdL << 5;
        fpdR ^= fpdR << 13; fpdR ^= fpdR >> 17; fpdR ^= fpdR << 5;

        AW_OUT_FAST(aw_out, aw_channels, sampleL, sampleR);
        aw_in += aw_channels;
        aw_out += aw_channels;
    }
    s->iirAL = iirAL; s->iirBL = iirBL; s->iirAR = iirAR; s->iirBR = iirBR;
    s->feedbackAL = feedbackAL; s->feedbackBL = feedbackBL;
    s->feedbackCL = feedbackCL; s->feedbackDL = feedbackDL;
    s->feedbackAR = feedbackAR; s->feedbackBR = feedbackBR;
    s->feedbackCR = feedbackCR; s->feedbackDR = feedbackDR;
    for (int n = 0; n < 12; ++n) {
        *counts[n] = (int)(ln[n].at - ln[n].base);
    }
    s->countM = countM;
    s->cycle = cycle;
    s->vibM = vibM;
    s->oldfpd = oldfpd;
    s->fpdL = fpdL;
    s->fpdR = fpdR;
}

static const uint32_t aw_Galactic_offsets_fast[] = {offsetof(aw_Galactic_fast_t, A), offsetof(aw_Galactic_fast_t, B), offsetof(aw_Galactic_fast_t, C), offsetof(aw_Galactic_fast_t, D), offsetof(aw_Galactic_fast_t, E)};

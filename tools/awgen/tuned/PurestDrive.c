// PurestDrive for the ESP32-S3 (plugin.h, AW_TUNED), in Q30 and Q31 fixed
// point: there the integer multiply-high beats the FPU, 2.9 % of a core
// against 3.5 % for the translated float loop. Upstream's loop, per side:
//
//     sine = sin(input)
//     apply = |previous + sine| / 2 * drive
//     output = input * (1 - apply) + sine * apply
//     previous = sine
//
// The input is int16, so it is exact in Q31, and every product keeps at
// least 29 fraction bits, about 2e-9: far inside the 1 LSB bar. The output
// blend is written input + apply * (sine - input), the same value in one
// multiply.
// Upstream's denormal guard adds noise near 1e-17 to a zero input; in Q30
// that rounds to zero, so it is left out, with its noise generators.
typedef struct {
    double aw_sample_rate;
    uint32_t aw_rand;
    int32_t previousSampleL;
    int32_t previousSampleR;
    float A;
    float B;
    float C;
    float D;
    float E;
} aw_PurestDrive_fast_t;

static void aw_PurestDrive_init_fast(void *aw_state, double aw_rate) {
    aw_PurestDrive_fast_t *aw_s = (aw_PurestDrive_fast_t *)aw_state;
    memset(aw_s, 0, sizeof(*aw_s));
    aw_s->aw_sample_rate = aw_rate;
    aw_s->aw_rand = AW_RAND_SEED;
}

static void aw_PurestDrive_process_fast(void *aw_state, int16_t *aw_out,
    const int16_t *aw_in, int32_t sampleFrames, uint32_t aw_channels) {
    aw_PurestDrive_fast_t *aw_s = (aw_PurestDrive_fast_t *)aw_state;
    int32_t previousL = aw_s->previousSampleL;                  // Q30
    int32_t previousR = aw_s->previousSampleR;
    const int32_t intensity = aw_q31_from_unit(aw_s->A);        // Q31
    while (--sampleFrames >= 0) {
        const int32_t inL = (int32_t)aw_in[0] << 16;            // Q31
        const int32_t inR = (int32_t)aw_in[aw_channels - 1] << 16;
        const int32_t sineL = aw_sin_q31(inL);                  // Q30
        const int32_t sineR = aw_sin_q31(inR);
        // |previous + sine| in Q30 is |previous + sine| / 2 in Q31.
        int32_t sumL = previousL + sineL;
        int32_t sumR = previousR + sineR;
        sumL = sumL < 0 ? -sumL : sumL;
        sumR = sumR < 0 ? -sumR : sumR;
        const int32_t applyL = aw_mulhi(sumL, intensity);       // Q30
        const int32_t applyR = aw_mulhi(sumR, intensity);
        // sine - input is under 0.16, so it holds Q31.
        const int32_t outL = (inL >> 1)                         // Q30
            + (aw_mulhi(applyL, (sineL << 1) - inL) << 1);
        const int32_t outR = (inR >> 1)
            + (aw_mulhi(applyR, (sineR << 1) - inR) << 1);
        previousL = sineL;
        previousR = sineR;
        AW_OUT_Q(aw_out, aw_channels, outL, outR, 30);
        aw_in += aw_channels;
        aw_out += aw_channels;
    }
    aw_s->previousSampleL = previousL;
    aw_s->previousSampleR = previousR;
}

static const uint32_t aw_PurestDrive_offsets_fast[] = {offsetof(aw_PurestDrive_fast_t, A)};

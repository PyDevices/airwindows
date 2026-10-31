// A stand-in for the VST2 SDK header, just enough to compile an Airwindows
// plug-in's constructor and processing on their own. Only the reference
// harness uses it.
// SPDX-License-Identifier: MIT
#pragma once
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#define __audioeffect__
typedef int32_t VstInt32;
typedef intptr_t VstIntPtr;
typedef void* audioMasterCallback;
enum { kVstMaxProgNameLen=24, kVstMaxParamStrLen=8, kVstMaxVendorStrLen=64,
       kVstMaxProductStrLen=64, kVstMaxEffectNameLen=32, kVstMaxLabelLen=64,
       kVstMaxShortLabelLen=8 };
typedef int VstPlugCategory;
enum { kPlugCategUnknown=0, kPlugCategEffect, kPlugCategSynth,
       kPlugCategAnalysis, kPlugCategMastering, kPlugCategSpacializer,
       kPlugCategRoomFx, kPlugSurroundFx, kPlugCategRestoration,
       kPlugCategOfflineProcess, kPlugCategShell, kPlugCategGenerator };
struct VstParameterProperties { float stepFloat, smallStepFloat, largeStepFloat;
  char label[64]; int32_t flags, minInteger, maxInteger, stepInteger,
  largeStepInteger; char shortLabel[8]; int16_t displayIndex, category,
  numParametersInCategory, reserved; char categoryLabel[24]; char future[16]; };
enum { kVstParameterIsSwitch = 1, kVstParameterUsesIntegerMinMax = 2,
       kVstParameterUsesFloatStep = 4, kVstParameterUsesIntStep = 8,
       kVstParameterSupportsDisplayIndex = 16,
       kVstParameterSupportsDisplayCategory = 32,
       kVstParameterCanRamp = 64 };
extern "C" double aw_harness_sr;
class AudioEffect {};
class AudioEffectX : public AudioEffect {
public:
  double sr = aw_harness_sr;
  AudioEffectX(audioMasterCallback, int, int) {}
  virtual ~AudioEffectX() {}
  double getSampleRate() { return sr; }
  void setNumInputs(int) {} void setNumOutputs(int) {}
  void setUniqueID(unsigned long) {}
  void canProcessReplacing() {} void canDoubleReplacing() {}
  void programsAreChunks(bool) {} void isSynth(bool = true) {}
  void noTail(bool = true) {} void setInitialDelay(int) {}
  void updateDisplay() {}
  void float2string(float v, char *t, int n) { snprintf(t, n, "%f", v); }
  void dB2string(float v, char *t, int n) { snprintf(t, n, "%f", v); }
  void int2string(int v, char *t, int n) { snprintf(t, n, "%d", v); }
};
static inline char* vst_strncpy(char* d, const char* s, int n) {
  strncpy(d, s, n); d[n] = 0; return d; }
static inline float vst_strtof(const char *s) { return (float)atof(s); }

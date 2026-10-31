// Forced into every upstream source the reference harness compiles: rand()
// becomes the generator the generated kernels use, so a plug-in that draws
// from it as it runs draws the same numbers on both sides.
// SPDX-License-Identifier: MIT
#pragma once
#include <stdlib.h>
#include <cstdlib>
extern "C" int aw_harness_rand(void);
extern "C" double aw_harness_sr;
#define rand aw_harness_rand

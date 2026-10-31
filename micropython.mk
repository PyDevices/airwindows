# MicroPython Make glue (unix, windows) for audioairwindows.
#
# This module builds beside audiodsp, never alone: it uses audiodsp's
# audiocore sample protocol and pump lock, and finds their headers through
# the include path audiodsp's own micropython.mk adds. Put both checkouts in
# one directory and point USER_C_MODULES at that directory.
# For CMake ports (esp32, rp2), see micropython.cmake.
#
# SPDX-License-Identifier: MIT

AW_MOD_DIR := $(USERMOD_DIR)
AW_SRC_DIR := $(AW_MOD_DIR)/src
AW_VERSION := $(shell cat $(AW_MOD_DIR)/VERSION 2>/dev/null || echo unknown)

# Which plug-ins this build carries: AIRWINDOWS_PLUGINS, a list of names,
# collections (Basic, Recommended, Latest), `default` or `all`, on the make
# command line or in the environment. The unix and windows ports carry them
# all unless told otherwise. src/airwindows/select.py reads the list.
AIRWINDOWS_PLUGINS ?= all
AW_PLUGINS := $(shell $(PYTHON) $(AW_SRC_DIR)/airwindows/select.py $(AW_SRC_DIR)/airwindows/selection.txt "$(AIRWINDOWS_PLUGINS)")
ifeq ($(AW_PLUGINS),)
$(error AIRWINDOWS_PLUGINS="$(AIRWINDOWS_PLUGINS)" chose no plug-in)
endif

# module.c first: see the note at the top of module.c.
SRC_USERMOD_C += $(AW_SRC_DIR)/audioairwindows/module.c
SRC_USERMOD_C += $(AW_SRC_DIR)/audioairwindows/types.c
SRC_USERMOD_C += $(AW_SRC_DIR)/audioairwindows/Airwindows.c
SRC_USERMOD_C += $(foreach p,$(AW_PLUGINS),$(AW_SRC_DIR)/airwindows/plugins/$(p).c)

CFLAGS_USERMOD += -I$(AW_SRC_DIR) -DAW_VERSION='"$(AW_VERSION)"'
CFLAGS_USERMOD += $(foreach p,$(AW_PLUGINS),-DAW_WITH_$(p)=1)

# audioairwindows.__revision__: which commit this firmware was built from,
# read from the checkout the build is compiling. "unknown" outside a git
# checkout; "-dirty" when it has uncommitted changes.
AW_REVISION := $(shell git -C $(AW_MOD_DIR) describe --tags --match 'v[0-9]*' --always --dirty --abbrev=7 2>/dev/null || echo unknown)
CFLAGS_USERMOD += -DAW_REVISION='"$(AW_REVISION)"'

# Make recompiles nothing when only a -D value changes, so module.o, which
# carries both strings, depends on a stamp rewritten only when they change.
# py.mk puts a module's objects under $(BUILD)/<module directory name>/.
AW_BUILD_STAMP := $(BUILD)/audioairwindows_build.stamp
$(shell mkdir -p $(BUILD) && echo '$(AW_VERSION) $(AW_REVISION)' > $(AW_BUILD_STAMP).new && \
    { cmp -s $(AW_BUILD_STAMP).new $(AW_BUILD_STAMP) && rm -f $(AW_BUILD_STAMP).new || mv -f $(AW_BUILD_STAMP).new $(AW_BUILD_STAMP); })
$(BUILD)/$(notdir $(AW_MOD_DIR))/src/audioairwindows/module.o: $(AW_BUILD_STAMP)

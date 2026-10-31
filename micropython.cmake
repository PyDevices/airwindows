# MicroPython CMake glue (esp32, rp2) for audioairwindows.
#
# This module builds beside audiodsp, never alone: it uses audiodsp's
# audiocore sample protocol and pump lock, whose headers reach these sources
# through audiodsp's usermod_mpaudio target. List both in USER_C_MODULES.
#
# SPDX-License-Identifier: MIT

set(AW_MOD_DIR ${CMAKE_CURRENT_LIST_DIR})
set(AW_SRC_DIR ${AW_MOD_DIR}/src)
file(STRINGS ${AW_MOD_DIR}/VERSION AW_VERSION LIMIT_COUNT 1)

add_library(usermod_airwindows INTERFACE)

# Which plug-ins this build carries: AIRWINDOWS_PLUGINS, a list of names,
# collections (Basic, Recommended, Latest), `default` or `all`, as a CMake
# variable (a board's mpconfigboard.cmake) or in the environment. A board
# build carries `default` unless told otherwise: Airwindows' Basic and
# Recommended lists. src/airwindows/select.py reads the list.
if(NOT DEFINED AIRWINDOWS_PLUGINS)
    if(DEFINED ENV{AIRWINDOWS_PLUGINS})
        set(AIRWINDOWS_PLUGINS "$ENV{AIRWINDOWS_PLUGINS}")
    else()
        set(AIRWINDOWS_PLUGINS default)
    endif()
endif()
if(NOT Python3_EXECUTABLE)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
endif()
execute_process(
    COMMAND ${Python3_EXECUTABLE} ${AW_SRC_DIR}/airwindows/select.py
        ${AW_SRC_DIR}/airwindows/selection.txt "${AIRWINDOWS_PLUGINS}"
    OUTPUT_VARIABLE AW_PLUGINS
    ERROR_VARIABLE AW_SELECT_ERROR
    RESULT_VARIABLE AW_SELECT_RESULT
    OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT AW_SELECT_RESULT EQUAL 0 OR AW_PLUGINS STREQUAL "")
    message(FATAL_ERROR "audioairwindows: ${AW_SELECT_ERROR}")
endif()
string(REPLACE "\n" ";" AW_PLUGINS "${AW_PLUGINS}")
list(LENGTH AW_PLUGINS AW_PLUGIN_COUNT)
message(STATUS "audioairwindows: ${AW_PLUGIN_COUNT} plug-ins")

# module.c first: see the note at the top of module.c.
target_sources(usermod_airwindows INTERFACE
    ${AW_SRC_DIR}/audioairwindows/module.c
    ${AW_SRC_DIR}/audioairwindows/types.c
    ${AW_SRC_DIR}/audioairwindows/Airwindows.c
)
foreach(AW_PLUGIN IN LISTS AW_PLUGINS)
    target_sources(usermod_airwindows INTERFACE
        ${AW_SRC_DIR}/airwindows/plugins/${AW_PLUGIN}.c)
    target_compile_definitions(usermod_airwindows INTERFACE
        AW_WITH_${AW_PLUGIN}=1)
    # The qstr scan reads the firmware target's own definitions, not an
    # INTERFACE library's, so it would see no plug-in without this.
    list(APPEND MICROPY_CPP_DEF_EXTRA AW_WITH_${AW_PLUGIN}=1)
endforeach()

target_include_directories(usermod_airwindows INTERFACE ${AW_SRC_DIR})

# No ESP32 does double precision or division in hardware, so its firmware
# carries only the single-precision fast variant of each kernel. Other ports
# carry only the reference. AIRWINDOWS_VARIANT (fast, ref) overrides it.
if(NOT DEFINED AIRWINDOWS_VARIANT)
    if(DEFINED ENV{AIRWINDOWS_VARIANT})
        set(AIRWINDOWS_VARIANT "$ENV{AIRWINDOWS_VARIANT}")
    elseif(IDF_TARGET)
        set(AIRWINDOWS_VARIANT fast)
    else()
        set(AIRWINDOWS_VARIANT ref)
    endif()
endif()
if(AIRWINDOWS_VARIANT STREQUAL "fast")
    target_compile_definitions(usermod_airwindows INTERFACE
        AW_FAST_DEFAULT=1 AW_BUILD_REF=0 AW_BUILD_FAST=1)
else()
    target_compile_definitions(usermod_airwindows INTERFACE
        AW_FAST_DEFAULT=0 AW_BUILD_REF=1 AW_BUILD_FAST=0)
endif()
target_compile_definitions(usermod_airwindows INTERFACE
    AW_VERSION="${AW_VERSION}")

# audioairwindows.__revision__: which commit this firmware was built from.
# revision.cmake writes it into a header on every build, and rewrites the
# header only when it changes, so an unchanged checkout recompiles nothing.
set(AW_GENHDR_DIR ${CMAKE_BINARY_DIR}/audioairwindows_genhdr)
set(AW_REVISION_COMMAND ${CMAKE_COMMAND}
    -DMOD_DIR=${AW_MOD_DIR} -DOUT=${AW_GENHDR_DIR}/audioairwindows_revision.h
    -P ${AW_SRC_DIR}/audioairwindows/revision.cmake)
execute_process(COMMAND ${AW_REVISION_COMMAND})
if(NOT TARGET audioairwindows_revision)
    add_custom_target(audioairwindows_revision
        COMMAND ${AW_REVISION_COMMAND}
        BYPRODUCTS ${AW_GENHDR_DIR}/audioairwindows_revision.h)
endif()
add_dependencies(usermod_airwindows audioairwindows_revision)
target_include_directories(usermod_airwindows INTERFACE ${AW_GENHDR_DIR})
target_compile_definitions(usermod_airwindows INTERFACE AW_REVISION_HEADER=1)

target_link_libraries(usermod INTERFACE usermod_airwindows)

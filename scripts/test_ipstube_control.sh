#!/usr/bin/env bash
set -euo pipefail

mkdir -p .pio/test-native

${CXX:-c++} \
  -std=c++17 \
  -Wall \
  -Wextra \
  -Werror \
  -Iinclude \
  tests/ipstube_control_tests.cpp \
  src/IPSTubeControlTypes.cpp \
  src/IPSTubeBmpValidator.cpp \
  -o .pio/test-native/ipstube_control_tests

.pio/test-native/ipstube_control_tests

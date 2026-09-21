#!/bin/bash -eu
# Build the fuzz targets for ClusterFuzzLite / OSS-Fuzz.
#
# The policy imports nothing from Sage, so a plain install is enough. If that
# ever stops being true the build fails here rather than the target silently
# fuzzing an import error.
cd "$SRC/sagemath-mcp"
python3 -m pip install --no-cache-dir .

for target in fuzz/fuzz_*.py; do
  name="$(basename "$target" .py)"
  compile_python_fuzzer "$target" --add-data "src/sagemath_mcp:sagemath_mcp"
done

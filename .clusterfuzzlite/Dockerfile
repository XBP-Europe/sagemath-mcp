# ClusterFuzzLite build image for the AST security policy.
#
# Only `security.py` and the generated artifacts it reads are fuzzed, so this
# installs the package without Sage: the policy is pure Python and decides
# everything before a worker exists. That keeps the image small enough for the
# per-PR budget, which a SageMath base image would not be.
FROM gcr.io/oss-fuzz-base/base-builder-python:v1

RUN apt-get update && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY . $SRC/sagemath-mcp
WORKDIR $SRC/sagemath-mcp
COPY .clusterfuzzlite/build.sh $SRC/build.sh

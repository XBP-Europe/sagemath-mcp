FROM sagemath/sagemath:10.9

WORKDIR /workspace

USER root

# Copy only what the wheel build needs -- pyproject, the readme it references,
# and the package. `COPY . /workspace` used to pull the whole repo (tests,
# external_docs, the 100 KB+ review file) into the image and bust this layer's
# cache on every edit to any of them. LICENSE rides along because it belongs in
# the image, though the build does not require it (license is declared inline).
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# Install the MCP server into Sage's Python environment
RUN sage -python -m pip install --upgrade pip && \
    sage -python -m pip install --no-cache-dir .

# Ensure runtime user owns the workspace.
RUN chown -R sage:sage /workspace

USER sage

EXPOSE 8314

ENTRYPOINT ["sage", "-python", "-m", "sagemath_mcp.server"]
# `--host 0.0.0.0` binds every interface INSIDE the container's own network
# namespace -- correct here, because who can reach the server is decided by how
# the port is published (the docs publish it on 127.0.0.1). It is not a bind on
# your host. The server has no authentication by default, so do not publish this
# port to a network without either putting an authenticating proxy in front or
# setting SAGEMATH_MCP_HTTP_AUTH_TOKEN=<secret> to require a bearer token (see
# SECURITY.md); the server logs a warning if it binds a non-loopback host with
# neither.
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8314"]

FROM sagemath/sagemath:latest

WORKDIR /workspace

USER root

# Copy project files
COPY . /workspace

# Install the MCP server into Sage's Python environment
RUN sage -python -m pip install --upgrade pip && \
    sage -python -m pip install --no-cache-dir .

# Ensure runtime user owns the workspace.
RUN chown -R sage:sage /workspace

USER sage

EXPOSE 31415

ENTRYPOINT ["sage", "-python", "-m", "sagemath_mcp.server"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "31415"]

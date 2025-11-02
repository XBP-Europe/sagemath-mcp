FROM sagemath/sagemath:latest

WORKDIR /workspace

# Copy project files
COPY . /workspace

# Install the MCP server into Sage's Python environment
RUN sage -python -m pip install --upgrade pip && \
    sage -python -m pip install --no-cache-dir .

EXPOSE 31415

ENTRYPOINT ["sage", "-python", "-m", "sagemath_mcp.server"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "31415"]

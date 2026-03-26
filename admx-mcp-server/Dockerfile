# ADMX MCP Server with mcpo proxy
FROM python:3.12-slim

WORKDIR /app

# Install mcpo proxy (runtime wrapper, not in pyproject.toml)
RUN pip install --no-cache-dir mcpo

# Copy and install project (pulls dependencies from pyproject.toml)
COPY pyproject.toml .
COPY server.py .
COPY app/ ./app/
RUN pip install --no-cache-dir .

COPY mcpo_config_docker.json ./mcpo_config.json

# Copy the ADMX dictionary (will be mounted as volume in production)
# COPY ms-admx-dictionary.json /data/

# Set environment variables
ENV ADMX_DB_PATH=/data/ms-admx-dictionary.json
ENV PYTHONUNBUFFERED=1

# Expose port for mcpo
EXPOSE 8000

# Health check (use python instead of curl to avoid adding a curl dependency)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs').read()" || exit 1

# Start mcpo with the MCP server
CMD ["mcpo", "--host", "0.0.0.0", "--port", "8000", "--config", "mcpo_config.json"]

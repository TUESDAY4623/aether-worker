FROM python:3.11-slim

LABEL maintainer="aether-dev"
LABEL description="Aether Controller - Distributed AI Platform"

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY aether/ ./aether/
COPY pyproject.toml .

# Create non-root user
RUN useradd -m -u 1000 aether && \
    chown -R aether:aether /app
USER aether

# Expose ports
EXPOSE 8000/tcp
EXPOSE 9000/udp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

# Run controller
CMD ["python", "-m", "aether.controller.app"]

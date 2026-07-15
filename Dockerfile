# --- Base image ---
# Slim variant keeps the image small; we only need Python + pip, no OS-level
# build tooling since our dependencies are all pure-Python or ship wheels.
FROM python:3.12-slim

# Prevents Python from writing .pyc files and buffering stdout/stderr -
# both make container logs behave correctly (visible immediately, not
# buffered until the process exits).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy and install dependencies first, separately from the app code.
# Docker caches each layer - if requirements.txt hasn't changed, this layer
# is reused instead of reinstalling every package on every code change.
# This alone can cut rebuild times from minutes to seconds during development.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the actual application code
COPY app/ ./app/
COPY static/ ./static/

# Document which port the app listens on (informational - doesn't actually
# publish it; that happens via `-p` at `docker run` or in docker-compose.yml)
EXPOSE 8000

# Run as a non-root user - a basic security practice. If the container is
# ever compromised, the attacker doesn't get root inside the container.
RUN useradd --create-home appuser
USER appuser

# No --reload here (that's a dev-only feature). Production containers
# should run a fixed, known version of the code - a restart just restarts
# the same version, it doesn't watch for file changes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so layer caches when only code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Then the application.
COPY scanner ./scanner
COPY data ./data

# Mount points for config + state. Docker users should bind-mount these
# so config.yaml and the dedupe DB survive container rebuilds:
#
#   docker run --rm \
#     -v $PWD/config.yaml:/app/config.yaml:ro \
#     -v $PWD/data:/app/data \
#     -v $PWD/logs:/app/logs \
#     -e DISCORD_WEBHOOK=$DISCORD_WEBHOOK \
#     ghcr.io/weaverjsdw-ux/pokemon-scanner:latest
VOLUME ["/app/data", "/app/logs"]

# Run as a non-root user — container best practice; also means the
# bind-mounted host files end up owned sensibly.
RUN useradd --create-home --uid 1000 scanner && \
    chown -R scanner:scanner /app
USER scanner

ENTRYPOINT ["python", "-m", "scanner"]

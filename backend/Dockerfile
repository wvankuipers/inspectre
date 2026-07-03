# ---- Stage 1: build deps with pip into a virtualenv -------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- Stage 2 (runtime): production image ------------------------------------
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        imagemagick \
        libpq5 \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY . .

RUN useradd --create-home --uid 1000 inspectre && chown -R inspectre:inspectre /app
USER inspectre

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["./scripts/start.sh"]


# ---- Stage 3 (dev): runtime + dev tooling for tests/lint --------------------
# Build with: docker compose --profile dev build api-dev
#       or:   docker build --target dev -t inspectre-api:dev .
FROM runtime AS dev

USER root
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
USER inspectre

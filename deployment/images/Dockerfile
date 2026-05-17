# syntax=docker/dockerfile:1.7

#######################
# 1) Python builder   #
#######################
FROM python:3.13-slim-bookworm AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

RUN --mount=type=cache,id=apt-builder,target=/var/cache/apt \
    --mount=type=cache,id=apt-lists-builder,target=/var/lib/apt \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY poiesis ./poiesis

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

###################
# 2) Runtime      #
###################
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN --mount=type=cache,id=apt-runtime,target=/var/cache/apt \
    --mount=type=cache,id=apt-lists-runtime,target=/var/lib/apt \
    apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 65532 poiesis \
    && useradd  --system --uid 65532 --gid 65532 --home /home/poiesis --create-home poiesis

COPY --from=builder /app /app

USER 65532:65532
WORKDIR /app

EXPOSE 8000
ENTRYPOINT ["poiesis"]

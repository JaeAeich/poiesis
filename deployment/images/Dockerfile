# Global ARGs
ARG PY_VERSION=3.13.0
ARG PY_IMAGE=alpine

###################################################
# Stage 1: Build application                      #
###################################################
FROM python:${PY_VERSION}-${PY_IMAGE} AS builder

WORKDIR /app

# Copy `uv` for package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy only files needed for dependency installation
COPY . .

# Install dependencies
RUN uv build

###################################################
# Stage 2: Install tini                           #
###################################################
FROM python:${PY_VERSION}-${PY_IMAGE} AS tini-installer

RUN apk add --no-cache tini

###################################################
# Stage 3: Final runtime image                    #
###################################################
FROM python:${PY_VERSION}-${PY_IMAGE} AS runtime

ARG PY_VERSION
ARG PY_IMAGE
ARG BUILD_DATE
ARG GIT_REVISION
ARG VERSION

LABEL Author="Javed Habib <jh4official@gmail.com>"

LABEL org.opencontainers.image.title="poiesis" \
    org.opencontainers.image.description="TES (Task Execution Service) implementation on Kubernetes" \
    org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.created="${BUILD_DATE}" \
    org.opencontainers.image.revision="${GIT_REVISION}" \
    org.opencontainers.image.licenses="Apache-2.0" \
    org.opencontainers.image.maintainers="Javed Habib <jh4official@gmail.com>" \
    org.opencontainers.image.authors="jaeaeich <jh4official@gmail.com>" \
    org.opencontainers.image.vendor="jaeaeich" \
    org.opencontainers.image.authors="Javed Habib <jh4official@gmail.com>" \
    org.opencontainers.image.url="https://github.com/jaeaeich/poiesis" \
    org.opencontainers.image.documentation="https://github.com/jaeaeich/poiesis" \
    org.opencontainers.image.source="https://github.com/jaeaeich/poiesis" \
    org.opencontainers.image.base.name="python:${PY_VERSION}-${PY_IMAGE}"

RUN addgroup -S poiesis && adduser -S -G poiesis -h /home/poiesis -s /bin/sh poiesis \
    && mkdir -p /app /home/poiesis/.cache \
    && chown -R poiesis:poiesis /app /home/poiesis/.cache

# Copy tini, uv, and the built package
COPY --from=tini-installer /sbin/tini /sbin/tini
COPY --from=builder /app/dist/*.whl /tmp/
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN uv pip install --system --no-cache /tmp/*.whl && rm /tmp/*.whl

WORKDIR /app
USER poiesis

ENTRYPOINT ["/sbin/tini", "--"]

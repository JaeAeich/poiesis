# Global ARGs
ARG PY_VERSION=3.13.0
ARG PY_IMAGE=slim

###################################################
# Stage 1: Get poetry                             #
###################################################
FROM python:${PY_VERSION}-${PY_IMAGE} AS poetry

ARG PY_VERSION
ARG PY_IMAGE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

###################################################
# Stage 2: Build dependencies                     #
###################################################
FROM poetry AS builder

WORKDIR /app

COPY . .

RUN poetry build

###################################################
# Stage 3: Final runtime image                    #
###################################################
FROM python:${PY_VERSION}-${PY_IMAGE} AS runtime

ARG PY_VERSION
ARG PY_IMAGE
ARG BUILD_DATE
ARG GIT_REVISION
ARG VERSION

LABEL Author="Javed Habib <javed@example.com>"

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

RUN groupadd -r poises && useradd -r -g poises -d /home/poises -m poises \
    && mkdir -p /app /home/poises/.cache \
    && chown -R poises:poises /app /home/poises/.cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

WORKDIR /app
USER poises

ENTRYPOINT ["/usr/bin/tini", "--"]

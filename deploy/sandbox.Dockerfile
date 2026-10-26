FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bash ca-certificates libatomic1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/ /usr/local/
COPY --from=node /opt/ /opt/

WORKDIR /workspace

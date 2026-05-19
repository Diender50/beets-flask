ARG NODE_VERSION=22.12.0
FROM node:${NODE_VERSION}-alpine3.20 AS node_runtime

FROM python:3.11-alpine3.20 AS base

FROM base AS deps

RUN addgroup -g 1000 beetle && \
    adduser -D -u 1000 -G beetle beetle

ENV HOSTNAME="beets-container"
ENV EDITOR="vi"

# map beets directory and our configs to /config
RUN mkdir -p /config/beets \
    && mkdir -p /config/beets-flask \
    && mkdir -p /logs \
    && chown -R beetle:beetle /config \
    && chown -R beetle:beetle /logs

ENV BEETSDIR="/config/beets"
ENV BEETSFLASKDIR="/config/beets-flask"
ENV BEETSFLASKLOG="/logs/beets-flask.log"

# our default folders they should not be used in production
RUN mkdir -p /music/inbox \
    && mkdir -p /music/imported \
    && chown -R beetle:beetle /music

# dependencies (Combinaison de l'update et du add dans le même montage de cache)
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --update \
    imagemagick \
    redis  \
    bash \
    tmux \
    shadow \
    git \
    ffmpeg \
    curl \
    xz

# Node setup
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN printf '#!/bin/sh\nexec node /usr/local/lib/node_modules/npm/bin/npm-cli.js "$@"\n' \
        > /usr/local/bin/npm \
    && printf '#!/bin/sh\nexec node /usr/local/lib/node_modules/npm/bin/npx-cli.js "$@"\n' \
        > /usr/local/bin/npx \
    && chmod +x /usr/local/bin/npm /usr/local/bin/npx

RUN node --version && npm --version

# Install backend dependencies
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
ENV UV_PROJECT_ENVIRONMENT="/usr/local/"

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir uv

WORKDIR /repo/backend

# OPTIMISATION : On copie uniquement les fichiers nécessaires à l'installation des dépendances.
# On inclut uv.lock* au cas où tu en génères un, c'est une bonne pratique.
COPY ./backend/pyproject.toml ./backend/uv.lock* /repo/backend/

# OPTIMISATION : On crée un README factice juste pour satisfaire uv s'il en a besoin, 
# sans casser le cache si le vrai README change.
RUN touch /repo/README.md && uv sync --no-install-project

# OPTIMISATION : On extrait la version maintenant (ça ne sera rejoué que si pyproject.toml change)
RUN mkdir -p /version \
    && python -c "import tomllib; print(tomllib.load(open('/repo/backend/pyproject.toml', 'rb'))['project']['version'])" > /version/backend.txt

# OPTIMISATION : Maintenant on copie le reste du code source
COPY ./README.md /repo/
COPY ./backend/beets_flask/ /repo/backend/beets_flask/
COPY ./backend/*.py /repo/backend/

RUN uv sync

# ------------------------------------------------------------------------------------ #
#                                      Development                                     #
# ------------------------------------------------------------------------------------ #

FROM deps AS dev

RUN npm install -g pnpm
RUN pnpm config set store-dir /repo/frontend/.pnpm-store

WORKDIR /repo
# Copie seulement des fichiers de lock
COPY ./frontend/package.json ./frontend/pnpm-lock.yaml /repo/frontend/

WORKDIR /repo/frontend

RUN mkdir -p /version \
    && python -c "import json; print(json.load(open('/repo/frontend/package.json'))['version'])" \
    > /version/frontend.txt

ENV IB_SERVER_CONFIG="dev_docker"

WORKDIR /repo
USER root
ENTRYPOINT [ \
    "/bin/sh", "-c", \
    "for f in /repo/docker/entrypoints/*.sh; do [ -f \"$f\" ] && sed -i 's/\r$//' \"$f\"; done && \
    /bin/bash /repo/docker/entrypoints/entrypoint_fix_permissions.sh && \
    su beetle -c '/bin/bash /repo/docker/entrypoints/entrypoint_dev.sh'" \
    ]

# ------------------------------------------------------------------------------------ #
#                                        Build                                         #
# ------------------------------------------------------------------------------------ #

FROM deps AS build

RUN npm install -g pnpm
RUN pnpm config set store-dir /repo/frontend/.pnpm-store

WORKDIR /repo/frontend

# OPTIMISATION MAJEURE : On copie D'ABORD les fichiers de définition de paquets
COPY ./frontend/package.json ./frontend/pnpm-lock.yaml /repo/frontend/

RUN mkdir -p /version \
    && python -c "import json; print(json.load(open('/repo/frontend/package.json'))['version'])" \
    > /version/frontend.txt

# OPTIMISATION : On installe les dépendances MAINTENANT (en restaurant ton cache pnpm)
RUN --mount=type=cache,id=pnpm-store,target=/repo/frontend/.pnpm-store \
    pnpm install --frozen-lockfile

# OPTIMISATION : On copie le code source SEULEMENT APRÈS l'installation
COPY ./frontend /repo/frontend/
RUN chown -R beetle:beetle /repo/frontend

USER beetle
RUN pnpm run build

# ------------------------------------------------------------------------------------ #
#                                      Production                                      #
# ------------------------------------------------------------------------------------ #

FROM deps AS prod

ENV IB_SERVER_CONFIG="prod"

WORKDIR /repo
COPY --from=build /repo/frontend/dist /repo/frontend/dist
COPY --from=build /version /version
COPY docker/entrypoints .
RUN chown -R beetle:beetle /repo

USER root

ENTRYPOINT [ \
    "/bin/sh", "-c", \
    "/repo/entrypoint_fix_permissions.sh && \
    /repo/entrypoint_user_scripts.sh && \
    su beetle -c /repo/entrypoint.sh" \
    ]
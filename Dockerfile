FROM node:24-bookworm-slim AS client
WORKDIR /client
COPY apps/webapp/frontend/package.json apps/webapp/frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY apps/webapp/frontend/build.mjs ./
COPY apps/webapp/frontend/src ./src
COPY apps/webapp/frontend/public ./public
RUN CLIENT_OUT=/out npm run build

# OSRM and Python live in the SAME hardened Nära Hem container.
# The -debian variant supplies apt and a compatible system Python.
FROM ghcr.io/project-osrm/osrm-backend:26.11.0-debian
LABEL org.opencontainers.image.description="Nära Hem server with private road matching"
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/narahem-venv
ENV PATH="/opt/narahem-venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/webapp/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data /exports && chown 10001:10001 /data /exports && chmod 0700 /data && chmod 0755 /exports \
    && command -v osrm-extract && command -v osrm-partition \
    && command -v osrm-customize && command -v osrm-routed
COPY apps/webapp/backend/manage.py /app/manage.py
COPY apps/webapp/backend/narahem /app/narahem
RUN python manage.py diagnostics --help >/dev/null
# Official images get the project's push relay URLs/tokens from GitHub
# secrets (a BuildKit secret, so not in build args or history). Forks and
# local builds have none; NARAHEM_*_RELAY_* environment variables override.
# A secret is not part of the build cache key, so CI passes a fingerprint of the
# relay addresses (not secret) here: the step below re-runs whenever they change.
ARG NARAHEM_RELAY_DEFAULTS_SHA=
RUN --mount=type=secret,id=relay_defaults,required=false \
    if [ -s /run/secrets/relay_defaults ]; then install -m 0444 /run/secrets/relay_defaults /app/narahem/relay-defaults.json; fi
COPY apps/webapp/backend/entrypoint.sh /usr/local/bin/narahem-entrypoint
RUN chmod 0755 /usr/local/bin/narahem-entrypoint
# The whole browser app (page, styles, scripts, icons) comes from the client build stage.
COPY --from=client /out /app/static
# Shown to signed-in users ("Server dev build 591 · c399c6c"). Set late so the
# build cache above is unaffected; local builds report the "local" channel.
ARG NARAHEM_BUILD_CHANNEL=local
ARG NARAHEM_BUILD_NUMBER=
ARG NARAHEM_BUILD_COMMIT=
ARG NARAHEM_BUILD_UTC=
ENV NARAHEM_BUILD_CHANNEL=$NARAHEM_BUILD_CHANNEL NARAHEM_BUILD_NUMBER=$NARAHEM_BUILD_NUMBER \
    NARAHEM_BUILD_COMMIT=$NARAHEM_BUILD_COMMIT NARAHEM_BUILD_UTC=$NARAHEM_BUILD_UTC
# Temporary root at startup only, to repair root-owned bind mount directory.
# The entrypoint immediately drops to UID/GID 10001 before running Python.
USER 0:0
ENTRYPOINT ["/usr/local/bin/narahem-entrypoint"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"]
CMD ["uvicorn", "narahem.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "16"]

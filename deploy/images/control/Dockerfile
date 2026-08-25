FROM python:3.12-slim@sha256:646fb0bca3dd3ea1bcc6feb72c17ed16eed6e10cffc732fcc1478bd3e7f02d7b AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md requirements.lock ./
COPY media_bridge ./media_bridge
COPY media_bridge_adapters ./media_bridge_adapters
COPY media_bridge_control ./media_bridge_control
COPY media_bridge_gateway ./media_bridge_gateway
RUN python -m venv /opt/media-bridge \
    && /opt/media-bridge/bin/pip install --no-cache-dir -r requirements.lock \
    && /opt/media-bridge/bin/pip wheel --no-cache-dir --no-deps --wheel-dir /tmp/wheels . \
    && /opt/media-bridge/bin/pip install --no-cache-dir \
       /tmp/wheels/nonvision_media_bridge-0.1.0-py3-none-any.whl

FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web ./
RUN npm run build

FROM python:3.12-slim@sha256:646fb0bca3dd3ea1bcc6feb72c17ed16eed6e10cffc732fcc1478bd3e7f02d7b

ENV PATH=/opt/media-bridge/bin:$PATH \
    PYTHONPATH=/opt/media-bridge \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 media-bridge \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin media-bridge \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/media-bridge/snapshots
COPY --from=build --chown=10001:10001 /opt/media-bridge /opt/media-bridge
COPY --chown=10001:10001 deploy/health /opt/media-bridge/health
COPY --chown=10001:10001 deploy /opt/media-bridge/deploy
COPY --chown=10001:10001 migrations /opt/media-bridge/migrations
COPY --from=web-build --chown=10001:10001 /web/dist /opt/media-bridge/web
WORKDIR /srv/media-bridge
USER 10001:10001
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
  CMD ["python", "/opt/media-bridge/health/control_plane.py"]
CMD ["media-bridge-control"]

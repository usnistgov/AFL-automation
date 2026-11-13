FROM python:3.12-slim

ARG TILED_VERSION=0.2.4

RUN pip install --no-cache-dir \
        "tiled[server]==${TILED_VERSION}" \
        aiosqlite \
    && mkdir -p /catalog /data

COPY config.yml.template /opt/tiled/config.yml.template
COPY entrypoint.sh /usr/local/bin/tiled-entrypoint
RUN chmod 0444 /opt/tiled/config.yml.template \
    && chmod 0555 /usr/local/bin/tiled-entrypoint

ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/tiled-entrypoint"]

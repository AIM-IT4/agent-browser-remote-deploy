FROM node:22-slim

ARG AGENT_BROWSER_VERSION=latest
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv ca-certificates tini \
        fonts-liberation fonts-noto-core fonts-noto-color-emoji \
    && npm install -g agent-browser@${AGENT_BROWSER_VERSION} \
    && npm cache clean --force

RUN useradd -m -d /home/appuser appuser \
    && HOME=/home/appuser agent-browser install --with-deps \
    && chown -R appuser:appuser /home/appuser \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY runtime.tgz.b64 /tmp/runtime.tgz.b64

RUN python3 - <<'PY'
import base64, pathlib, tarfile
src=pathlib.Path('/tmp/runtime.tgz.b64')
tgz=pathlib.Path('/tmp/runtime.tgz')
tgz.write_bytes(base64.b64decode(src.read_text()))
with tarfile.open(tgz, 'r:gz') as t:
    t.extractall('/app')
PY

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir /app \
    && rm -f /tmp/runtime.tgz /tmp/runtime.tgz.b64

ENV PATH="/opt/venv/bin:${PATH}" \
    PORT=8001 \
    MALLOC_ARENA_MAX=2 \
    MEMORY_LIMIT_MB=1024

USER appuser
EXPOSE 8001
ENTRYPOINT ["tini", "--"]
CMD ["agent-browser-remote"]

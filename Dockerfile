FROM node:24-bookworm-slim

ARG AGENT_BROWSER_VERSION=latest
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv ca-certificates tini \
        libxcb-shm0 libx11-xcb1 libx11-6 libxcb1 libxext6 libxrandr2 \
        libxcomposite1 libxcursor1 libxdamage1 libxfixes3 libxi6 \
        libgtk-3-0 libpangocairo-1.0-0 libpango-1.0-0 libatk1.0-0 \
        libcairo-gobject2 libcairo2 libgdk-pixbuf-2.0-0 libxrender1 \
        libasound2 libfreetype6 libfontconfig1 libdbus-1-3 libnss3 \
        libnss3-tools libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
        libatspi2.0-0 libcups2 libxshmfence1 libgbm1 \
        fonts-noto-color-emoji fonts-noto-cjk fonts-freefont-ttf fonts-liberation \
    && npm install -g agent-browser@${AGENT_BROWSER_VERSION} \
    && useradd -m -d /home/appuser appuser \
    && HOME=/home/appuser agent-browser install \
    && chown -R appuser:appuser /home/appuser \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY agent_browser_remote /app/agent_browser_remote

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir /app

ENV PATH="/opt/venv/bin:${PATH}" \
    PORT=8001 \
    MALLOC_ARENA_MAX=2 \
    MEMORY_LIMIT_MB=900

USER appuser
EXPOSE 8001
ENTRYPOINT ["tini", "--"]
CMD ["agent-browser-remote"]

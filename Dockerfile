FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV NODE_VERSION=22
ENV APP_HOME=/app
ENV BACKEND_PORT=8005
ENV FRONTEND_PORT=3005
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PATH="/opt/vidmuse/ui_dev/node_modules/.bin:${PATH}"

WORKDIR /app

RUN set -eux; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        build-essential \
        pkg-config \
        xz-utils \
    && node_arch="$(dpkg --print-architecture)" \
    && case "$node_arch" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        *) echo "Unsupported architecture: $node_arch" >&2; exit 1 ;; \
    esac \
    && node_major="${NODE_VERSION%%.*}" \
    && node_file="$(curl -fsSL "https://npmmirror.com/mirrors/node/latest-v${node_major}.x/SHASUMS256.txt" | awk -v arch="$node_arch" '$2 ~ ("node-v.*-linux-" arch "\\.tar\\.xz$") {print $2; exit}')" \
    && node_version="$(echo "$node_file" | sed 's|node-v||; s|-linux-.*||')" \
    && curl -fsSLO "https://npmmirror.com/mirrors/node/v${node_version}/node-v${node_version}-linux-${node_arch}.tar.xz" \
    && tar -xJf "node-v${node_version}-linux-${node_arch}.tar.xz" -C /usr/local --strip-components=1 \
    && rm "node-v${node_version}-linux-${node_arch}.tar.xz" \
    && npm config set registry https://registry.npmmirror.com \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/backend-requirements.txt

COPY ui_dev/package.json ui_dev/package-lock.json /opt/vidmuse/ui_dev/
WORKDIR /opt/vidmuse/ui_dev
RUN npm ci

WORKDIR /app
COPY scripts/docker-entrypoint.sh /usr/local/bin/vidmuse-entrypoint.sh
RUN chmod +x /usr/local/bin/vidmuse-entrypoint.sh

EXPOSE 8005
EXPOSE 3005

CMD ["/usr/local/bin/vidmuse-entrypoint.sh"]

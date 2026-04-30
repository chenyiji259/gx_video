FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/backend
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV NODE_VERSION=22
ENV PATH="/opt/vidmuse/frontend/node_modules/.bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/backend-requirements.txt

COPY frontend/package.json frontend/package-lock.json /opt/vidmuse/frontend/
WORKDIR /opt/vidmuse/frontend
RUN npm ci

WORKDIR /app

EXPOSE 8000
EXPOSE 3000

CMD ["bash"]

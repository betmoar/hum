# Stage 1: build frontend
FROM node:20-alpine AS fe
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# deno: yt-dlp's JavaScript runtime for YouTube's signature/n challenges
# Static binary, copied in below.
FROM denoland/deno:bin-2.9.7 AS deno

# Stage 2: python + built frontend
FROM python:3.11-slim
COPY --from=deno /deno /usr/local/bin/deno
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir -e .

# Copy built frontend from stage 1
COPY --from=fe /fe/dist ./frontend/dist

# Run as a non-root user: the app needs no privileges, and a compromise of the
# yt-dlp/deno challenge-solving path shouldn't hand out container root.
# --create-home: yt-dlp writes its cache under ~/.cache/yt-dlp.
RUN useradd --create-home --uid 1000 hum
USER hum

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    LOG_LEVEL=INFO

# Documents the default; does not enforce it — actual bind port follows $PORT (see ENV above).
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD sh -c 'curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1'

# "hum" is the console script from pyproject.toml [project.scripts]; it calls
# app.main:main(), which is the only place that reads settings.host/settings.port
# (HOST/PORT env vars). If that entry point is ever renamed, this breaks silently.
CMD ["hum"]

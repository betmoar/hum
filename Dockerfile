# Stage 1: build frontend
FROM node:20-alpine AS fe
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python + built frontend
FROM python:3.11-slim
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
# pytubefix/Node cipher path shouldn't hand out container root.
# pytubefix writes its token cache to site-packages/pytubefix/__cache__ when
# oauth/po_token are enabled (the usual mitigation when YouTube starts
# blocking) — pre-create it writable so that switch doesn't crash at runtime.
RUN useradd --create-home --uid 1000 hum \
    && mkdir -p "$(python -c 'import pytubefix, pathlib; print(pathlib.Path(pytubefix.__file__).parent / "__cache__")')" \
    && chown -R hum:hum "$(python -c 'import pytubefix, pathlib; print(pathlib.Path(pytubefix.__file__).parent / "__cache__")')"
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

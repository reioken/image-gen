# Web backend for Product Image Batch.
# Build:  docker build -t product-image-batch-web .
# Run:    docker run -p 8000:8000 \
#           -e WEB_APP_PASSWORD=changeme -e WEB_APP_SECRET=$(openssl rand -hex 32) \
#           -e OPENAI_API_KEY=sk-... -e FAL_KEY=... \
#           product-image-batch-web
#
# Works on any Python host (Render, Railway, Fly.io, a VPS). Cloudflare then
# points a DNS record (e.g. api.dennisbf.design) at this service. See
# docs/WEB_DEPLOY.md.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY requirements.txt requirements-web.txt ./
RUN pip install -r requirements.txt -r requirements-web.txt

# App code.
COPY product_image_batch ./product_image_batch
COPY web ./web
COPY config ./config

# Generated images live here (mount a volume if you want persistence).
RUN mkdir -p /app/outputs

EXPOSE 8000

# WEB_APP_PASSWORD must be provided at runtime or the server refuses to start.
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000"]

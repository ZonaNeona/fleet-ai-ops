# API and worker share one image; docker-compose picks the command.
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed FLEET_ENV=/dev/null FLEET_INTEGRATIONS_ENV=/dev/null
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpangoft2-1.0-0 fonts-dejavu-core curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# The embedding model is read from the local cache only (app/embed_worker.py), so it is baked into the image.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/fastembed')"
COPY alembic.ini ./
COPY migrations migrations
COPY app app
COPY scripts scripts
COPY public public
COPY n8n n8n
COPY infra infra
RUN useradd --system --uid 10001 fleet && mkdir -p /data/files && chown -R fleet /data
USER fleet
EXPOSE 3008
CMD ["sh", "infra/docker/api.sh"]

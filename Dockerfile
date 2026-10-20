# QueryDoc AI — single-container image (React build served by FastAPI).
# Runs on any CPU host (x86-64 or ARM64), e.g. an Oracle Cloud Always Free VM (deploy/oracle/):
#   docker build -t querydoc-ai . && docker run -p 7860:7860 -v querydoc-data:/home/user/data querydoc-ai
# Author: Raahul Sallagunta

# ---- 1. frontend build ------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build

# ---- 2. runtime ---------------------------------------------------------------
FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*
# Non-root user (uid 1000, also what Hugging Face Spaces expect).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface
WORKDIR /home/user/app

# CPU-only PyTorch (the default wheel bundles ~2 GB of CUDA libraries we cannot use).
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu
COPY --chown=user backend/pyproject.toml backend/
COPY --chown=user README.md backend/README.md
COPY --chown=user backend/app backend/app
COPY --chown=user backend/querydoc backend/querydoc
COPY --chown=user backend/alembic backend/alembic
COPY --chown=user backend/alembic.ini backend/alembic.ini
RUN pip install --no-cache-dir --user ./backend

# Bake the models into the image so a cold start does not download ~3.5 GB.
RUN python -c "from huggingface_hub import snapshot_download as d; \
[d(m) for m in ('sentence-transformers/all-MiniLM-L6-v2', 'cross-encoder/ms-marco-MiniLM-L-6-v2', 'Qwen/Qwen2.5-1.5B-Instruct')]"

COPY --chown=user --from=web /web/dist frontend/dist
COPY --chown=user results results
COPY --chown=user LICENSE THIRD_PARTY_NOTICES.md ./

# Public multi-user configuration. Engine settings use QUERYDOC_* as well.
ENV QUERYDOC_AUTH_ENABLED=true \
    QUERYDOC_COOKIE_SECURE=true \
    QUERYDOC_COOKIE_SAMESITE=lax \
    QUERYDOC_DATA_DIR=/home/user/data \
    QUERYDOC_FRONTEND_DIST=/home/user/app/frontend/dist \
    QUERYDOC_RESULTS_DIR=/home/user/app/results \
    QUERYDOC_LLM_DEVICE=cpu \
    QUERYDOC_RERANKER_DEVICE=cpu \
    QUERYDOC_TORCH_THREADS=2 \
    QUERYDOC_ENABLE_OCR=true \
    QUERYDOC_MAX_UPLOAD_MB=20 \
    QUERYDOC_MAX_PAGES=400 \
    QUERYDOC_STREAM_TIMEOUT_S=600 \
    QUERYDOC_GENERATION_TIMEOUT_S=300 \
    QUERYDOC_MAX_GENERATION_QUEUE=4 \
    HF_HUB_OFFLINE=0

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "7860", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

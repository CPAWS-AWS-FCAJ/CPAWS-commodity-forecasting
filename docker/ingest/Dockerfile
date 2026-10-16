# Image for the ingest Lambda (draft for review by Tien; the official infra is CDK).
# Build from the repo root:
#   docker buildx build --platform linux/amd64 --provenance=false \
#     -f docker/ingest/Dockerfile -t cpaws-ingest:dev .
#
# Base image: public.ecr.aws/lambda/python:3.12 (Amazon Linux 2023, glibc 2.34).
# Not 3.11: the 3.11 base runs Amazon Linux 2 (glibc 2.26) and the pinned numpy==2.4.6 /
# pandas / pyarrow wheels need glibc >= 2.28, so pip cannot install them there.
# The tag "3.12" moves when AWS patches the base, so the digest is pinned.
# Pinned 2026-10-17 from tag public.ecr.aws/lambda/python:3.12 (multi-arch index digest).
# To update: see "Cập nhật base image" in docs/handoff/ingest-lambda.md.
FROM public.ecr.aws/lambda/python:3.12@sha256:3856536f53e945debf4c90d0ff301cbaa837c07a4ab9b0e2c102c6e54ceb9762

# Only the ingest dependencies (no torch, EMD-signal, scikit-learn, statsmodels).
COPY requirements-ingest.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-ingest.txt

# Only the code the handler needs: src/__init__.py and src/data/ (no data/, tests/, .env).
COPY src/__init__.py ${LAMBDA_TASK_ROOT}/src/__init__.py
COPY src/data/ ${LAMBDA_TASK_ROOT}/src/data/

# yfinance writes its cache to /tmp inside Lambda (see src/data/lambda_ingest.py).
ENV YF_CACHE_DIR=/tmp/yfinance-cache

CMD ["src.data.lambda_ingest.handler"]

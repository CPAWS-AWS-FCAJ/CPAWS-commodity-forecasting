# Image for the predict Lambda (draft for review by Tien; the official infra is CDK).
# Build from the repo root:
#   docker buildx build --platform linux/amd64 --provenance=false \
#     -f docker/predict/Dockerfile -t cpaws-predict:dev .
#
# Needs BuildKit (docker buildx, or DOCKER_BUILDKIT=1): the build context is filtered by
# docker/predict/Dockerfile.dockerignore. The legacy builder ignores that file and falls back to
# the root .dockerignore, which only lets the ingest files through, so the COPY of src/features/
# and src/forecast/ below would fail.
#
# Base image: same pinned digest as docker/ingest/Dockerfile (python:3.12, Amazon Linux 2023).
# To update: see "Cập nhật base image" in docs/handoff/ingest-lambda.md and change both files.
FROM public.ecr.aws/lambda/python:3.12@sha256:3856536f53e945debf4c90d0ff301cbaa837c07a4ab9b0e2c102c6e54ceb9762

# Only the predict dependencies (NumPy inference: no torch, EMD-signal, scipy, yfinance, requests).
COPY requirements-predict.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-predict.txt

# Only the code the handler needs (no data/, tests/, .env). Modules in these folders that need
# other libraries (src/data/sources, src/forecast/decomposition, ...) are copied but never imported.
COPY src/__init__.py ${LAMBDA_TASK_ROOT}/src/__init__.py
COPY src/data/ ${LAMBDA_TASK_ROOT}/src/data/
COPY src/features/ ${LAMBDA_TASK_ROOT}/src/features/
COPY src/forecast/ ${LAMBDA_TASK_ROOT}/src/forecast/

# Environment set by CDK: LAKE_BUCKET, LAKE_PREFIX (optional), FORECASTS_TABLE, MODEL_VERSION,
# CPAWS_ENV. Model artifacts are downloaded to /tmp (see src/forecast/predict.py).
CMD ["src.forecast.lambda_predict.handler"]

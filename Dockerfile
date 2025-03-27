# syntax=docker/dockerfile:1.14.0
FROM python:3.11-slim-bullseye AS python-base

ENV HOME=/home/user
WORKDIR $HOME
RUN apt-get update && apt-get install -y curl

RUN curl -LsSf https://astral.sh/uv/0.6.7/install.sh | sh
ENV PATH="$HOME/.local/bin:$PATH"
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

FROM python-base AS worker-cpu

ARG dbmate_arch
WORKDIR $HOME/src/app
RUN curl -fsSL -o /usr/local/bin/dbmate https://github.com/amacneil/dbmate/releases/download/v2.19.0/dbmate-linux-${dbmate_arch} \
    && chmod +x /usr/local/bin/dbmate
# TODO: add more languages here
RUN apt-get install -y tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-spa \
    tesseract-ocr-lat \
    tesseract-ocr-jpn \
    libtesseract-dev \
    libleptonica-dev \
    pkg-config
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata
# We skip opencv since we already depend on opencv-python-headless which is the lib we need to use
# Install deps first to optimize layer cache
RUN --mount=type=cache,target=~/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync -v --frozen --no-editable --no-sources --no-install-project --no-install-package opencv-python --extra docling
RUN uv run --no-sync docling-tools models download -o ~/.cache/docling/models
# Then copy code
ADD uv.lock pyproject.toml README.md ./
ADD extract_python ./extract_python/
# Then install service
RUN uv sync -v --frozen --no-editable --no-sources --no-install-package opencv-python --extra docling

RUN rm -rf ~/.cache/pip $(uv cache dir)

ENTRYPOINT ["uv", "run", "--no-sync", "icij-worker", "workers", "start", "-g", "cpu", "extract_python.app:app"]

FROM icij/task-service:icij-worker-0.17.21 AS http-service
ADD uv.lock pyproject.toml README.md ./extract-python/
ADD extract_python ./extract-python/extract_python/
RUN uv pip install -e ./extract-python

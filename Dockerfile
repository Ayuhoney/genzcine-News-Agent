# syntax=docker/dockerfile:1.6
#
# Production image: LiveKit + voice agent + Kokoro TTS (API-only; phone clients connect).
#
# Build args:
#   --build-arg LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda  (for GPU)
#   --build-arg PYTHON_BASE=python:3.11-slim                        (or nvidia/cuda...)

ARG LLAMA_IMAGE=ghcr.io/ggml-org/llama.cpp:server
ARG LIVEKIT_IMAGE=livekit/livekit-server:latest
ARG PYTHON_BASE=python:3.11-slim

# ---------------- binary sources ----------------
FROM ${LLAMA_IMAGE} AS llama-bin
FROM ${LIVEKIT_IMAGE} AS livekit-bin

# ---------------- runtime ----------------
FROM ${PYTHON_BASE} AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTORCH_ENABLE_MPS_FALLBACK=1 \
    HF_HOME=/models \
    XDG_CACHE_HOME=/models

# System libs needed by the inference stack and the binaries
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        espeak-ng \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps via uv for speed and a reproducible env
RUN pip install --no-cache-dir uv

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

# Copy ONLY dependency metadata here — the heavy install layer below then stays
# cached across source-code changes (code-only rebuilds: ~15 min -> seconds).
COPY pyproject.toml ./

# Resolve + install dependencies WITHOUT the project itself, in a single
# resolution pass (torch via explicit index for CPU/CUDA selection).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip compile pyproject.toml --extra ml -o /tmp/requirements.txt \
        --index-strategy unsafe-best-match --extra-index-url ${TORCH_INDEX_URL} && \
    uv pip install --system --index-strategy unsafe-best-match \
        --extra-index-url ${TORCH_INDEX_URL} -r /tmp/requirements.txt

# Pre-bake the spacy English G2P model (misaki/kokoro needs it) so the TTS
# server never downloads it at runtime — also cached independently of code.
RUN python -m spacy download en_core_web_sm || true

# Now copy the source and install just the package itself (fast, no deps)
COPY local_voice_ai ./local_voice_ai
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps .

COPY --from=llama-bin /app/ /usr/local/lib/llama/
RUN ln -s /usr/local/lib/llama/llama-server /usr/local/bin/llama-server \
    && echo /usr/local/lib/llama > /etc/ld.so.conf.d/llama.conf \
    && ldconfig
COPY --from=livekit-bin /livekit-server /usr/local/bin/livekit-server

# Pre-download VAD + turn detector weights so cold start is faster
RUN python -m local_voice_ai.agent download-files || true

EXPOSE 8080 7880 7881
VOLUME ["/models"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "local_voice_ai", "serve"]

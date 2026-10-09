#!/usr/bin/env bash
# Serve a local Qwen3-VL for shopper extraction via OpenAI-compatible API.
# AWQ 4-bit weights (~5.5GB) leave ample KV cache on the 16GB RTX 5070 Ti,
# unlike the 17GB fp16 checkpoint which starves the KV cache.
set -e
cd "$(dirname "$0")"
MODEL="${VL_MODEL:-cpatonn/Qwen3-VL-8B-Instruct-AWQ-4bit}"
PORT="${VL_PORT:-8100}"
exec .venv/bin/python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --port "$PORT" \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.82 \
  --limit-mm-per-prompt '{"image":1}' \
  --trust-remote-code

"""Bounded local inference subprocess, releases ONNX memory on exit."""

import json, os, sys
from fastembed import TextEmbedding

data = json.load(sys.stdin)
model = TextEmbedding(
    model_name=data["model"],
    cache_dir=os.getenv("FASTEMBED_CACHE_PATH", "/tmp/fastembed_cache"),
    threads=1,
    local_files_only=True,
    enable_cpu_mem_arena=False,
)
json.dump([v.tolist() for v in model.embed(data["texts"], batch_size=4)], sys.stdout)

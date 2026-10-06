#!/usr/bin/env python3
"""Build (or rebuild) the knowledge-base embedding index cache.

    python scripts/build_index.py            # build if missing
    python scripts/build_index.py --force     # rebuild even if a cache exists

Requires GEMINI_API_KEY (real embeddings). The chat CLI/server will also
build this automatically on first run if it's missing, but running it
up-front makes startup latency predictable and lets you inspect the chunk
count before starting the app.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.embeddings import GeminiEmbedder
from app.retriever import build_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebuild even if a cached index already exists.")
    args = parser.parse_args()

    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set. Export it or put it in a .env file (see .env.example).", file=sys.stderr)
        sys.exit(1)

    embedder = GeminiEmbedder()
    index = build_index(embedder, force=args.force)
    print(f"Indexed {len(index.chunks)} chunks from {config.KB_DIR} -> {config.INDEX_CACHE_PATH}")


if __name__ == "__main__":
    main()

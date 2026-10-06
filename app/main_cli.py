#!/usr/bin/env python3
"""Interactive CLI for the Aster & Row support agent.

    python -m app.main_cli
    python -m app.main_cli --debug          # print the trace for each turn
    USE_MOCK_LLM=1 python -m app.main_cli   # offline demo mode, no API key needed
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

from app.bootstrap import build_agent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Print the structured trace after each answer.")
    parser.add_argument("--session", default=None, help="Reuse a specific session id (default: random per run).")
    args = parser.parse_args()

    print("Building agent (loading / indexing knowledge base)...", file=sys.stderr)
    agent = build_agent()
    session_id = args.session or str(uuid.uuid4())
    print(f"Aster & Row support agent. Session: {session_id}. Type 'exit' to quit, 'reset' for a new session.\n")

    while True:
        try:
            user_message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_message:
            continue
        if user_message.lower() in {"exit", "quit"}:
            break
        if user_message.lower() == "reset":
            session_id = str(uuid.uuid4())
            print(f"(new session: {session_id})")
            continue

        result = agent.handle_turn(session_id, user_message)
        print(f"agent> {result.answer}")
        if result.sources:
            print(f"       Sources: {', '.join(result.sources)}")
        if result.handoff:
            print(f"       [Recommending human support: {result.handoff_reason}]")
        if args.debug:
            trace = agent._trace.read_all()[-1]  # noqa: SLF001 - CLI debug convenience only
            print("       --- trace ---")
            print("      ", json.dumps(trace, indent=2)[:2000])
        print()


if __name__ == "__main__":
    main()

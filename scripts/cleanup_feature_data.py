"""Delete user-created data behind the staff/admin feature pages.

Covers, for ALL accounts (admin, support, customer) at once:

  Support Tickets        tickets, ticket_messages
  Action Center          ai_actions
  Support Workspace      conversations, messages, internal_notes
  AI Support Intelligence conversation_classifications, ai_quality_checks,
                         conversation_citations
  Knowledge Base         knowledge_documents (+ versions, index jobs)
  AI Analytics           ai_feedback, logs/trace.jsonl
  Prompt Management      prompt_templates, prompt_versions,
                         prompt_experiments, prompt_test_cases
  AI Usage               ai_usage_events, model_routing_events
  Advanced               product_recommendations (saved recommendations),
                         recommendation_explanations

User accounts, roles, permissions, orders and settings are NOT touched.

Usage (inside the backend container):
    docker compose exec backend python scripts/cleanup_feature_data.py            # dry run: only counts rows
    python scripts/cleanup_feature_data.py --yes      # really delete
    python scripts/cleanup_feature_data.py --yes --keep-conversations
        # keep the AI Chat conversations/messages (Chat history)

After running with --yes, restart the backend so the in-memory RAG index
drops chunks of the deleted Knowledge Base documents:
    docker compose restart backend
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db import models  # noqa: E402,F401  (register every table)

# (page, table) in child-before-parent order so FK constraints never block.
PLAN: list[tuple[str, str]] = [
    ("Action Center", "ai_actions"),
    ("AI Support Intelligence", "conversation_citations"),
    ("AI Support Intelligence", "ai_quality_checks"),
    ("AI Support Intelligence", "conversation_classifications"),
    ("Support Workspace", "internal_notes"),
    ("Support Tickets", "ticket_messages"),
    ("Support Tickets", "tickets"),
    ("AI Analytics", "ai_feedback"),
    ("Knowledge Base", "knowledge_index_jobs"),
    ("Knowledge Base", "knowledge_document_versions"),
    ("Knowledge Base", "knowledge_documents"),
    ("Prompt Management", "prompt_test_cases"),
    ("Prompt Management", "prompt_experiments"),
    ("Prompt Management", "prompt_versions"),
    ("Prompt Management", "prompt_templates"),
    ("AI Usage", "ai_usage_events"),
    ("AI Usage", "model_routing_events"),
    ("Advanced (saved recs)", "recommendation_explanations"),
    ("Advanced (saved recs)", "product_recommendations"),
]
CONVERSATION_PLAN = [
    ("Support Workspace / Chat", "messages"),
    ("Support Workspace / Chat", "conversations"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually delete (default is a dry run)")
    parser.add_argument("--keep-conversations", action="store_true", help="keep AI Chat conversations/messages")
    args = parser.parse_args()

    plan = list(PLAN)
    if not args.keep_conversations:
        plan += CONVERSATION_PLAN

    db = SessionLocal()
    try:
        existing = set(inspect(db.get_bind()).get_table_names())
        mode = "DELETING" if args.yes else "DRY RUN (nothing deleted)"
        print(f"== {mode} ==")
        total = 0
        for page, table in plan:
            if table not in existing:
                print(f"  [skip] {table}: table not found")
                continue
            count = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
            total += count
            if args.yes and count:
                db.execute(text(f'DELETE FROM "{table}"'))
            print(f"  {page:<26} {table:<32} {count:>6} rows")
        if args.yes:
            db.commit()
        print(f"Total rows {'deleted' if args.yes else 'that would be deleted'}: {total}")

        trace = Path(config.LOG_PATH)
        if trace.exists():
            size = trace.stat().st_size
            if args.yes:
                trace.write_text("", encoding="utf-8")
            print(f"  AI Analytics               {trace.name:<32} {size:>6} bytes")

        if not args.yes:
            print("\nRe-run with --yes to delete. Accounts/roles/orders are never touched.")
        else:
            print("\nDone. Restart the backend (docker compose restart backend) to refresh the RAG index.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

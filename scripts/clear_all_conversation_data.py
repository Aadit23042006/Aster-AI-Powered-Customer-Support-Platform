"""Delete all customer AI conversation data while preserving project configuration.

This removes chat/conversation records and their conversation-scoped AI metadata.
It does not remove users, roles, permissions, orders, Knowledge Base documents,
prompts, or application configuration.

Dry run:
    docker compose exec backend python scripts/clear_all_conversation_data.py

Delete:
    docker compose exec backend python scripts/clear_all_conversation_data.py --yes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db import models  # noqa: E402,F401

# Child tables first. Keep Knowledge Base, users, orders, prompts, roles, and
# other durable application configuration intact.
TABLES = [
    ("AI actions", "ai_actions"),
    ("Conversation citations", "conversation_citations"),
    ("AI quality checks", "ai_quality_checks"),
    ("Conversation classifications", "conversation_classifications"),
    ("Internal conversation notes", "internal_notes"),
    ("AI messages", "messages"),
    ("AI conversations", "conversations"),
]

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="actually delete rows")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = set(inspect(db.get_bind()).get_table_names())
        mode = "DELETE MODE" if args.yes else "DRY RUN"
        print(f"== {mode} ==")
        total = 0
        for label, table in TABLES:
            if table not in existing:
                print(f"  [skip] {table}: table not found")
                continue
            count = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
            total += count
            if args.yes and count:
                db.execute(text(f'DELETE FROM "{table}"'))
            print(f"  {label:<32} {table:<32} {count:>6} rows")

        if args.yes:
            db.commit()
            trace = Path(config.LOG_PATH)
            if trace.exists():
                trace.write_text("", encoding="utf-8")
            print(f"Deleted {total} conversation-related rows.")
            print("Conversation trace log cleared when present.")
            print("Users, orders, Knowledge Base, prompts, and configuration were preserved.")
        else:
            print(f"Rows that would be deleted: {total}")
            print("Re-run with --yes to delete.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()

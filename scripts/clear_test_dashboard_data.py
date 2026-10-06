"""Clear test records shown in Admin and Support dashboards.

Dry run (counts only):
    docker compose exec backend python scripts/clear_test_dashboard_data.py
Delete records:
    docker compose exec backend python scripts/clear_test_dashboard_data.py --yes

This is global, not role-specific: it clears the shared test data visible to
both admin and support accounts. It preserves users, roles, permissions,
orders, knowledge-base documents, prompts, and application configuration.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from sqlalchemy import inspect, text
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db import models  # noqa: F401,E402

# Child/dependent rows first. Tables are checked against the live DB schema.
TABLES = [
    ("Action Center AI actions", "ai_actions"),
    ("Support tickets", "ticket_messages"),
    ("Support tickets", "internal_notes"),
    ("Support tickets", "tickets"),
    ("AI conversation details", "conversation_citations"),
    ("AI conversation details", "ai_quality_checks"),
    ("AI conversation details", "conversation_classifications"),
    ("AI Usage & Routing", "ai_usage_events"),
    ("AI Usage & Routing", "model_routing_events"),
    ("AI conversations", "messages"),
    ("AI conversations", "conversations"),
]

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="delete records; without this flag only show counts")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        existing = set(inspect(db.get_bind()).get_table_names())
        total = 0
        print("== DELETE MODE ==" if args.yes else "== DRY RUN: nothing will be deleted ==")
        for label, table in TABLES:
            if table not in existing:
                print(f"[skip] {table}: table not found")
                continue
            count = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
            total += count
            if args.yes and count:
                db.execute(text(f'DELETE FROM "{table}"'))
            print(f"{label:<30} {table:<34} {count:>6}")
        if args.yes:
            db.commit()
            trace = Path(config.LOG_PATH)
            if trace.exists():
                trace.write_text("", encoding="utf-8")
                print(f"Cleared AI trace log: {trace}")
            print(f"Deleted {total} database rows. Refresh both Admin and Support pages.")
        else:
            print(f"Rows that would be deleted: {total}")
            print("Re-run with --yes to perform deletion.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()

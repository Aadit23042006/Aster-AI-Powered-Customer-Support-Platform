"""Canonical permission list and default role->permission mapping (Phase 3,
Feature 19). This is the single source of truth used by:
- `scripts/seed_db.py` (populates `permissions` + `role_permissions` in a
  real database)
- `tests_web/conftest.py` (populates the same tables in the test database,
  so permission-gated routes are testable without duplicating this list)
- `app/auth/deps.py::require_permission` (the runtime check)

Adding a new permission or changing a role's defaults means editing this
file only -- nothing else needs to change to pick it up.
"""
from __future__ import annotations


ALL_PERMISSIONS: dict[str, str] = {
    "users.read": (
        "View other users' account info "
        "(support/admin context, not self -- self access never needs a permission check)."
    ),
    "users.update": (
        "Edit another user's account, including changing their role."
    ),

    "orders.read": (
        "View any customer's orders (beyond one's own)."
    ),
    "orders.manage": (
        "Modify order records directly (support/admin tooling)."
    ),

    "tickets.read": (
        "View any customer's tickets (beyond one's own / assigned)."
    ),
    "tickets.create": (
        "Create a ticket (every authenticated user has this via their role)."
    ),
    "tickets.update": (
        "Update ticket status/fields."
    ),
    "tickets.assign": (
        "Assign a ticket to a support agent."
    ),
    "tickets.close": (
        "Close a ticket."
    ),

    "chat.use": (
        "Use the AI chat (every authenticated customer-facing role has this)."
    ),

    "knowledge.read": (
        "View admin-authored knowledge base documents and their versions."
    ),
    "knowledge.create": (
        "Create a new knowledge base document."
    ),
    "knowledge.update": (
        "Edit a knowledge base document."
    ),
    "knowledge.publish": (
        "Publish a knowledge base document "
        "(makes it live to the retriever)."
    ),
    "knowledge.archive": (
        "Archive a knowledge base document."
    ),

    "analytics.read": (
        "View the AI/ops analytics dashboard."
    ),
    "traces.read": (
        "View AI reasoning traces "
        "(may contain redacted PII -- see app/security/pii.py)."
    ),
    "evaluations.read": (
        "View evaluation run results."
    ),
    "evaluations.run": (
        "Trigger a new evaluation run."
    ),
    "feedback.read": (
        "View aggregated AI feedback."
    ),
    "audit_logs.read": (
        "View the security/administrative audit log."
    ),
    "notifications.manage": (
        "Manage notification templates/settings for other users."
    ),

    "system.read": (
        "View operational dashboards: health status and metrics "
        "(Feature 25) and the error log (Feature 26)."
    ),
    "system.manage": (
        "Manage system/security-sensitive operations: granting elevated "
        "(admin/super_admin) roles, infrastructure and security configuration. "
        "Super_admin only."
    ),

    "organizations.manage": (
        "Manage organization members and settings."
    ),
    "personas.manage": (
        "Manage organization AI personas."
    ),
    "knowledge_bases.manage": (
        "Manage organization knowledge bases."
    ),
    "products.manage": (
        "Manage organization product catalog."
    ),
    "integrations.manage": (
        "Manage API keys and webhooks."
    ),

    "action_center.read": (
        "View AI action history and tool registry."
    ),
    "action_center.execute": (
        "Execute authorized AI support tools."
    ),

    "support_workspace.read": (
        "View support workspace conversations and AI assistance."
    ),
    "support_workspace.manage": (
        "Manage support workspace notes, assignments, escalations and resolutions."
    ),

    "ai_intelligence.read": (
        "View conversation intent, sentiment and priority signals."
    ),
    "ai_quality.read": (
        "View AI response quality guard results."
    ),
    "citations.read": (
        "View verified RAG citation/source details."
    ),
}


# Every role explicitly lists its complete default permission set.
#
# customer:
#   Basic customer-facing access.
#
# support_agent:
#   Customer support operations, AI assistance, Action Center,
#   support workspace and AI intelligence.
#
# admin:
#   Administrative access plus Action Center access.
#
# super_admin:
#   All canonical permissions plus system.manage.
DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "customer": {
        "chat.use",
        "tickets.create",
    },

    "support_agent": {
        "chat.use",
        "tickets.create",

        "tickets.read",
        "tickets.update",
        "tickets.assign",
        "tickets.close",

        "orders.read",

        "action_center.read",
        "action_center.execute",

        "support_workspace.read",
        "support_workspace.manage",

        "ai_intelligence.read",
        "ai_quality.read",
        "citations.read",
    },

    "admin": {
        "chat.use",
        "tickets.create",

        "tickets.read",
        "tickets.update",
        "tickets.assign",
        "tickets.close",

        "orders.read",
        "orders.manage",

        # Action Center
        "action_center.read",
        "action_center.execute",

        # User administration
        "users.read",
        "users.update",

        # Knowledge Base
        "knowledge.read",
        "knowledge.create",
        "knowledge.update",
        "knowledge.publish",
        "knowledge.archive",

        # AI / Operations
        "analytics.read",
        "traces.read",
        "evaluations.read",
        "evaluations.run",
        "feedback.read",
        "audit_logs.read",
        "notifications.manage",

        # System
        "system.read",

        # Organization / Enterprise
        "organizations.manage",
        "personas.manage",
        "knowledge_bases.manage",
        "products.manage",
        "integrations.manage",
    },

    "super_admin": set(ALL_PERMISSIONS.keys()) | {
        "system.manage",
    },
}
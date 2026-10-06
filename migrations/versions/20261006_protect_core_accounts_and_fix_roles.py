"""Protect core accounts and repair mixed admin/customer demo roles."""
from alembic import op

revision = "20261006_core_account_protection"
down_revision = "enterprise_upgrade_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An admin/super-admin must not also be a customer. The old clean-demo
    # seed accidentally assigned both roles to admin@example.com, which made
    # the User Management customer counter display 2 instead of 1.
    op.execute(
        """
        DELETE FROM user_roles ur
        USING roles customer_role
        WHERE ur.role_id = customer_role.id
          AND customer_role.name = 'customer'
          AND EXISTS (
              SELECT 1
              FROM user_roles elevated
              JOIN roles elevated_role ON elevated_role.id = elevated.role_id
              WHERE elevated.user_id = ur.user_id
                AND elevated_role.name IN ('admin', 'super_admin')
          )
        """
    )


def downgrade() -> None:
    # Role repair is intentionally irreversible: restoring a customer role to
    # an admin would recreate the invalid mixed-role state.
    pass

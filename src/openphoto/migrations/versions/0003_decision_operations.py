"""Preserve batch undo boundaries and explicit review reasons."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # The initial migration creates current metadata for brand-new catalogs.
    inspector = sa.inspect(op.get_bind())
    if "operation_id" not in {c["name"] for c in inspector.get_columns("decisions")}:
        op.add_column("decisions", sa.Column("operation_id", sa.String(), nullable=True))
        op.create_index("ix_decisions_operation_id", "decisions", ["operation_id"])
    if "review_flags" not in {c["name"] for c in inspector.get_columns("photos")}:
        op.add_column("photos", sa.Column("review_flags", sa.Text(), nullable=False, server_default="[]"))


def downgrade():
    raise RuntimeError("Restore a project backup to downgrade")

"""Recover uncommitted editor drafts independently of render recipes."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    from openphoto.database import RecipeDraft
    RecipeDraft.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Restore a project backup to downgrade")

"""Initial versioned local catalog."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    from openphoto.database import Base
    Base.metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError("Destructive catalog downgrades are not supported; restore a backup")

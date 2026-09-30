from alembic import context
from openphoto.database import Base

context.configure(connection=context.config.attributes["connection"], target_metadata=Base.metadata)
with context.begin_transaction():
    context.run_migrations()

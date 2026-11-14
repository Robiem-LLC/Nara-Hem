"""Alembic environment: the app passes its engine; the alembic CLI uses DATABASE_URL."""

import os

from alembic import context
from sqlalchemy import create_engine

# Every table is declared in narahem.models, so importing it registers them all.
from narahem.models import Base

engine = context.config.attributes.get("engine") or create_engine(os.environ["DATABASE_URL"])

with engine.connect() as connection:
    # SQLite cannot alter tables in place; batch mode copies them instead.
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()

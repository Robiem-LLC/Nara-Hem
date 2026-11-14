"""Database schema: Alembic migrations, applied automatically on startup.

To change the schema, edit the models, then from apps/webapp/backend run
    DATABASE_URL=sqlite:///./draft.db alembic upgrade head
    DATABASE_URL=sqlite:///./draft.db alembic revision --autogenerate -m "what changed"
review the new file in narahem/migrations/versions/, and delete draft.db.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

MIGRATIONS = Path(__file__).resolve().with_name("migrations")


def config(engine=None):
    """Returns an Alembic config for this package's migrations and the given engine."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["engine"] = engine
    return cfg


def upgrade(engine):
    """Upgrades the database to the latest schema. Refuses databases created before migrations
    existed.
    """
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        current = MigrationContext.configure(connection).get_current_revision()
    if tables and current is None:
        raise RuntimeError(
            "This database predates schema migrations; start the server with an empty database"
        )
    # A database from a newer version fails here ("Can't locate revision") and is left untouched.
    command.upgrade(config(engine), "head")

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from narahem import schema
from narahem.models import Base


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name)}/schema.db")

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_migrations_build_exactly_the_models(self):
        schema.upgrade(self.engine)
        with self.engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            self.assertEqual(
                compare_metadata(context, Base.metadata),
                [],
                "Models changed without a migration: run alembic revision --autogenerate (see "
                "schema.py)",
            )
        schema.upgrade(self.engine)  # already current: nothing to do

    def test_every_migration_can_be_undone(self):
        schema.upgrade(self.engine)
        command.downgrade(schema.config(self.engine), "base")
        with self.engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
        self.assertLessEqual(tables, {"alembic_version"})
        schema.upgrade(self.engine)  # and redone from scratch

    def test_database_from_before_migrations_is_refused(self):
        with self.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE settings (id INTEGER PRIMARY KEY, version INTEGER)")
            )
        with self.assertRaisesRegex(RuntimeError, "predates schema migrations"):
            schema.upgrade(self.engine)


if __name__ == "__main__":
    unittest.main()

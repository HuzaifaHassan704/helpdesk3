"""Guards the Alembic setup: migrations apply, reverse, and always match the ORM models."""

import sqlite3

import pytest
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {"users", "tickets", "comments", "alembic_version"}


@pytest.fixture
def alembic_cfg(tmp_path):
    db_file = tmp_path / "migrations.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file}")
    cfg.attributes["skip_logging_config"] = True
    return cfg, db_file


def _tables(db_file) -> set[str]:
    con = sqlite3.connect(db_file)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


# Synchronous tests on purpose: Alembic's async env.py starts its own event loop.
def test_upgrade_and_downgrade(alembic_cfg):
    cfg, db_file = alembic_cfg
    command.upgrade(cfg, "head")
    assert EXPECTED_TABLES <= _tables(db_file)
    command.downgrade(cfg, "base")
    assert _tables(db_file) == {"alembic_version"}


def test_models_and_migrations_are_in_sync(alembic_cfg):
    """Fails if someone changes a model without generating a migration (`alembic revision --autogenerate`)."""
    cfg, _ = alembic_cfg
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises CommandError when autogenerate would produce changes


def test_single_head(alembic_cfg):
    from alembic.script import ScriptDirectory

    cfg, _ = alembic_cfg
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1

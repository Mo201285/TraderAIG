"""Schema compatibility tests for persistence safety."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

import persistence.db as db_mod  # noqa: E402


def test_sqlite_schema_patch_adds_missing_metadata_json(monkeypatch):
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE experiences (
                record_id VARCHAR(64) PRIMARY KEY,
                decision_id VARCHAR(64),
                timestamp FLOAT DEFAULT 0.0,
                thesis_id VARCHAR(64),
                candidate_id VARCHAR(64),
                market_snapshot_json TEXT DEFAULT '{}',
                risk_decision_json TEXT DEFAULT '{}',
                actual_result_json TEXT DEFAULT '{}',
                error_classification VARCHAR(32),
                slippage FLOAT DEFAULT 0.0,
                fees FLOAT DEFAULT 0.0,
                lessons_json TEXT DEFAULT '[]'
            )
        """))

    monkeypatch.setattr(db_mod, "engine", engine)
    db_mod._patch_sqlite_schema()

    cols = {c["name"] for c in inspect(engine).get_columns("experiences")}
    assert "metadata_json" in cols

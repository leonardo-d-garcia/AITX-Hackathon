"""SQLite schema and connection management (architecture section 4).

WAL, foreign keys on, one orchestration owner. Workers never touch this database; they write into
their allocated job directory and hand artifacts back.

Migrations are forward-only and numbered. The table is tiny on purpose - a hackathon repo that
grows a migration framework has spent its budget in the wrong place.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE designs (
        design_id           TEXT PRIMARY KEY,
        display_name        TEXT NOT NULL,
        active_revision_id  TEXT,
        mission_hash        TEXT,
        created_at          TEXT NOT NULL
    );

    CREATE TABLE revisions (
        revision_id             TEXT PRIMARY KEY,
        design_id               TEXT NOT NULL REFERENCES designs(design_id),
        parent_revision_id      TEXT REFERENCES revisions(revision_id),
        stage                   TEXT NOT NULL,
        created_cause           TEXT NOT NULL,
        content_hash            TEXT NOT NULL,
        mission_hash            TEXT,
        created_by_proposal_id  TEXT,
        label                   TEXT NOT NULL DEFAULT '',
        manifest_json           TEXT NOT NULL,
        created_at              TEXT NOT NULL,
        -- When this revision first became the active one. A revision that was built but never
        -- activated (a preview, or a commit whose compare-and-swap lost the race) is not a state
        -- the design was ever in, so it does not belong in the history the user scrubs through.
        activated_at            TEXT
    );
    CREATE INDEX idx_revisions_design ON revisions(design_id, created_at);
    CREATE INDEX idx_revisions_parent ON revisions(parent_revision_id);
    CREATE INDEX idx_revisions_activated ON revisions(design_id, activated_at);

    CREATE TABLE artifacts (
        artifact_id     TEXT NOT NULL,
        revision_id     TEXT NOT NULL REFERENCES revisions(revision_id),
        relative_path   TEXT NOT NULL,
        sha256          TEXT NOT NULL,
        size_bytes      INTEGER NOT NULL,
        media_type      TEXT NOT NULL,
        representation  TEXT,
        produced_by     TEXT NOT NULL,
        role            TEXT NOT NULL,
        part_ids_json   TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (artifact_id, revision_id)
    );
    CREATE INDEX idx_artifacts_revision ON artifacts(revision_id);
    CREATE INDEX idx_artifacts_id ON artifacts(artifact_id);

    CREATE TABLE proposals (
        proposal_id          TEXT PRIMARY KEY,
        design_id            TEXT NOT NULL REFERENCES designs(design_id),
        base_revision_id     TEXT NOT NULL,
        mission_hash         TEXT NOT NULL,
        state                TEXT NOT NULL,
        payload_json         TEXT NOT NULL,
        preview_revision_id  TEXT,
        preview_hash         TEXT,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL
    );
    CREATE INDEX idx_proposals_design ON proposals(design_id, base_revision_id);

    -- The idempotency store. A repeated key returns the stored outcome verbatim rather than
    -- performing the decision a second time (architecture section 13, workflow checks).
    CREATE TABLE decisions (
        idempotency_key  TEXT PRIMARY KEY,
        proposal_id      TEXT NOT NULL REFERENCES proposals(proposal_id),
        decision         TEXT NOT NULL,
        outcome_json     TEXT NOT NULL,
        created_at       TEXT NOT NULL
    );
    CREATE INDEX idx_decisions_proposal ON decisions(proposal_id);

    CREATE TABLE events (
        design_id   TEXT NOT NULL REFERENCES designs(design_id),
        sequence    INTEGER NOT NULL,
        event_json  TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (design_id, sequence)
    );

    CREATE TABLE jobs (
        job_id      TEXT PRIMARY KEY,
        design_id   TEXT NOT NULL REFERENCES designs(design_id),
        kind        TEXT NOT NULL,
        status      TEXT NOT NULL,
        cache_key   TEXT NOT NULL,
        record_json TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX idx_jobs_cache ON jobs(cache_key, status);
    CREATE INDEX idx_jobs_design ON jobs(design_id, created_at);

    CREATE TABLE missions (
        mission_hash  TEXT PRIMARY KEY,
        mission_json  TEXT NOT NULL
    );
    """,
}


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the orchestration database with the pragmas section 4 requires."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(path),
        isolation_level=None,          # explicit transactions; see `transaction`
        check_same_thread=False,
        timeout=30.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    migrate(connection)
    return connection


def migrate(connection: sqlite3.Connection) -> int:
    """Apply outstanding migrations. Returns the resulting schema version."""
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    for version in sorted(_MIGRATIONS):
        if version > current:
            connection.executescript("BEGIN;\n" + _MIGRATIONS[version] + "\nCOMMIT;")
            connection.execute(f"PRAGMA user_version = {version}")
            current = version
    return current


class transaction:
    """A write transaction.

    ``BEGIN IMMEDIATE`` takes the write lock up front, which is what makes the compare-and-swap in
    :mod:`dronebench_workflow.transactions` a real check-then-act rather than an optimistic read
    that another writer can slip past.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> sqlite3.Connection:
        self._connection.execute("BEGIN IMMEDIATE")
        return self._connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._connection.execute("COMMIT")
        else:
            self._connection.execute("ROLLBACK")
        return False


def rows(connection: sqlite3.Connection, sql: str, *params: object) -> Iterator[sqlite3.Row]:
    yield from connection.execute(sql, params)

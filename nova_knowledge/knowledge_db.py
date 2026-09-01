"""Structured, local-only knowledge store for what NOVA has learned.

The vault stays the human-readable second brain and raw evidence stays in files;
this database holds the machine-readable structure that neither can express --
confidence, status, counts, scope, and provenance.

The first thing it owns is CORRECTION MEMORY, because that is where NOVA is most
likely to hurt itself. A mishearing that reaches note generation becomes a
fabricated concept: a real COT3400 lecture produced "The condition GNRO >= N is
a property stated in the lecture slide" from a garbled `g(n) >= 0`. The flat
`STT-Corrections.md` file cannot help there, because every line in it is already
ground truth that Ahmed typed. It has no way to hold something NOVA merely
suspects.

So a correction has a lifecycle:

    candidate -> (evidence) -> confirmed -> (contradiction) -> rejected

and only CONFIRMED corrections are ever applied. A candidate is counted, kept,
and inspectable, but it does not get to change what NOVA believes. Repetition is
not verification -- the recognizer can be wrong the same way twice -- so
`times_seen` never promotes anything on its own.

Nothing here deletes: a rejected rule is retained because it explains why a note
was revised.

Follows the SQLite conventions already established in
``nova_integrations/storage.py`` (WAL, foreign keys, busy timeout, versioned
migrations) rather than inventing a second pattern. Large artifacts -- audio,
slides, PDFs -- stay file-backed and are referenced, never inlined.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from collections.abc import Generator

SCHEMA_VERSION = 1

#: Confidence a user-authored or user-confirmed correction carries. Ahmed was in
#: the room; nothing NOVA infers outranks that.
_USER_CONFIDENCE = 0.95
#: Where an inferred candidate starts. Deliberately below the applied threshold.
_CANDIDATE_CONFIDENCE = 0.3
#: Confidence at or above which a confirmed correction is applied.
_APPLY_THRESHOLD = 0.75
#: Below this a rule is retired rather than left quietly influencing notes.
_REJECT_THRESHOLD = 0.2

#: Sources whose word is good enough on arrival. `user_file` is Ahmed's own
#: `STT-Corrections.md`; `user` is him confirming in the moment.
_TRUSTED_SOURCES = frozenset({"user", "user_file"})


class CorrectionStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class CorrectionScope(StrEnum):
    """Where a correction applies. The most specific match wins.

    "consents" -> "constants" is right in an algorithms lecture and wrong in a
    conversation about consent forms, so scope is part of the rule, not a
    detail.
    """

    GLOBAL = "global"
    COURSE = "course"
    TOPIC = "topic"
    SPEAKER = "speaker"


#: Specificity order used to resolve competing rules for the same heard text.
_SCOPE_RANK = {
    CorrectionScope.GLOBAL: 0,
    CorrectionScope.COURSE: 1,
    CorrectionScope.TOPIC: 2,
    CorrectionScope.SPEAKER: 3,
}


@dataclass(frozen=True, slots=True)
class CorrectionRecord:
    heard_text: str
    corrected_text: str
    scope: CorrectionScope
    course_code: str | None
    topic: str | None
    speaker_id: str | None
    status: CorrectionStatus
    confidence: float
    times_seen: int
    times_confirmed: int
    first_seen: str
    last_seen: str
    source: str

    @property
    def is_active(self) -> bool:
        return (
            self.status is CorrectionStatus.CONFIRMED
            and self.confidence >= _APPLY_THRESHOLD
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    source: str
    detail: str
    recorded_at: str
    session_id: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_knowledge_path() -> Path:
    """Local-only, outside the vault and outside Git.

    Same environment contract as the rest of NOVA's runtime state. The vault
    holds human-readable knowledge; this holds the machine-readable structure
    behind it.
    """
    import os

    override = os.getenv("NOVA_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve() / "knowledge.sqlite3"

    local = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NOVA" / "knowledge.sqlite3").resolve()


class KnowledgeStore:
    """Local-only structured knowledge. Currently: correction memory."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row["version"]
                for row in db.execute("SELECT version FROM schema_migrations")
            }
            if 1 not in applied:
                self._migration_1(db)
                db.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (1, _now()),
                )

    @staticmethod
    def _migration_1(db: sqlite3.Connection) -> None:
        db.execute(
            """
            CREATE TABLE corrections (
                id INTEGER PRIMARY KEY,
                heard_text TEXT NOT NULL,
                heard_key TEXT NOT NULL,
                corrected_text TEXT NOT NULL,
                scope TEXT NOT NULL,
                course_code TEXT,
                topic TEXT,
                speaker_id TEXT,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                times_seen INTEGER NOT NULL DEFAULT 0,
                times_confirmed INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                source TEXT NOT NULL,
                UNIQUE (heard_key, scope, course_code, topic, speaker_id)
            )
            """
        )
        db.execute(
            "CREATE INDEX corrections_lookup ON corrections (heard_key, course_code)"
        )
        db.execute(
            """
            CREATE TABLE correction_evidence (
                id INTEGER PRIMARY KEY,
                correction_id INTEGER NOT NULL
                    REFERENCES corrections (id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                detail TEXT NOT NULL,
                session_id TEXT,
                recorded_at TEXT NOT NULL
            )
            """
        )

    def schema_version(self) -> int:
        with self.connection() as db:
            row = db.execute(
                "SELECT MAX(version) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"] or 0)

    # -- writing -------------------------------------------------------------

    def observe_correction(
        self,
        heard_text: str,
        corrected_text: str,
        *,
        course_code: str | None = None,
        topic: str | None = None,
        speaker_id: str | None = None,
        scope: CorrectionScope | None = None,
        source: str = "inferred",
        detail: str = "",
        session_id: str | None = None,
    ) -> CorrectionRecord:
        """Record that this correction was seen. Does NOT confirm it.

        A trusted source (Ahmed's own file, or Ahmed confirming) arrives already
        confirmed -- there is nothing to verify about a rule he wrote himself.
        Anything NOVA inferred starts as a candidate and stays inert until
        evidence promotes it.
        """
        resolved = scope or _infer_scope(course_code, topic, speaker_id)
        trusted = source in _TRUSTED_SOURCES
        now = _now()

        with self.connection() as db:
            existing = self._row(
                db, heard_text, resolved, course_code, topic, speaker_id
            )
            if existing is None:
                db.execute(
                    """
                    INSERT INTO corrections (
                        heard_text, heard_key, corrected_text, scope,
                        course_code, topic, speaker_id, status, confidence,
                        times_seen, times_confirmed, first_seen, last_seen, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        heard_text,
                        _key(heard_text),
                        corrected_text,
                        str(resolved),
                        course_code,
                        topic,
                        speaker_id,
                        str(
                            CorrectionStatus.CONFIRMED
                            if trusted
                            else CorrectionStatus.CANDIDATE
                        ),
                        _USER_CONFIDENCE if trusted else _CANDIDATE_CONFIDENCE,
                        1 if trusted else 0,
                        now,
                        now,
                        source,
                    ),
                )
            else:
                db.execute(
                    "UPDATE corrections SET times_seen = times_seen + 1, "
                    "last_seen = ? WHERE id = ?",
                    (now, existing["id"]),
                )

            if detail:
                row = self._row(
                    db, heard_text, resolved, course_code, topic, speaker_id
                )
                if row is None:
                    raise RuntimeError(
                        "Correction row vanished between write and evidence insert."
                    )
                db.execute(
                    "INSERT INTO correction_evidence "
                    "(correction_id, source, detail, session_id, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row["id"], source, detail, session_id, now),
                )

        found = self.find_correction(
            heard_text, course_code=course_code, topic=topic, speaker_id=speaker_id
        )
        assert found is not None
        return found

    def confirm_correction(
        self,
        heard_text: str,
        *,
        course_code: str | None = None,
        topic: str | None = None,
        speaker_id: str | None = None,
        source: str = "user",
        detail: str = "",
        session_id: str | None = None,
    ) -> CorrectionRecord:
        """Independent evidence supports this correction. Promote it."""
        record = self.find_correction(
            heard_text, course_code=course_code, topic=topic, speaker_id=speaker_id
        )
        if record is None:
            raise KeyError(heard_text)

        confidence = (
            _USER_CONFIDENCE
            if source in _TRUSTED_SOURCES
            else min(0.99, record.confidence + 0.2)
        )
        status = (
            CorrectionStatus.CONFIRMED
            if confidence >= _APPLY_THRESHOLD
            else CorrectionStatus.CANDIDATE
        )
        now = _now()

        with self.connection() as db:
            row = self._row(
                db, heard_text, record.scope, course_code, topic, speaker_id
            )
            if row is None:
                raise KeyError(heard_text)
            db.execute(
                "UPDATE corrections SET status = ?, confidence = ?, "
                "times_confirmed = times_confirmed + 1, last_seen = ? WHERE id = ?",
                (str(status), confidence, now, row["id"]),
            )
            db.execute(
                "INSERT INTO correction_evidence "
                "(correction_id, source, detail, session_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row["id"],
                    source,
                    detail or f"Confirmed by {source}.",
                    session_id,
                    now,
                ),
            )

        found = self.find_correction(
            heard_text, course_code=course_code, topic=topic, speaker_id=speaker_id
        )
        assert found is not None
        return found

    def contradict_correction(
        self,
        heard_text: str,
        *,
        course_code: str | None = None,
        topic: str | None = None,
        speaker_id: str | None = None,
        source: str = "contradiction",
        detail: str = "",
        session_id: str | None = None,
    ) -> CorrectionRecord:
        """Evidence against. Lower confidence, and retire the rule if it falls far enough."""
        record = self.find_correction(
            heard_text, course_code=course_code, topic=topic, speaker_id=speaker_id
        )
        if record is None:
            raise KeyError(heard_text)

        confidence = max(0.0, record.confidence - 0.2)
        status = (
            CorrectionStatus.REJECTED
            if confidence <= _REJECT_THRESHOLD
            else record.status
        )
        now = _now()

        with self.connection() as db:
            row = self._row(
                db, heard_text, record.scope, course_code, topic, speaker_id
            )
            if row is None:
                raise KeyError(heard_text)
            db.execute(
                "UPDATE corrections SET status = ?, confidence = ?, last_seen = ? "
                "WHERE id = ?",
                (str(status), confidence, now, row["id"]),
            )
            db.execute(
                "INSERT INTO correction_evidence "
                "(correction_id, source, detail, session_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row["id"],
                    source,
                    detail or "Contradicting evidence observed.",
                    session_id,
                    now,
                ),
            )

        found = self.find_correction(
            heard_text, course_code=course_code, topic=topic, speaker_id=speaker_id
        )
        assert found is not None
        return found

    # -- reading -------------------------------------------------------------

    def find_correction(
        self,
        heard_text: str,
        *,
        course_code: str | None = None,
        topic: str | None = None,
        speaker_id: str | None = None,
    ) -> CorrectionRecord | None:
        """The best rule for this text in this context, most specific first."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM corrections WHERE heard_key = ?", (_key(heard_text),)
            ).fetchall()

        candidates = [
            row
            for row in rows
            if _scope_applies(row, course_code, topic, speaker_id)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda row: (
                _SCOPE_RANK.get(CorrectionScope(row["scope"]), 0),
                row["confidence"],
            ),
            reverse=True,
        )
        return _as_record(candidates[0])

    def active_corrections(
        self,
        *,
        course_code: str | None = None,
        topic: str | None = None,
        speaker_id: str | None = None,
    ) -> tuple[CorrectionRecord, ...]:
        """Only CONFIRMED, sufficiently-confident rules. Candidates never apply."""
        with self.connection() as db:
            rows = db.execute("SELECT * FROM corrections").fetchall()

        best: dict[str, sqlite3.Row] = {}
        for row in rows:
            if not _scope_applies(row, course_code, topic, speaker_id):
                continue
            record = _as_record(row)
            if not record.is_active:
                continue
            key = row["heard_key"]
            incumbent = best.get(key)
            if incumbent is None or _SCOPE_RANK.get(
                CorrectionScope(row["scope"]), 0
            ) > _SCOPE_RANK.get(CorrectionScope(incumbent["scope"]), 0):
                best[key] = row

        return tuple(
            sorted(
                (_as_record(row) for row in best.values()),
                key=lambda item: (-len(item.heard_text), item.heard_text.casefold()),
            )
        )

    def correction_evidence(
        self,
        heard_text: str,
        *,
        course_code: str | None = None,
        topic: str | None = None,
        speaker_id: str | None = None,
    ) -> tuple[EvidenceRecord, ...]:
        """Why NOVA believes this correction."""
        record = self.find_correction(
            heard_text, course_code=course_code, topic=topic, speaker_id=speaker_id
        )
        if record is None:
            return ()
        with self.connection() as db:
            row = self._row(
                db, heard_text, record.scope, course_code, topic, speaker_id
            )
            if row is None:
                return ()
            rows = db.execute(
                "SELECT source, detail, session_id, recorded_at "
                "FROM correction_evidence WHERE correction_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
        return tuple(
            EvidenceRecord(
                source=item["source"],
                detail=item["detail"],
                recorded_at=item["recorded_at"],
                session_id=item["session_id"],
            )
            for item in rows
        )

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _row(
        db: sqlite3.Connection,
        heard_text: str,
        scope: CorrectionScope,
        course_code: str | None,
        topic: str | None,
        speaker_id: str | None,
    ) -> sqlite3.Row | None:
        return db.execute(
            "SELECT * FROM corrections WHERE heard_key = ? AND scope = ? "
            "AND course_code IS ? AND topic IS ? AND speaker_id IS ?",
            (_key(heard_text), str(scope), course_code, topic, speaker_id),
        ).fetchone()


def _key(heard_text: str) -> str:
    return " ".join(str(heard_text).split()).casefold()


def _infer_scope(
    course_code: str | None, topic: str | None, speaker_id: str | None
) -> CorrectionScope:
    if speaker_id:
        return CorrectionScope.SPEAKER
    if topic:
        return CorrectionScope.TOPIC
    if course_code:
        return CorrectionScope.COURSE
    return CorrectionScope.GLOBAL


def _scope_applies(
    row: sqlite3.Row,
    course_code: str | None,
    topic: str | None,
    speaker_id: str | None,
) -> bool:
    scope = CorrectionScope(row["scope"])
    if scope is CorrectionScope.GLOBAL:
        return True
    if row["course_code"] and row["course_code"] != course_code:
        return False
    if scope is CorrectionScope.COURSE:
        return True
    if scope is CorrectionScope.TOPIC:
        return bool(topic) and row["topic"] == topic
    if scope is CorrectionScope.SPEAKER:
        return bool(speaker_id) and row["speaker_id"] == speaker_id
    return False


def _as_record(row: sqlite3.Row) -> CorrectionRecord:
    return CorrectionRecord(
        heard_text=row["heard_text"],
        corrected_text=row["corrected_text"],
        scope=CorrectionScope(row["scope"]),
        course_code=row["course_code"],
        topic=row["topic"],
        speaker_id=row["speaker_id"],
        status=CorrectionStatus(row["status"]),
        confidence=float(row["confidence"]),
        times_seen=int(row["times_seen"]),
        times_confirmed=int(row["times_confirmed"]),
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        source=row["source"],
    )

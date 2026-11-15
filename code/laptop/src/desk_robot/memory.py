"""Durable, provenance-aware memories for five independently identified desk pets.

This is a local, text-only SQLite store, not a vector search system and not
camera history. A peer telling a story must never be reclassified as something
the receiver saw. There are no motion permits, commands, images or secrets in
the schema. All calls are synchronous; callers should serialize writes and
offload blocking I/O from their asyncio event loop.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
_EVENT_KIND = re.compile(r"[a-z_]{1,40}\Z")


_CORE_SLOT = re.compile(r"[a-z][a-z0-9_]{1,39}\Z")
_WORDS = re.compile(r"[a-z0-9]{2,}")
_QUERY_FILLER = frozenset({
    "a", "an", "and", "are", "at", "be", "can", "did", "do", "for", "from",
    "have", "i", "in", "is", "it", "me", "my", "of", "on", "our", "that",
    "the", "there", "this", "to", "was", "we", "were", "what", "when",
    "where", "which", "who", "with", "you", "your",
})


def _terms(text: str) -> frozenset[str]:
    """Small local lexical recall, no external embedding service or new agent."""
    words = _WORDS.findall(text.casefold())[:96]
    return frozenset(
        word[:-3] + "y" if len(word) > 4 and word.endswith("ies")
        else word[:-1] if len(word) > 3 and word.endswith("s")
        else word
        for word in words if word not in _QUERY_FILLER
    )


@dataclass(frozen=True)
class Memory:
    robot_id: str
    event_id: str
    source_robot: str
    witnessed: bool
    kind: str
    summary: str
    observed_at: float
    confidence: float


@dataclass(frozen=True)
class CoreFact:
    robot_id: str
    slot: str
    value: str
    updated_at: float


class MemoryStore:
    """One local SQLite database per robot; explicit observed vs told provenance."""

    def __init__(self, root: Path, robot_ids: list[str] | tuple[str, ...]):
        self.root = Path(root)
        self.robot_ids = frozenset(robot_ids)
        if not self.robot_ids or not all(_ROBOT_ID.fullmatch(i) for i in self.robot_ids):
            raise ValueError("Every robot ID must be a safe nonempty identifier")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("Memory root must not be a symlink")
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass  # Network/Windows filesystems may not support POSIX permissions.
        for robot in sorted(self.robot_ids):
            with self._connect(robot) as db:
                db.execute(
                    """CREATE TABLE IF NOT EXISTS memories (
                         event_id TEXT PRIMARY KEY,
                         source_robot TEXT NOT NULL,
                         witnessed INTEGER NOT NULL CHECK(witnessed IN (0,1)),
                         kind TEXT NOT NULL,
                         summary TEXT NOT NULL,
                         observed_at REAL NOT NULL,
                         confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1)
                       )"""
                )
                # Operator-curated core identity/preferences are distinct
                # from automatic sensor episodes. Like Letta core memory,
                # a tiny stable block survives the 250-event rolling buffer.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS core_facts (
                         slot TEXT PRIMARY KEY,
                         value TEXT NOT NULL,
                         updated_at REAL NOT NULL
                       )"""
                )

    @contextmanager
    def _connect(self, robot_id: str):
        if robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        path = self.root / (robot_id + ".sqlite3")
        if path.is_symlink():
            raise ValueError("Refusing symlinked memory database")
        db = sqlite3.connect(path, timeout=3)
        try:
            db.execute("PRAGMA busy_timeout=3000")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def remember(
        self,
        robot_id: str,
        event_id: str,
        summary: str,
        *,
        kind: str,
        source_robot: str,
        witnessed: bool,
        observed_at: float | None = None,
        confidence: float = 1.0,
    ) -> bool:
        """Idempotently store one fact; duplicates do not rewrite earlier evidence."""
        if (not isinstance(robot_id, str) or not isinstance(source_robot, str)
                or robot_id not in self.robot_ids or source_robot not in self.robot_ids):
            raise ValueError("Unknown robot identity")
        if (not isinstance(event_id, str) or not isinstance(kind, str)
                or not _EVENT_ID.fullmatch(event_id) or not _EVENT_KIND.fullmatch(kind)):
            raise ValueError("Invalid event ID or kind")
        if witnessed is not True and witnessed is not False:
            raise ValueError("witnessed must be a boolean")
        if witnessed != (source_robot == robot_id):
            raise ValueError("Only this robot's own sensor observations are witnessed")
        if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 300:
            raise ValueError("Bounded nonempty description required")
        if "\x00" in summary:
            raise ValueError("Invalid description")
        when = time.time() if observed_at is None else observed_at
        if not isinstance(when, (int, float)) or isinstance(when, bool) or not 0 <= when < 1e12:
            raise ValueError("Invalid observation clock")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("Confidence outside [0,1]")
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence outside [0,1]")
        if not math.isfinite(when) or not math.isfinite(confidence):
            raise ValueError("Nonfinite timestamp or confidence")
        with self._connect(robot_id) as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO memories
                   (event_id,source_robot,witnessed,kind,summary,observed_at,confidence)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    event_id, source_robot, int(witnessed), kind, summary.strip(),
                    float(when), float(confidence),
                ),
            )
            # Keep a bounded episodic store; rich long term semantic memory can
            # be layered later without changing the per-robot provenance contract.
            db.execute(
                """DELETE FROM memories WHERE event_id IN (
                     SELECT event_id FROM memories
                     ORDER BY observed_at DESC, event_id DESC LIMIT -1 OFFSET 250
                   )"""
            )
            return cursor.rowcount == 1

    def recent(self, robot_id: str, *, limit: int = 12) -> list[Memory]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Limit must be 1..50")
        with self._connect(robot_id) as db:
            rows = db.execute(
                """SELECT event_id,source_robot,witnessed,kind,summary,observed_at,confidence
                   FROM memories ORDER BY observed_at DESC,event_id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            Memory(robot_id, event_id, source, bool(witnessed), kind, summary, at, score)
            for event_id, source, witnessed, kind, summary, at, score in rows
        ]

    def search(self, robot_id: str, query: str, *, limit: int = 6) -> list[Memory]:
        """Recall relevant events from THIS pet's local episodic SQLite store.

        Mirrors LangGraph's separation of short lived turn state from durable
        memories without introducing another agent. The store has at most 250
        records per robot, so this bounded fallback needs no embedding server.
        Empty matches produce no invented recollections.
        """
        if robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 240
                or "\x00" in query or type(limit) is not int
                or not 1 <= limit <= 12):
            raise ValueError("Bounded memory question and limit required")
        wanted = _terms(query)
        if not wanted:
            return []
        with self._connect(robot_id) as db:
            rows = db.execute(
                """SELECT event_id,source_robot,witnessed,kind,summary,observed_at,confidence
                   FROM memories ORDER BY observed_at DESC,event_id DESC LIMIT 250"""
            ).fetchall()
        now = time.time()
        ranked = []
        for event_id, source, witnessed, kind, summary, at, score in rows:
            common = len(wanted & _terms(summary + " " + kind))
            if not common:
                continue
            # Topic match wins; confidence, firsthand source and recent age
            # break ties. None upgrades secondhand memory to eyewitness fact.
            age_days = max(0.0, now - at) / 86400
            rank = (
                5 * common / len(wanted) + 2 * common + float(score)
                + (0.25 if witnessed else 0)
                + 0.25 / (1 + age_days / 14),
                at,
                event_id,
            )
            ranked.append((
                rank, Memory(robot_id, event_id, source, bool(witnessed),
                             kind, summary, at, score),
            ))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in ranked[:limit]]

    def set_core_fact(self, robot_id: str, slot: str, value: str) -> bool:
        """Curate one long-lived preference; ONLY operator API may invoke.

        No model/tool automatically edits identity, user preferences or safety
        policy. This bounded core is separate from ephemeral episodes.
        """
        if robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        if not isinstance(slot, str) or not _CORE_SLOT.fullmatch(slot):
            raise ValueError("Invalid core memory slot")
        if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 200
                or "\x00" in value):
            raise ValueError("Invalid bounded core memory value")
        clean = " ".join(value.split())
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT value FROM core_facts WHERE slot=?", (slot,)
            ).fetchone()
            if old is None and db.execute(
                "SELECT count(*) FROM core_facts"
            ).fetchone()[0] >= 24:
                raise ValueError("Robot core memory limited to 24 slots")
            if old is not None and old[0] == clean:
                return False
            db.execute(
                """INSERT INTO core_facts (slot,value,updated_at)
                   VALUES (?,?,?)
                   ON CONFLICT(slot) DO UPDATE SET
                       value=excluded.value,updated_at=excluded.updated_at""",
                (slot, clean, time.time()),
            )
            return True

    def core_facts(self, robot_id: str, *, limit: int = 12) -> list[CoreFact]:
        if type(limit) is not int or not 1 <= limit <= 24:
            raise ValueError("Core memory limit must be 1..24")
        with self._connect(robot_id) as db:
            rows = db.execute(
                """SELECT slot,value,updated_at FROM core_facts
                   ORDER BY updated_at DESC,slot ASC LIMIT ?""", (limit,)
            ).fetchall()
        return [CoreFact(robot_id, slot, value, at)
                for slot, value, at in rows]

    def forget_core_fact(self, robot_id: str, slot: str) -> bool:
        if not isinstance(slot, str) or not _CORE_SLOT.fullmatch(slot):
            raise ValueError("Invalid core memory slot")
        with self._connect(robot_id) as db:
            return db.execute(
                "DELETE FROM core_facts WHERE slot=?", (slot,)
            ).rowcount == 1

    def forget_episode(self, robot_id: str, event_id: str) -> bool:
        """Explicit per-pet deletion; does not silently mutate peer memories."""
        if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        with self._connect(robot_id) as db:
            return db.execute(
                "DELETE FROM memories WHERE event_id=?", (event_id,)
            ).rowcount == 1

    def count(self, robot_id: str) -> int:
        with self._connect(robot_id) as db:
            return int(db.execute("SELECT count(*) FROM memories").fetchone()[0])

"""Durable, provenance-aware memories for five independently identified desk pets.

This is a local, text-only SQLite store, not a vector search system and not
camera history. A peer telling a story must never be reclassified as something
the receiver saw. There are no motion permits, commands, images or secrets in
the schema. All calls are synchronous; callers should serialize writes and
offload blocking I/O from their asyncio event loop.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
_EVENT_KIND = re.compile(r"[a-z_]{1,40}\Z")


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

    def _connect(self, robot_id: str) -> sqlite3.Connection:
        if robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        path = self.root / (robot_id + ".sqlite3")
        if path.is_symlink():
            raise ValueError("Refusing symlinked memory database")
        db = sqlite3.connect(path, timeout=3)
        db.execute("PRAGMA busy_timeout=3000")
        return db

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
        if robot_id not in self.robot_ids or source_robot not in self.robot_ids:
            raise ValueError("Unknown robot identity")
        if not _EVENT_ID.fullmatch(event_id) or not _EVENT_KIND.fullmatch(kind):
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
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("Confidence outside [0,1]")
        # Refuse NaN/Inf because they poison ranking and cannot be meaningful evidence.
        import math

        if not math.isfinite(float(when)) or not math.isfinite(float(confidence)):
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

    def count(self, robot_id: str) -> int:
        with self._connect(robot_id) as db:
            return int(db.execute("SELECT count(*) FROM memories").fetchone()[0])

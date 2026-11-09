"""Persistent, provenance-aware per-robot observations. No image or audio storage.

SQLite is part of Python, rather than a new framework. One event-loop owner
writes through this small adapter; a peer event never becomes a firsthand memory.
No drive authority, voice tokens or raw media may be serialized here.
"""

from __future__ import annotations

import json
import math
import sqlite3

from .config import Settings


class PetMemory:
    def __init__(self, settings: Settings):
        self.robot_ids = {r.id for r in settings.robots}
        self.directory = settings.memory_dir
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.databases: dict[str, sqlite3.Connection] = {}
        for robot_id in self.robot_ids:
            path = self.directory / f"{robot_id}.sqlite3"
            connection = sqlite3.connect(path, timeout=2)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    observed_by TEXT NOT NULL,
                    told_by TEXT,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    captured_at REAL NOT NULL,
                    source TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS recent_memories ON memories(captured_at DESC)"
            )
            connection.commit()
            self.databases[robot_id] = connection

    def remember(
        self,
        robot_id: str,
        *,
        event_id: str,
        observed_by: str,
        kind: str,
        summary: str,
        captured_at: float,
        source: str = "camera",
        told_by: str | None = None,
    ) -> bool:
        if robot_id not in self.databases:
            raise ValueError("Unknown memory owner")
        if observed_by not in self.robot_ids:
            raise ValueError("Unknown original witness")
        if told_by is not None and told_by not in self.robot_ids:
            raise ValueError("Unknown peer")
        if source not in {"camera", "touch", "human", "peer", "sound"}:
            raise ValueError("Unknown observation source")
        if source == "peer" and (told_by is None or observed_by == robot_id):
            raise ValueError("Peer memories must be attributed to their actual witness")
        if source != "peer" and observed_by != robot_id:
            raise ValueError("Direct observations must belong to their actual witness")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
            raise ValueError("Invalid event identifier")
        if not isinstance(kind, str) or not 1 <= len(kind) <= 40:
            raise ValueError("Invalid event kind")
        if not isinstance(summary, str) or not 1 <= len(summary) <= 300:
            raise ValueError("Only short text summaries are stored, never raw media")
        if not isinstance(captured_at, (int, float)) or not math.isfinite(captured_at):
            raise ValueError("Invalid timestamp")
        with self.databases[robot_id]:
            result = self.databases[robot_id].execute(
                """INSERT OR IGNORE INTO memories
                   (event_id, observed_by, told_by, kind, summary, captured_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_id, observed_by, told_by, kind, summary, float(captured_at), source),
            )
        return bool(result.rowcount)

    def recent(self, robot_id: str, limit: int = 8) -> list[dict]:
        if robot_id not in self.databases or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("Unknown robot or invalid memory limit")
        cursor = self.databases[robot_id].execute(
            """SELECT event_id, observed_by, told_by, kind, summary, captured_at, source
               FROM memories ORDER BY captured_at DESC, id DESC LIMIT ?""",
            (limit,),
        )
        names = ("event_id", "observed_by", "told_by", "kind", "summary", "captured_at", "source")
        return [dict(zip(names, row, strict=True)) for row in cursor]

    def context(self, robot_id: str) -> str:
        """Explicitly label what is personally seen versus secondhand."""
        records = self.recent(robot_id)
        if not records:
            return "No confirmed prior memories."
        return json.dumps(
            [
                {
                    "witness": row["observed_by"],
                    "secondhand": row["source"] == "peer",
                    "summary": row["summary"],
                    "kind": row["kind"],
                }
                for row in records
            ],
            ensure_ascii=False,
        )[:2400]

    def close(self):
        for connection in self.databases.values():
            connection.close()
        self.databases.clear()

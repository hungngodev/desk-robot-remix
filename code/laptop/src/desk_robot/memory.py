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
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_ROBOT_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
_EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
_EVENT_KIND = re.compile(r"[a-z_]{1,40}\Z")
_RELAY_TOKEN = re.compile(r"[0-9a-f]{32}\Z")

# Every retained deletion ID is an exact cross-restart replay prohibition.
# Unlike bounded episode rows, tombstones CANNOT be silently evicted.
# At this generous per-pet budget (~274 unique deletions/day for a year),
# seal only NEW memory writes durably. Explicit forget remains available.
_MAX_DELETED_EPISODE_IDS = 100_000

# SQLite INTEGER is a signed 64-bit value. Mutation receipts use its positive range.
_MAX_MUTATION_GENERATION = (1 << 63) - 1


class MemoryWriteSealed(RuntimeError):
    """Private episode writes are disabled after the deletion fence fills."""


class CoreMemoryMutationSuperseded(RuntimeError):
    """A newer operator mutation retired this core slot request."""


class EpisodeMemoryMutationSuperseded(RuntimeError):
    """A newer operator correction or deletion retired this episode request."""


_CORE_SLOT = re.compile(r"[a-z][a-z0-9_]{1,39}\Z")
_WORDS = re.compile(r"(?u)[^\W_]{2,}")
_QUERY_FILLER = frozenset({
    "a", "an", "and", "are", "at", "be", "can", "did", "do", "for", "from",
    "have", "i", "in", "is", "it", "me", "my", "of", "on", "our", "that",
    "the", "there", "this", "to", "was", "we", "were", "what", "when",
    "where", "which", "who", "with", "you", "your",
})


def _fts_query(text: str) -> str:
    """Safely quote bounded Unicode query tokens for SQLite FTS5 MATCH.

    Porter stemming and tokenization belong to SQLite, not custom Python
    suffix rules. Quoted individual tokens also prevent FTS5 operators or
    user hyphens from becoming query syntax.
    """
    # Streaming ASR and clients can send canonically equivalent NFD text.
    # Combining marks otherwise split a Vietnamese word before FTS tokenization.
    normalized = unicodedata.normalize("NFC", text.casefold())
    terms = [
        term for term in _WORDS.findall(normalized)[:96]
        if term not in _QUERY_FILLER
    ]
    # FTS5 unicode61 does not always index an already-stored NFD word
    # identically to its NFC spelling (for example Vietnamese "điện").
    # Query both canonical forms rather than rewriting private episodes.
    variants = dict.fromkeys(
        form for term in terms
        for form in (term, unicodedata.normalize("NFD", term))
    )
    return " OR ".join('"' + term + '"' for term in variants)


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
class CameraProvenance:
    """Provenance without raw media or invented device-to-Mac clock mapping."""
    received_at: float
    interpreted_at: float
    source_identity: tuple[int, int, int] | None = None


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
        if (not isinstance(robot_ids, (list, tuple)) or not robot_ids
                or not all(type(i) is str and _ROBOT_ID.fullmatch(i)
                           for i in robot_ids)):
            raise ValueError("Every robot ID must be a safe nonempty identifier")
        self.robot_ids = frozenset(robot_ids)
        # The Mac's APFS volume may be case insensitive. Different Python
        # identifiers must not silently share one physical SQLite filename.
        if (len(self.robot_ids) != len(robot_ids)
                or len({robot.casefold() for robot in robot_ids}) != len(robot_ids)):
            raise ValueError("Duplicate robot memory identities are not allowed")
        # An ancestor alias bypasses a check of the final directory alone.
        # Refuse it BEFORE mkdir can create private records in another tree.
        if any(part.is_symlink() for part in (self.root, *self.root.parents)):
            raise ValueError("Memory root ancestry must not contain symlinks")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError as exc:
            # A readable shared directory defeats per-pet SQLite isolation.
            # Do not initialize durable private memories if the filesystem
            # refuses the local permission boundary.
            raise PermissionError("Cannot protect private robot memory root") from exc
        if self.root.stat().st_mode & 0o077:
            raise PermissionError("Robot memory root is accessible to other users")
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
                         confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                         relay_token TEXT
                       )"""
                )
                # Older private databases lack this nullable internal receipt.
                if "relay_token" not in {
                    row[1] for row in db.execute("PRAGMA table_info(memories)")
                }:
                    db.execute("ALTER TABLE memories ADD COLUMN relay_token TEXT")
                # One private sidecar per robot, no JPEG or PCM stored.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS camera_provenance (
                         event_id TEXT PRIMARY KEY,
                         mac_received_at REAL NOT NULL,
                         interpreted_at REAL NOT NULL,
                         device_boot INTEGER,
                         device_frame INTEGER,
                         device_complete_us TEXT
                       )"""
                )
                # Spatial metadata shares this pet's existing private DB and
                # episode lifecycle. Never store a raw JPEG or voice sample.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS spatial_observations (
                         event_id TEXT PRIMARY KEY,
                         object_key TEXT NOT NULL,
                         observed_at REAL NOT NULL,
                         body_boot INTEGER NOT NULL,
                         origin_id TEXT NOT NULL,
                         pose_seq INTEGER NOT NULL,
                         pose_sample_us INTEGER NOT NULL,
                         camera_boot INTEGER NOT NULL,
                         camera_seq INTEGER NOT NULL,
                         camera_complete_us TEXT NOT NULL,
                         calibration_id TEXT NOT NULL,
                         x_mm INTEGER NOT NULL,
                         y_mm INTEGER NOT NULL,
                         yaw_mrad INTEGER NOT NULL,
                         uncertainty_mm INTEGER NOT NULL,
                         frame TEXT NOT NULL CHECK(frame IN ('odom', 'map')),
                         anchor_id TEXT,
                         UNIQUE(object_key,camera_boot,camera_seq,camera_complete_us)
                       )"""
                )
                db.execute(
                    """CREATE INDEX IF NOT EXISTS spatial_object_latest
                       ON spatial_observations(object_key,observed_at DESC,event_id DESC)"""
                )
                # A deletion tombstone contains only the random event ID,
                # never private episode text. Retain it across reconnects so
                # an old delayed audio/vision callback cannot resurrect a
                # fact after an operator forget or consent revocation.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS deleted_episode_ids (
                         event_id TEXT PRIMARY KEY
                       )"""
                )
                # Saturation cannot evict a tombstone: that would allow
                # delayed canceled audio or camera callbacks to resurrect an
                # explicitly deleted memory. Persist one per-pet write seal.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS deletion_fence_guard (
                         singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                         writes_sealed INTEGER NOT NULL
                             CHECK(writes_sealed IN (0,1))
                       )"""
                )
                db.execute(
                    "INSERT OR IGNORE INTO deletion_fence_guard "
                    "(singleton,writes_sealed) VALUES (1,0)"
                )
                # Legacy databases may already contain more deletions than
                # the current budget. Their next episode write must NOT get
                # an accidental new lease just because this schema is new.
                db.execute(
                    """UPDATE deletion_fence_guard SET writes_sealed=1
                       WHERE singleton=1 AND
                         (SELECT COUNT(*) FROM deleted_episode_ids) >= ?""",
                    (_MAX_DELETED_EPISODE_IDS,),
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
                # Durable request-order tombstones remain after a deletion.
                # Neither the slot token nor its revision stores private text.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS core_fact_mutations (
                         slot TEXT PRIMARY KEY,
                         generation INTEGER NOT NULL CHECK(generation > 0)
                       )"""
                )
                # Request ordering persists across async workers and Mac
                # restarts. Only bounded event IDs, never private text, live
                # here; an older correction cannot outlive a newer deletion.
                db.execute(
                    """CREATE TABLE IF NOT EXISTS episode_mutations (
                         event_id TEXT PRIMARY KEY,
                         generation INTEGER NOT NULL CHECK(generation > 0)
                       )"""
                )
                # SQLite FTS5 is built in and zero-dependency. An external
                # content index avoids storing a second copy of text and
                # preserves the existing per-pet provenance source of truth.
                db.execute(
                    """CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                       USING fts5(summary, kind, content='memories',
                                  content_rowid='rowid',
                                  tokenize='porter unicode61')"""
                )
                db.executescript(
                    """CREATE TRIGGER IF NOT EXISTS spatial_observations_delete
                       AFTER DELETE ON memories BEGIN
                          DELETE FROM spatial_observations WHERE event_id=old.event_id;
                       END;
                       CREATE TRIGGER IF NOT EXISTS spatial_observations_correction
                       AFTER UPDATE OF summary ON memories
                       WHEN new.summary <> old.summary BEGIN
                          DELETE FROM spatial_observations WHERE event_id=old.event_id;
                       END;
                       CREATE TRIGGER IF NOT EXISTS camera_provenance_delete
                       AFTER DELETE ON memories BEGIN
                         DELETE FROM camera_provenance WHERE event_id=old.event_id;
                       END;
                       CREATE TRIGGER IF NOT EXISTS memories_fts_insert
                       AFTER INSERT ON memories BEGIN
                         INSERT INTO memories_fts(rowid,summary,kind)
                         VALUES (new.rowid,new.summary,new.kind);
                       END;
                       CREATE TRIGGER IF NOT EXISTS memories_fts_delete
                       AFTER DELETE ON memories BEGIN
                         INSERT INTO memories_fts(memories_fts,rowid,summary,kind)
                         VALUES ('delete',old.rowid,old.summary,old.kind);
                       END;
                       CREATE TRIGGER IF NOT EXISTS memories_fts_update
                       AFTER UPDATE ON memories BEGIN
                         INSERT INTO memories_fts(memories_fts,rowid,summary,kind)
                         VALUES ('delete',old.rowid,old.summary,old.kind);
                         INSERT INTO memories_fts(rowid,summary,kind)
                         VALUES (new.rowid,new.summary,new.kind);
                       END;"""
                )
                # At most 250 rows per robot. Rebuild once per store start
                # so an interrupted migration cannot leave a present but
                # incomplete index, without touching original episode rows.
                db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")

    @contextmanager
    def _connect(self, robot_id: str):
        # A str subclass can override hashing or filename construction. Only
        # a plain schema string may select a private database.
        if type(robot_id) is not str or robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        # Repeat the ancestry check at each SQLite open: a linked parent
        # introduced after boot must not redirect subsequent private reads.
        if any(part.is_symlink() for part in (self.root, *self.root.parents)):
            raise ValueError("Memory root ancestry must not contain symlinks")
        path = self.root / (robot_id + ".sqlite3")
        # A renamed fleet identity must not inherit an old pet's private
        # database on a case-insensitive Mac volume. Directory entries retain
        # their actual spelling even when a differently cased lookup succeeds.
        if any(entry.name != path.name
               and entry.name.casefold() == path.name.casefold()
               for entry in self.root.iterdir()):
            raise ValueError("Case-aliased robot memory database")
        if path.is_symlink():
            raise ValueError("Refusing symlinked memory database")
        # Two pet filenames must never share one SQLite inode, including
        # aliases introduced after MemoryStore was initialized.
        if path.exists() and path.stat().st_nlink > 1:
            raise ValueError("Refusing hard-linked memory database")
        db = sqlite3.connect(path, timeout=3)
        try:
            # A private root is necessary but insufficient if an older
            # database file was created with group/world read bits. Restrict
            # both new and legacy pet files before any episode is accessed.
            try:
                os.chmod(path, 0o600)
            except OSError as exc:
                raise PermissionError(
                    "Cannot protect private robot memory database"
                ) from exc
            if path.stat().st_mode & 0o077:
                raise PermissionError(
                    "Robot memory database is accessible to other users"
                )
            db.execute("PRAGMA busy_timeout=3000")
            # SQLite ordinarily leaves deleted row bytes in free pages.
            # Restore secure_delete on every connection, including legacy
            # databases, before correction, retention trimming or forgetting.
            # This is NOT a claim to erase backups or FTS5 historical pages.
            db.execute("PRAGMA secure_delete=ON")
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
        camera_provenance: CameraProvenance | None = None,
        relay_token: str | None = None,
    ) -> bool:
        """Idempotently store one fact; duplicates do not rewrite earlier evidence."""
        if (type(robot_id) is not str or type(source_robot) is not str
                or robot_id not in self.robot_ids or source_robot not in self.robot_ids):
            raise ValueError("Unknown robot identity")
        if (type(event_id) is not str or type(kind) is not str
                or not _EVENT_ID.fullmatch(event_id) or not _EVENT_KIND.fullmatch(kind)):
            raise ValueError("Invalid event ID or kind")
        if witnessed is not True and witnessed is not False:
            raise ValueError("witnessed must be a boolean")
        if witnessed != (source_robot == robot_id):
            raise ValueError("Only this robot's own sensor observations are witnessed")
        if relay_token is not None and (
            witnessed or type(relay_token) is not str
            or _RELAY_TOKEN.fullmatch(relay_token) is None
        ):
            raise ValueError("Only a secondhand copy can carry a relay receipt")
        if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 300:
            raise ValueError("Bounded nonempty description required")
        if "\x00" in summary:
            raise ValueError("Invalid description")
        when = time.time() if observed_at is None else observed_at
        if not isinstance(when, (int, float)) or isinstance(when, bool) or not 0 <= when < 1e12:
            raise ValueError("Invalid observation clock")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("Confidence outside [0,1]")
        # NaN does not compare within any numeric interval. Report it as
        # nonfinite before the finite [0,1] range check so invalid data
        # cannot masquerade as an ordinary low-confidence observation.
        # A massive integer can OverflowError when passed to math.isfinite.
        # Reject nonfinite floats explicitly, bound ints before conversion,
        # and preserve the distinct nonfinite diagnostic for NaN and Infinity.
        if isinstance(confidence, float) and not math.isfinite(confidence):
            raise ValueError("Nonfinite timestamp or confidence")
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence outside [0,1]")
        if not math.isfinite(when):
            raise ValueError("Nonfinite timestamp or confidence")
        # A bad device clock or replayed future event must not outrank genuine
        # observations forever or evict them from the bounded 250-row store.
        # Historical events remain importable; only impossible future times
        # beyond a small clock-skew allowance are rejected.
        if when > time.time() + 60:
            raise ValueError("Observation timestamp exceeds local clock")
        if camera_provenance is not None:
            if type(camera_provenance) is not CameraProvenance:
                raise ValueError("Invalid camera provenance type")
            received = camera_provenance.received_at
            interpreted = camera_provenance.interpreted_at
            if (type(received) not in (int, float)
                    or type(interpreted) not in (int, float)
                    # Bound integers before math.isfinite can convert them
                    # to float; huge device clocks must fail as ValueError.
                    or not 0 <= received <= interpreted <= time.time() + 60
                    or not math.isfinite(received) or not math.isfinite(interpreted)
                    or abs(float(when) - received) > 0.01):
                raise ValueError("Invalid camera chronology or receive clock")
            identity = camera_provenance.source_identity
            if identity is not None and (
                type(identity) is not tuple or len(identity) != 3
                or any(type(value) is not int for value in identity)
                or not 0 <= identity[0] <= 0xffffffff
                or not 1 <= identity[1] <= 0xffffffff
                or not 1 <= identity[2] <= 0xffffffffffffffff
            ):
                raise ValueError("Invalid camera device completion identity")
        with self._connect(robot_id) as db:
            # Begin before checking the tombstone: the competing operator
            # DELETE and a delayed remembered event must have ONE order.
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT writes_sealed FROM deletion_fence_guard WHERE singleton=1"
            ).fetchone() != (0,):
                # A bounded tombstone table cannot faithfully represent an
                # unbounded event-ID set. Reject every new episode write
                # instead of forgetting an old operator deletion.
                raise MemoryWriteSealed(
                    "Private episode writes sealed after deletion fence budget"
                )
            if db.execute(
                "SELECT 1 FROM deleted_episode_ids WHERE event_id=?",
                (event_id,),
            ).fetchone() is not None:
                return False
            cursor = db.execute(
                """INSERT OR IGNORE INTO memories
                   (event_id,source_robot,witnessed,kind,summary,observed_at,confidence,relay_token)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    event_id, source_robot, int(witnessed), kind, summary.strip(),
                    float(when), float(confidence), relay_token,
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
            if cursor.rowcount != 1:
                return False
            # An old but previously unseen episode can be inserted and
            # immediately evicted by the 250-row retention policy. Report
            # persisted evidence, not merely a successful INSERT, so callers
            # cannot share a fact the eyewitness pet no longer remembers.
            retained = db.execute(
                "SELECT 1 FROM memories WHERE event_id=?", (event_id,),
            ).fetchone() is not None
            if retained and camera_provenance is not None:
                identity = camera_provenance.source_identity
                db.execute(
                    """INSERT INTO camera_provenance
                       (event_id,mac_received_at,interpreted_at,
                        device_boot,device_frame,device_complete_us)
                       VALUES (?,?,?,?,?,?)""",
                    (event_id, camera_provenance.received_at,
                     camera_provenance.interpreted_at,
                     identity[0] if identity is not None else None,
                     identity[1] if identity is not None else None,
                     str(identity[2]) if identity is not None else None),
                )
            return retained

    def retract_peer_copy(
        self, robot_id: str, event_id: str, relay_token: str,
    ) -> bool:
        """Conditionally undo an internal relay without an operator tombstone.

        The unique pending-insert receipt protects newer copies and explicit
        corrections from a late cancelled sharing task.
        """
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        if type(relay_token) is not str or _RELAY_TOKEN.fullmatch(relay_token) is None:
            raise ValueError("Invalid secondhand relay receipt")
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            return db.execute(
                """DELETE FROM memories
                   WHERE event_id=? AND witnessed=0 AND relay_token=?""",
                (event_id, relay_token),
            ).rowcount == 1

    def get_episode(self, robot_id: str, event_id: str) -> Memory | None:
        """Look up one retained episode by ID without leaking peer history.

        An event can be older than the 50-row recent-view cap while still
        present in the complete 250-row per-pet store. This read does not
        resurrect deleted or trimmed episodes.
        """
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        with self._connect(robot_id) as db:
            row = db.execute(
                """SELECT event_id,source_robot,witnessed,kind,summary,
                          observed_at,confidence FROM memories
                   WHERE event_id=?""",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        event, source, witnessed, kind, summary, at, score = row
        return Memory(robot_id, event, source, bool(witnessed),
                      kind, summary, at, score)

    def witnessed_episode_revision(
        self, robot_id: str, event_id: str,
    ) -> tuple[str, int] | None:
        """Return one retained eyewitness summary and edit/delete generation.

        A pending automatic text fanout must not publish an old description
        after the operator changes or deletes the source. Both fields come
        from one private SQLite read; no peer's memories are inspected.
        """
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        with self._connect(robot_id) as db:
            row = db.execute(
                """SELECT m.summary, COALESCE(e.generation,0)
                   FROM memories AS m
                   LEFT JOIN episode_mutations AS e ON e.event_id=m.event_id
                   WHERE m.event_id=? AND m.source_robot=? AND m.witnessed=1""",
                (event_id, robot_id),
            ).fetchone()
        return (str(row[0]), int(row[1])) if row is not None else None

    def get_camera_provenance(
        self, robot_id: str, event_id: str,
    ) -> CameraProvenance | None:
        """Read only an active camera episode from one pet's local database."""
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        with self._connect(robot_id) as db:
            row = db.execute(
                """SELECT p.mac_received_at,p.interpreted_at,
                          p.device_boot,p.device_frame,p.device_complete_us
                   FROM camera_provenance AS p JOIN memories AS m
                   ON p.event_id=m.event_id WHERE p.event_id=?""",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        received, interpreted, boot, frame, complete = row
        identity = ((int(boot), int(frame), int(complete))
                    if boot is not None else None)
        return CameraProvenance(received, interpreted, identity)

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
        """Search only this pet's SQLite FTS5 index; never mix peer memories.

        Porter unicode61 and BM25 are the proven local SQLite implementation.
        Stored confidence, witnessed/secondhand provenance and event age
        remain secondary ranking signals. Empty matches invent nothing.
        """
        if type(robot_id) is not str or robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 240
                or "\x00" in query or type(limit) is not int
                or not 1 <= limit <= 12):
            raise ValueError("Bounded memory question and limit required")
        expression = _fts_query(query)
        if not expression:
            return []
        with self._connect(robot_id) as db:
            rows = db.execute(
                """SELECT m.event_id,m.source_robot,m.witnessed,m.kind,m.summary,
                          m.observed_at,m.confidence,bm25(memories_fts,1.0,0.5)
                   FROM memories_fts
                   JOIN memories AS m ON m.rowid = memories_fts.rowid
                   WHERE memories_fts MATCH ? LIMIT 250""",
                (expression,),
            ).fetchall()
        now = time.time()
        ranked = []
        for event_id, source, witnessed, kind, summary, at, confidence, relevance in rows:
            age_days = max(0.0, now - at) / 86400
            # BM25 scores are lower for better matches. Quantize tiny
            # floating noise so confidence, firsthand source and recency
            # fairly break equal-ranking topical results.
            rank = (
                round(-float(relevance), 6),
                float(confidence) + (0.25 if witnessed else 0)
                + 0.25 / (1 + age_days / 14),
                at, event_id,
            )
            ranked.append((
                rank, Memory(robot_id, event_id, source, bool(witnessed),
                             kind, summary, at, confidence),
            ))
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        return [memory for _, memory in ranked[:limit]]

    def reserve_core_fact_mutation(
        self, robot_id: str, slot: str, value: str | None = None,
    ) -> int:
        """Order one operator request before its asynchronous SQLite write."""
        if type(robot_id) is not str or robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        if type(slot) is not str or not _CORE_SLOT.fullmatch(slot):
            raise ValueError("Invalid core memory slot")
        if value is not None and (
            not isinstance(value, str) or not 1 <= len(value.strip()) <= 200
            or "\x00" in value
        ):
            raise ValueError("Invalid bounded core memory value")
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            return self._advance_core_mutation(db, slot)

    @staticmethod
    def _advance_core_mutation(db: sqlite3.Connection, slot: str) -> int:
        old = db.execute(
            "SELECT generation FROM core_fact_mutations WHERE slot=?", (slot,)
        ).fetchone()
        if old is not None and old[0] >= _MAX_MUTATION_GENERATION:
            raise ValueError("Core memory generation exhausted")
        generation = 1 if old is None else old[0] + 1
        db.execute(
            """INSERT INTO core_fact_mutations(slot,generation) VALUES (?,?)
               ON CONFLICT(slot) DO UPDATE SET generation=excluded.generation""",
            (slot, generation),
        )
        return generation

    @classmethod
    def _require_core_mutation(
        cls, db: sqlite3.Connection, slot: str, generation: int | None,
    ) -> None:
        if generation is None:
            cls._advance_core_mutation(db, slot)
            return
        if type(generation) is not int or not 1 <= generation <= _MAX_MUTATION_GENERATION:
            raise ValueError("Invalid core memory mutation generation")
        current = db.execute(
            "SELECT generation FROM core_fact_mutations WHERE slot=?", (slot,)
        ).fetchone()
        if current != (generation,):
            raise CoreMemoryMutationSuperseded(
                "A newer operator memory mutation superseded this request"
            )

    def set_core_fact(
        self, robot_id: str, slot: str, value: str, *,
        mutation_generation: int | None = None,
    ) -> bool:
        """Curate one long-lived preference; ONLY operator API may invoke.

        No model/tool automatically edits identity, user preferences or safety
        policy. This bounded core is separate from ephemeral episodes.
        """
        if type(robot_id) is not str or robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        if type(slot) is not str or not _CORE_SLOT.fullmatch(slot):
            raise ValueError("Invalid core memory slot")
        if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 200
                or "\x00" in value):
            raise ValueError("Invalid bounded core memory value")
        clean = " ".join(value.split())
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_core_mutation(db, slot, mutation_generation)
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

    def forget_core_fact(
        self, robot_id: str, slot: str, *,
        mutation_generation: int | None = None,
    ) -> bool:
        if type(slot) is not str or not _CORE_SLOT.fullmatch(slot):
            raise ValueError("Invalid core memory slot")
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_core_mutation(db, slot, mutation_generation)
            return db.execute(
                "DELETE FROM core_facts WHERE slot=?", (slot,)
            ).rowcount == 1

    def reserve_episode_mutation(
        self, robot_id: str, event_id: str, summary: str | None = None,
    ) -> int:
        """Order the authenticated request before its offloaded SQLite write."""
        if type(robot_id) is not str or robot_id not in self.robot_ids:
            raise ValueError("Unknown robot memory identity")
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        if summary is not None and (
            not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 300
            or "\x00" in summary
        ):
            raise ValueError("Bounded nonempty description required")
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            return self._advance_episode_mutation(db, event_id)

    @staticmethod
    def _advance_episode_mutation(db: sqlite3.Connection, event_id: str) -> int:
        old = db.execute(
            "SELECT generation FROM episode_mutations WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if old is not None and old[0] >= _MAX_MUTATION_GENERATION:
            raise ValueError("Episode memory generation exhausted")
        generation = 1 if old is None else old[0] + 1
        db.execute(
            """INSERT INTO episode_mutations(event_id,generation) VALUES (?,?)
               ON CONFLICT(event_id) DO UPDATE SET generation=excluded.generation""",
            (event_id, generation),
        )
        return generation

    @classmethod
    def _require_episode_mutation(
        cls, db: sqlite3.Connection, event_id: str, generation: int | None,
    ) -> None:
        if generation is None:
            # Direct local corrections and safety deletions also retire an
            # older pending API correction without losing their semantics.
            cls._advance_episode_mutation(db, event_id)
            return
        if type(generation) is not int or not 1 <= generation <= _MAX_MUTATION_GENERATION:
            raise ValueError("Invalid episode memory mutation generation")
        current = db.execute(
            "SELECT generation FROM episode_mutations WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if current != (generation,):
            raise EpisodeMemoryMutationSuperseded(
                "A newer operator episode mutation superseded this request"
            )

    def correct_episode(
        self, robot_id: str, event_id: str, summary: str, *,
        mutation_generation: int | None = None,
    ) -> bool:
        """Correct local episode text without rewriting its evidence provenance."""
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        if (not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 300
                or "\x00" in summary):
            raise ValueError("Bounded nonempty description required")
        clean = summary.strip()
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_episode_mutation(db, event_id, mutation_generation)
            current = db.execute(
                "SELECT summary FROM memories WHERE event_id=?", (event_id,)
            ).fetchone()
            if current is None:
                return False
            if current[0] == clean:
                # Human reaffirmation is no longer owned by a stale relay.
                db.execute(
                    "UPDATE memories SET relay_token=NULL "
                    "WHERE event_id=? AND relay_token IS NOT NULL", (event_id,),
                )
                return False
            # Only the operator-correctable description changes. Event identity,
            # source, firsthand/peer attribution, kind, time and confidence stay
            # immutable, and the existing FTS UPDATE trigger refreshes search.
            return db.execute(
                "UPDATE memories SET summary=?,relay_token=NULL WHERE event_id=?",
                (clean, event_id),
            ).rowcount == 1

    def forget_episode(
        self, robot_id: str, event_id: str, *,
        mutation_generation: int | None = None,
    ) -> bool:
        """Explicit per-pet deletion; does not silently mutate peer memories."""
        if type(event_id) is not str or not _EVENT_ID.fullmatch(event_id):
            raise ValueError("Invalid memory event ID")
        with self._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_episode_mutation(db, event_id, mutation_generation)
            # Even a deletion arriving before a slow SQLite writer creates a
            # durable fence. Never copy a peer's deletion to this pet's DB.
            sealed = db.execute(
                "SELECT writes_sealed FROM deletion_fence_guard WHERE singleton=1"
            ).fetchone() != (0,)
            if not sealed:
                db.execute(
                    "INSERT OR IGNORE INTO deleted_episode_ids(event_id) VALUES (?)",
                    (event_id,),
                )
                if db.execute(
                    "SELECT COUNT(*) FROM deleted_episode_ids"
                ).fetchone()[0] >= _MAX_DELETED_EPISODE_IDS:
                    # Permanently bound this robot's deletion registry.
                    # No later remember() may insert anything, including
                    # an ID deleted after saturation. Both operations hold
                    # the same BEGIN IMMEDIATE writer lease.
                    db.execute(
                        "UPDATE deletion_fence_guard SET writes_sealed=1 "
                        "WHERE singleton=1"
                    )
            return db.execute(
                "DELETE FROM memories WHERE event_id=?", (event_id,)
            ).rowcount == 1

    def count(self, robot_id: str) -> int:
        with self._connect(robot_id) as db:
            return int(db.execute("SELECT count(*) FROM memories").fetchone()[0])

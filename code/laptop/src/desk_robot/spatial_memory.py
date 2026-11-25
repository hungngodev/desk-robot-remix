"""Spatial sidecar for the existing private, per-pet MemoryStore SQLite.

Only retained firsthand episodes may acquire spatial provenance. This module
never writes raw JPEGs, grants movement, or promotes odometry to an anchored map.
Original episode deletion and rolling retention remove this sidecar via the
MemoryStore schema trigger. Producer authentication remains with Mac transport.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import MemoryStore

_OBJECT_KEY = re.compile(r"[a-z0-9][a-z0-9_:-]{0,63}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
_MAX_I64 = (1 << 63) - 1


@dataclass(frozen=True)
class SpatialEvidence:
    object_key: str
    observed_at: float  # local wall clock, already admitted by MemoryStore
    body_boot: int
    origin_id: str
    pose_seq: int
    pose_sample_us: int
    camera_boot: int
    camera_seq: int
    camera_complete_us: int
    calibration_id: str
    x_mm: int
    y_mm: int
    yaw_mrad: int
    uncertainty_mm: int
    frame: str = "odom"
    anchor_id: str | None = None


@dataclass(frozen=True)
class SpatialSighting:
    event_id: str
    evidence: SpatialEvidence
    status: str  # pending_localization, historical, live, stale, invalid_origin


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _validate(e: SpatialEvidence) -> None:
    if (type(e) is not SpatialEvidence or type(e.object_key) is not str
            or not _OBJECT_KEY.fullmatch(e.object_key)):
        raise ValueError("Invalid spatial object identity")
    # Compare bounded numeric values before any conversion to SQLite REAL.
    # Chained bounds also reject NaN and infinities without integer overflow.
    if (type(e.observed_at) not in (float, int)
            or not 0 <= e.observed_at <= time.time() + 60):
        raise ValueError("Invalid spatial observation wall clock")
    if (not _integer(e.body_boot, 0, 0xffffffff)
            or type(e.origin_id) is not str or not _TOKEN.fullmatch(e.origin_id)
            or not _integer(e.pose_seq, 1, 0xffffffff)
            or not _integer(e.pose_sample_us, 1, _MAX_I64)
            or not _integer(e.camera_boot, 0, 0xffffffff)
            or not _integer(e.camera_seq, 1, 0xffffffff)
            or not _integer(e.camera_complete_us, 1, _MAX_I64)
            or type(e.calibration_id) is not str
            or not _TOKEN.fullmatch(e.calibration_id)):
        raise ValueError("Invalid spatial frame identity or calibration")
    if (not _integer(e.x_mm, -1_000_000, 1_000_000)
            or not _integer(e.y_mm, -1_000_000, 1_000_000)
            or not _integer(e.yaw_mrad, -3142, 3142)
            or not _integer(e.uncertainty_mm, 1, 1_000_000)):
        raise ValueError("Invalid spatial coordinate or uncertainty")
    if type(e.frame) is not str or e.frame != "odom" or e.anchor_id is not None:
        # A caller cannot self-assert a map anchor without Guide 50's future
        # stationary JPEG/pose bracket and validated measured-tag receipt.
        raise ValueError("Unverified map anchoring not accepted")


class SpatialMemory:
    """Read and annotate the existing episode store without a second DB."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def attach(self, robot_id: str, event_id: str, evidence: SpatialEvidence) -> bool:
        """Transactionally attach metadata only to one existing eyewitness event.

        A deleted, expired or unretained episode can never be resurrected by a
        late camera callback. Duplicate frames or event IDs cannot rewrite a
        newer observation. Origin and frame IDs remain independently queryable.
        """
        _validate(evidence)
        if type(event_id) is not str or not _TOKEN.fullmatch(event_id):
            raise ValueError("Invalid source memory event ID")
        with self.memory._connect(robot_id) as db:
            db.execute("BEGIN IMMEDIATE")
            episode = db.execute(
                """SELECT m.source_robot, m.witnessed, m.observed_at,
                          p.device_boot, p.device_frame, p.device_complete_us,
                          COALESCE(e.generation,0), p.mac_received_at
                   FROM memories AS m
                   LEFT JOIN camera_provenance AS p ON p.event_id=m.event_id
                   LEFT JOIN episode_mutations AS e ON e.event_id=m.event_id
                   WHERE m.event_id=?""",
                (event_id,),
            ).fetchone()
            if episode is None:
                return False
            if (episode[0] != robot_id or episode[1] != 1
                    or abs(episode[2] - evidence.observed_at) > 0.01):
                raise ValueError("Spatial evidence requires same-robot firsthand episode time")
            # A corrected or mutation-reserved episode cannot regain old
            # coordinates from a delayed callback, even across restarts.
            # The retained camera receipt must match exactly; no clock mapping
            # between the camera and Mac is invented here.
            if (episode[6] != 0
                    or episode[3:6] != (evidence.camera_boot, evidence.camera_seq,
                                        str(evidence.camera_complete_us))
                    or episode[7] is None
                    or abs(episode[7] - evidence.observed_at) > 0.01):
                return False
            # Camera sequence identifies an image independently of completion timestamp.
            # The same image can depict several objects, but cannot create a
            # second sighting of one object just by changing complete_us.
            # BEGIN IMMEDIATE makes this check atomic with the insert on legacy DBs.
            if db.execute(
                """SELECT 1 FROM spatial_observations
                   WHERE object_key=? AND camera_boot=? AND camera_seq=?
                   LIMIT 1""",
                (evidence.object_key, evidence.camera_boot, evidence.camera_seq),
            ).fetchone() is not None:
                return False
            row = db.execute(
                """INSERT OR IGNORE INTO spatial_observations
                   (event_id,object_key,observed_at,body_boot,origin_id,
                    pose_seq,pose_sample_us,camera_boot,camera_seq,
                    camera_complete_us,calibration_id,x_mm,y_mm,yaw_mrad,
                    uncertainty_mm,frame,anchor_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, evidence.object_key, float(evidence.observed_at),
                 evidence.body_boot, evidence.origin_id, evidence.pose_seq,
                 evidence.pose_sample_us, evidence.camera_boot, evidence.camera_seq,
                 str(evidence.camera_complete_us), evidence.calibration_id,
                 evidence.x_mm, evidence.y_mm, evidence.yaw_mrad,
                 evidence.uncertainty_mm, evidence.frame, evidence.anchor_id),
            )
            return row.rowcount == 1

    def last_seen(
        self, robot_id: str, object_key: str, *, now: float,
        current_origin: tuple[int, str] | None = None,
        current_camera: tuple[int, int, int] | None = None,
        live_age_s: float = 0.25, history_age_s: float = 86400.0,
    ) -> SpatialSighting | None:
        """Return historical evidence with an explicit reason not to navigate.

        A current same-camera receipt alone does not anchor a map. Consumers
        must not treat 'pending_localization' as a metric target or arrival.
        """
        if type(object_key) is not str or not _OBJECT_KEY.fullmatch(object_key):
            raise ValueError("Invalid object key")
        if (type(now) not in (float, int) or not 0 <= now < 1e12
                or type(live_age_s) not in (float, int)
                or type(history_age_s) not in (float, int)
                or not 0 < live_age_s <= 1 or not live_age_s <= history_age_s <= 31_536_000):
            raise ValueError("Invalid spatial read clock or age budget")
        if current_origin is not None and (
                type(current_origin) is not tuple or len(current_origin) != 2
                or not _integer(current_origin[0], 0, 0xffffffff)
                or type(current_origin[1]) is not str
                or not _TOKEN.fullmatch(current_origin[1])):
            raise ValueError("Invalid current body origin")
        if current_camera is not None and (
                type(current_camera) is not tuple or len(current_camera) != 3
                or not _integer(current_camera[0], 0, 0xffffffff)
                or not _integer(current_camera[1], 1, 0xffffffff)
                or not _integer(current_camera[2], 1, _MAX_I64)):
            raise ValueError("Invalid current camera receipt")
        # Until a qualified anchor producer exists, durable reads must enforce
        # the same frame admission as attach, before selecting the newest row.
        with self.memory._connect(robot_id) as db:
            row = db.execute(
                """SELECT s.event_id,s.object_key,s.observed_at,s.body_boot,
                          s.origin_id,s.pose_seq,s.pose_sample_us,s.camera_boot,
                          s.camera_seq,s.camera_complete_us,s.calibration_id,
                          s.x_mm,s.y_mm,s.yaw_mrad,s.uncertainty_mm,
                          s.frame,s.anchor_id
                   FROM spatial_observations AS s JOIN memories AS m
                   ON s.event_id=m.event_id
                   JOIN camera_provenance AS p ON p.event_id=m.event_id
                   LEFT JOIN episode_mutations AS e ON e.event_id=m.event_id
                   WHERE s.object_key=? AND m.source_robot=? AND m.witnessed=1
                   AND COALESCE(e.generation,0)=0
                   AND s.frame='odom' AND s.anchor_id IS NULL
                   AND p.device_boot=s.camera_boot AND p.device_frame=s.camera_seq
                   AND p.device_complete_us=s.camera_complete_us
                   AND ABS(m.observed_at-s.observed_at)<=0.01
                   AND ABS(p.mac_received_at-s.observed_at)<=0.01
                   ORDER BY s.observed_at DESC,s.event_id DESC LIMIT 1""",
                (object_key, robot_id),
            ).fetchone()
        if row is None:
            return None
        (event_id, obj, observed, boot, origin, pose_seq, pose_time,
         camera_boot, camera_seq, complete, calibration, x, y, yaw, uncertainty,
         frame, anchor) = row
        # SQLite affinities are not strict types. Never decode malformed
        # durable receipt IDs or expose invalid coordinates from a legacy row.
        if (type(event_id) is not str or not _TOKEN.fullmatch(event_id)
                or type(complete) is not str or not 1 <= len(complete) <= 19
                or not complete.isascii() or not complete.isdigit()
                or complete.startswith("0")):
            return None
        evidence = SpatialEvidence(
            object_key=obj, observed_at=observed, body_boot=boot,
            origin_id=origin, pose_seq=pose_seq, pose_sample_us=pose_time,
            camera_boot=camera_boot, camera_seq=camera_seq,
            camera_complete_us=int(complete), calibration_id=calibration,
            x_mm=x, y_mm=y, yaw_mrad=yaw, uncertainty_mm=uncertainty,
            frame=frame, anchor_id=anchor,
        )
        try:
            _validate(evidence)
        except ValueError:
            # Fail closed rather than inventing an older location.
            return None
        elapsed = now - observed
        if current_origin is not None and current_origin != (boot, origin):
            status = "invalid_origin"
        elif not 0 <= elapsed <= history_age_s:
            status = "stale"
        elif evidence.frame != "map" or not evidence.anchor_id:
            status = "pending_localization"
        elif (current_camera == (camera_boot, camera_seq, int(complete))
              and elapsed <= live_age_s):
            status = "live"
        else:
            status = "historical"
        return SpatialSighting(event_id, evidence, status)

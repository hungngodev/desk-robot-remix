"""Read-only, source-qualified object recall for a single active robot turn.

This accepts typed observations from the future per-robot spatial store. It
never decodes camera frames, manufactures floor projection, or permits motion.
A remembered position is only a search hint, never proof of arrival.
"""

from __future__ import annotations

from dataclasses import dataclass

_SOURCES = frozenset({"camera_seen", "camera_not_seen", "user_reported"})


@dataclass(frozen=True)
class ObjectQuery:
    robot_id: str
    label: str
    session_id: str
    turn_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    calibration_id: str
    camera_boot: int
    host_boot_id: str  # Mac monotonic clock boot, not Sense boot.
    camera_grant: int  # Bump on every consent revoke/regrant.
    created_us: int
    deadline_us: int
    cancelled: bool = False


@dataclass(frozen=True)
class ObjectOwner:
    """Fresh identities from the live turn, map, and camera owners."""

    robot_id: str
    session_id: str
    turn_id: str
    origin_id: str
    epoch: int
    anchor_id: str
    calibration_id: str
    camera_boot: int
    host_boot_id: str
    camera_grant: int
    camera_allowed: bool
    memory_allowed: bool


@dataclass(frozen=True)
class ObjectEvidence:
    robot_id: str
    label: str
    source: str  # camera_seen, camera_not_seen, user_reported
    seen_at_wall_s: float  # Descriptive only, never used for live freshness.
    receipt_us: int | None = None  # Trusted Mac monotonic receipt, same host boot.
    origin_id: str | None = None
    epoch: int | None = None
    anchor_id: str | None = None
    calibration_id: str | None = None
    camera_boot: int | None = None
    host_boot_id: str | None = None
    camera_grant: int | None = None
    frame_seq: int | None = None
    floor_mm: tuple[int, int] | None = None
    projection_qualified: bool = False
    confidence: float = 0.0


@dataclass(frozen=True)
class ObjectTarget:
    status: str  # current_sighting, last_seen, user_reported, unknown, rejected
    reason: str
    robot_id: str
    label: str
    source: str | None = None
    seen_at_wall_s: float | None = None
    confirmed_floor_mm: tuple[int, int] | None = None
    search_hint_mm: tuple[int, int] | None = None
    may_execute: bool = False
    arrived: bool = False
    # Bind a resolved target to the exact request. A historical floor hint
    # alone does not authorize reuse after another turn, map or camera grant.
    request_fence: ObjectQuery | None = None


def _identity(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= 96


def _label(value: object) -> bool:
    return (_identity(value) and len(value) <= 64
            and value[0].isalpha()
            and all(c.isascii() and (c.isalnum() or c in " _") for c in value))


def _floor(value: object) -> bool:
    return (isinstance(value, tuple) and len(value) == 2
            and all(type(v) is int and -100_000 <= v <= 100_000 for v in value))


def _valid_evidence(e: object) -> bool:
    if not isinstance(e, ObjectEvidence):
        return False
    if (not _identity(e.robot_id) or not _label(e.label)
            or type(e.source) is not str or e.source not in _SOURCES
            or type(e.seen_at_wall_s) not in (float, int)
            or not 0 <= e.seen_at_wall_s <= 4_102_444_800
            or type(e.confidence) not in (float, int)
            or not 0 <= e.confidence <= 1
            or e.projection_qualified is not True and e.projection_qualified is not False):
        return False
    if e.source == "user_reported":
        # A human report never silently acquires a camera, pose or metric proof.
        return (e.receipt_us is None and e.camera_boot is None
                and e.host_boot_id is None and e.camera_grant is None
                and e.frame_seq is None and e.floor_mm is None
                and e.projection_qualified is False)
    return (type(e.receipt_us) is int and e.receipt_us >= 0
            and type(e.camera_boot) is int and 0 <= e.camera_boot <= 0xFFFFFFFF
            and _identity(e.host_boot_id)
            and type(e.camera_grant) is int and 0 <= e.camera_grant <= 0xFFFFFFFF
            and type(e.frame_seq) is int and e.frame_seq > 0
            and _identity(e.origin_id) and type(e.epoch) is int and e.epoch >= 0
            and _identity(e.anchor_id) and _identity(e.calibration_id)
            and (e.floor_mm is None or _floor(e.floor_mm))
            and (e.source != "camera_not_seen" or
                 (e.floor_mm is None and e.projection_qualified is False)))


def resolve_object_target(
    query: ObjectQuery,
    owner: ObjectOwner,
    evidence: tuple[ObjectEvidence, ...] | list[ObjectEvidence],
    *,
    now_us: int,
    fresh_us: int = 250_000,
    min_confidence: float = 0.75,
) -> ObjectTarget:
    """Resolve evidence without granting actuation or declaring arrival.

    The owner must be obtained *after* the request starts and checked again by
    the caller after any await. The caller must also reject a superseded owner
    before planning or dispatch, even if this synchronous result was valid.
    """
    def result(status: str, reason: str, selected: ObjectEvidence | None = None,
               *, confirmed: tuple[int, int] | None = None,
               hint: tuple[int, int] | None = None) -> ObjectTarget:
        return ObjectTarget(status, reason,
                            query.robot_id if isinstance(query, ObjectQuery) else "",
                            query.label if isinstance(query, ObjectQuery) else "",
                            selected.source if selected else None,
                            selected.seen_at_wall_s if selected else None,
                            confirmed, hint,
                            request_fence=query if status != "rejected" else None)

    if (not isinstance(query, ObjectQuery) or not isinstance(owner, ObjectOwner)
            or not all(_identity(s) for s in (
                query.robot_id, query.session_id, query.turn_id, query.origin_id,
                query.anchor_id, query.calibration_id, query.host_boot_id,
                owner.robot_id, owner.host_boot_id,
                owner.session_id, owner.turn_id, owner.origin_id,
                owner.anchor_id, owner.calibration_id))
            or not _label(query.label)
            or any(type(x) is not int for x in (
                query.epoch, query.camera_boot, query.camera_grant,
                query.created_us, query.deadline_us,
                owner.epoch, owner.camera_boot, owner.camera_grant, now_us, fresh_us))
            or min(query.epoch, query.camera_boot, query.camera_grant,
                   query.created_us, owner.epoch, owner.camera_boot,
                   owner.camera_grant, now_us) < 0
            or not 1 <= fresh_us <= 5_000_000
            or type(min_confidence) not in (int, float)
            or not 0 < min_confidence <= 1
            or type(query.cancelled) is not bool
            or type(owner.camera_allowed) is not bool
            or type(owner.memory_allowed) is not bool
            or not isinstance(evidence, (tuple, list)) or len(evidence) > 128):
        return result("rejected", "invalid_request_or_evidence_budget")
    if query.cancelled:
        return result("rejected", "cancelled")
    if query.created_us > now_us or query.deadline_us <= now_us:
        return result("rejected", "deadline_or_clock_invalid")
    if ((query.robot_id, query.session_id, query.turn_id) !=
            (owner.robot_id, owner.session_id, owner.turn_id)):
        return result("rejected", "turn_or_robot_changed")
    if ((query.origin_id, query.epoch, query.anchor_id, query.calibration_id,
         query.camera_boot, query.host_boot_id, query.camera_grant) !=
            (owner.origin_id, owner.epoch, owner.anchor_id, owner.calibration_id,
             owner.camera_boot, owner.host_boot_id, owner.camera_grant)):
        return result("rejected", "origin_map_or_camera_changed")
    if not owner.memory_allowed:
        return result("rejected", "memory_consent_revoked")

    # Reject evidence from another robot even if a store accidentally mixes rows.
    records = [e for e in evidence if _valid_evidence(e)
               and e.robot_id == query.robot_id and e.label == query.label]
    seen = [e for e in records if e.source == "camera_seen"
            and e.confidence >= min_confidence]
    reports = [e for e in records if e.source == "user_reported"]

    def same_map(e: ObjectEvidence) -> bool:
        return ((e.origin_id, e.epoch, e.anchor_id, e.calibration_id) ==
                (query.origin_id, query.epoch, query.anchor_id,
                 query.calibration_id))

    def fresh(e: ObjectEvidence) -> bool:
        return (owner.camera_allowed and same_map(e)
                and e.camera_boot == query.camera_boot
                and e.host_boot_id == query.host_boot_id
                and e.camera_grant == query.camera_grant
                and e.receipt_us is not None
                and query.created_us <= e.receipt_us <= now_us
                and now_us - e.receipt_us <= fresh_us)

    positives = [e for e in seen if fresh(e)]
    negatives = [e for e in records if e.source == "camera_not_seen" and fresh(e)]
    latest_seen = max(positives, key=lambda e: (e.receipt_us, e.frame_seq),
                      default=None)
    latest_absent = max(negatives, key=lambda e: (e.receipt_us, e.frame_seq),
                        default=None)
    if (latest_seen is not None and (latest_absent is None or
            (latest_seen.receipt_us, latest_seen.frame_seq) >
            (latest_absent.receipt_us, latest_absent.frame_seq))):
        if latest_seen.projection_qualified and latest_seen.floor_mm is not None:
            return result("current_sighting", "fresh_projected_view", latest_seen,
                          confirmed=latest_seen.floor_mm)
        return result("current_sighting", "fresh_view_no_metric_projection", latest_seen)

    # Historical observations cannot prove where a moved/hidden target is now.
    # A later user correction takes precedence but stays explicitly reported.
    past = max(seen, key=lambda e: e.seen_at_wall_s, default=None)
    report = max(reports, key=lambda e: e.seen_at_wall_s, default=None)
    if report is not None and (past is None or report.seen_at_wall_s > past.seen_at_wall_s):
        return result("user_reported", "unverified_user_location", report)
    if past is not None:
        hint = (past.floor_mm if past.projection_qualified and
                past.floor_mm is not None and same_map(past) else None)
        reason = "not_currently_confirmed" if latest_absent else "historical_sighting_only"
        return result("last_seen", reason, past, hint=hint)
    if report is not None:
        return result("user_reported", "unverified_user_location", report)
    return result("unknown", "no_qualified_observation")


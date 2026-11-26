"""Read-only, source-qualified object recall for a single active robot turn.

This accepts typed observations from the future per-robot spatial store. It
never decodes camera frames, manufactures floor projection, or permits motion.
A remembered position is only a search hint, never proof of arrival.
A qualified 2D floor projection does not measure object thickness, jaw height,
or swept clearance. Pickup must independently qualify its physical geometry.
"""

from __future__ import annotations

from dataclasses import dataclass

# Historical descriptions outlive metric search hints. Use the original capture clock.
MAX_SEARCH_HINT_AGE_US = 30_000_000

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
    # Original capture mapped to the same Mac monotonic host boot. Legacy
    # receipt-only evidence may be historical but never a current sighting.
    captured_us: int | None = None


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
    return type(value) is str and 0 < len(value) <= 96 and "\x00" not in value


def _label(value: object) -> bool:
    return (_identity(value) and len(value) <= 64
            and value[0].isalpha()
            and all(c.isascii() and (c.isalnum() or c in " _") for c in value))


def _valid_request_identity(query: object, owner: object) -> bool:
    """Validate identities before equality checks or any camera inference."""
    return (isinstance(query, ObjectQuery) and isinstance(owner, ObjectOwner)
            and all(_identity(s) for s in (
                query.robot_id, query.session_id, query.turn_id, query.origin_id,
                query.anchor_id, query.calibration_id, query.host_boot_id,
                owner.robot_id, owner.session_id, owner.turn_id, owner.origin_id,
                owner.anchor_id, owner.calibration_id, owner.host_boot_id))
            and _label(query.label)
            and all(type(x) is int and x >= 0 for x in (query.epoch, owner.epoch))
            and all(type(x) is int and 0 <= x <= 0xFFFFFFFF for x in (
                query.camera_boot, query.camera_grant, owner.camera_boot, owner.camera_grant))
            and type(query.cancelled) is bool
            and type(owner.camera_allowed) is bool
            and type(owner.memory_allowed) is bool)


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
        return (e.receipt_us is None and e.captured_us is None and e.camera_boot is None
                and e.host_boot_id is None and e.camera_grant is None
                and e.frame_seq is None and e.floor_mm is None
                and e.projection_qualified is False)
    return (type(e.receipt_us) is int and e.receipt_us >= 0
            and (e.captured_us is None or
                 (type(e.captured_us) is int and 0 <= e.captured_us <= e.receipt_us))
            and type(e.camera_boot) is int and 0 <= e.camera_boot <= 0xFFFFFFFF
            and _identity(e.host_boot_id)
            and type(e.camera_grant) is int and 0 <= e.camera_grant <= 0xFFFFFFFF
            and type(e.frame_seq) is int and 0 < e.frame_seq <= 0xFFFFFFFF
            and _identity(e.origin_id) and type(e.epoch) is int and e.epoch >= 0
            and _identity(e.anchor_id) and _identity(e.calibration_id)
            and (e.floor_mm is None or _floor(e.floor_mm))
            and (e.source != "camera_not_seen" or
                 (e.floor_mm is None and e.projection_qualified is False)))


def _result(
    query: ObjectQuery,
    status: str,
    reason: str,
    selected: ObjectEvidence | None = None,
    *,
    confirmed: tuple[int, int] | None = None,
    hint: tuple[int, int] | None = None,
) -> ObjectTarget:
    return ObjectTarget(status, reason,
                        query.robot_id if isinstance(query, ObjectQuery) else "",
                        query.label if isinstance(query, ObjectQuery) else "",
                        selected.source if selected else None,
                        selected.seen_at_wall_s if selected else None,
                        confirmed, hint,
                        request_fence=query if status != "rejected" else None)


def _request_rejection(
    query: ObjectQuery, owner: ObjectOwner,
    evidence: tuple[ObjectEvidence, ...] | list[ObjectEvidence],
    now_us: int, fresh_us: int, min_confidence: float,
) -> str | None:
    if (not _valid_request_identity(query, owner)
            or any(type(x) is not int for x in (
                query.created_us, query.deadline_us, now_us, fresh_us))
            or min(query.created_us, now_us) < 0
            or not 1 <= fresh_us <= 5_000_000
            or type(min_confidence) not in (int, float)
            or not 0 < min_confidence <= 1
            or not isinstance(evidence, (tuple, list)) or len(evidence) > 128):
        return "invalid_request_or_evidence_budget"
    if query.cancelled:
        return "cancelled"
    if query.created_us > now_us or query.deadline_us <= now_us:
        return "deadline_or_clock_invalid"
    if ((query.robot_id, query.session_id, query.turn_id) !=
            (owner.robot_id, owner.session_id, owner.turn_id)):
        return "turn_or_robot_changed"
    if ((query.origin_id, query.epoch, query.anchor_id, query.calibration_id,
         query.camera_boot, query.host_boot_id, query.camera_grant) !=
            (owner.origin_id, owner.epoch, owner.anchor_id, owner.calibration_id,
             owner.camera_boot, owner.host_boot_id, owner.camera_grant)):
        return "origin_map_or_camera_changed"
    if not owner.memory_allowed:
        return "memory_consent_revoked"
    return None


def _matching_records(
    query: ObjectQuery, evidence: tuple[ObjectEvidence, ...] | list[ObjectEvidence], now_us: int,
) -> list[ObjectEvidence]:
    # Reject evidence from another robot even if a store accidentally mixes rows.
    # A receipt in the future of this same Mac monotonic clock is impossible.
    # Do not downgrade it into a historical metric search hint. Other host
    # boots have incomparable monotonic clocks and remain historical only.
    return [e for e in evidence if _valid_evidence(e)
            and e.robot_id == query.robot_id and e.label == query.label
            and not (e.host_boot_id == query.host_boot_id
                     and e.receipt_us is not None and e.receipt_us > now_us)]


def _same_map(e: ObjectEvidence, query: ObjectQuery) -> bool:
    return ((e.origin_id, e.epoch, e.anchor_id, e.calibration_id) ==
            (query.origin_id, query.epoch, query.anchor_id,
             query.calibration_id))


def _fresh(
    e: ObjectEvidence, query: ObjectQuery, owner: ObjectOwner, now_us: int, fresh_us: int,
) -> bool:
    return (owner.camera_allowed and _same_map(e, query)
            and e.camera_boot == query.camera_boot
            and e.host_boot_id == query.host_boot_id
            and e.camera_grant == query.camera_grant
            and e.receipt_us is not None
            and e.captured_us is not None
            and query.created_us <= e.captured_us <= e.receipt_us <= now_us
            and now_us - e.captured_us <= fresh_us)


def _frame_identity(e: ObjectEvidence) -> tuple:
    return (e.host_boot_id, e.camera_boot, e.camera_grant, e.frame_seq,
            e.origin_id, e.epoch, e.anchor_id, e.calibration_id)


def _projected_locations(selected: ObjectEvidence, candidates: list[ObjectEvidence]) -> set:
    # Multiple detections of the same class in one frame do not identify
    # which physical object the user meant. Identical receipts may coalesce.
    return {tuple(e.floor_mm) if e.projection_qualified and e.floor_mm is not None
            else None for e in candidates
            if _frame_identity(e) == _frame_identity(selected)}


def _latest_fresh_frames(
    records: list[ObjectEvidence], seen: list[ObjectEvidence], query: ObjectQuery,
    owner: ObjectOwner, now_us: int, fresh_us: int,
) -> tuple[ObjectEvidence | None, ObjectEvidence | None]:
    positives = [e for e in seen if _fresh(e, query, owner, now_us, fresh_us)]
    negatives = [e for e in records if e.source == "camera_not_seen"
                 and _fresh(e, query, owner, now_us, fresh_us)]
    # Native camera frames are ordered by frame sequence inside one
    # authenticated camera boot. Inference can finish out of order: the
    # receipt time of an OLD frame cannot override a newer missing-object
    # frame. For conflicting results on the same frame, fail closed.
    latest_seen = max(positives, key=lambda e: (e.frame_seq, e.receipt_us),
                      default=None)
    latest_absent = max(negatives, key=lambda e: (e.frame_seq, e.receipt_us),
                        default=None)
    return latest_seen, latest_absent


def _resolve_current(
    query: ObjectQuery, seen: list[ObjectEvidence], absent_frames: set[tuple],
    latest_seen: ObjectEvidence | None, latest_absent: ObjectEvidence | None,
) -> ObjectTarget | None:
    if (latest_seen is None
            or _frame_identity(latest_seen) in absent_frames
            or (latest_absent is not None and latest_seen.frame_seq <= latest_absent.frame_seq)):
        return None
    # Freshness selects the view, not which objects existed in that view.
    # A conflicting detection from the same frame remains ambiguous even
    # if its individual receipt has aged out.
    locations = _projected_locations(latest_seen, seen)
    if len(locations) > 1:
        return _result(query, "current_sighting", "ambiguous_projected_view", latest_seen)
    if latest_seen.projection_qualified and latest_seen.floor_mm is not None:
        return _result(query, "current_sighting", "fresh_projected_view", latest_seen,
                      confirmed=latest_seen.floor_mm)
    return _result(query, "current_sighting", "fresh_view_no_metric_projection", latest_seen)


def _historical_candidates(
    seen: list[ObjectEvidence], query: ObjectQuery,
) -> list[ObjectEvidence]:
    # Historical observations cannot prove where a moved/hidden target is now.
    # A later user correction takes precedence but stays explicitly reported.
    # Wall time is descriptive and may jump backwards. Select the latest
    # frame within each authenticated stream before comparing streams.
    streams: dict[tuple, ObjectEvidence] = {}
    for observation in seen:
        stream = (observation.host_boot_id, observation.camera_boot,
                  observation.camera_grant)
        previous = streams.get(stream)
        rank = (observation.frame_seq, observation.receipt_us,
                observation.seen_at_wall_s)
        if previous is None or rank > (previous.frame_seq, previous.receipt_us,
                                       previous.seen_at_wall_s):
            streams[stream] = observation

    candidates = list(streams.values())
    # Evidence from the running host postdates prior host boots. Never compare
    # monotonic timestamps across distinct host boots.
    current_host = [e for e in candidates if e.host_boot_id == query.host_boot_id]
    if current_host:
        candidates = current_host
    return candidates


def _select_past(candidates: list[ObjectEvidence]) -> ObjectEvidence | None:
    past = candidates[0] if len(candidates) == 1 else None
    if (len(candidates) > 1
            and len({e.host_boot_id for e in candidates}) == 1
            and all(e.captured_us is not None for e in candidates)):
        latest_capture = max(e.captured_us for e in candidates)
        latest = [e for e in candidates if e.captured_us == latest_capture]
        if len(latest) == 1:
            past = latest[0]
    return past


def _resolve_past(
    query: ObjectQuery, past: ObjectEvidence, seen: list[ObjectEvidence],
    absent_frames: set[tuple], latest_absent: ObjectEvidence | None, now_us: int,
) -> ObjectTarget:
    if _frame_identity(past) in absent_frames:
        return _result(query, "unknown", "contradictory_camera_frame")
    if len(_projected_locations(past, seen)) > 1:
        return _result(query, "last_seen", "ambiguous_projected_view", past)
    metric_hint = (past.projection_qualified and past.floor_mm is not None
                   and _same_map(past, query))
    hint_fresh = (past.host_boot_id == query.host_boot_id
                  and past.captured_us is not None
                  and 0 <= now_us - past.captured_us < MAX_SEARCH_HINT_AGE_US)
    hint = past.floor_mm if metric_hint and hint_fresh else None
    if metric_hint and not hint_fresh:
        return _result(query, "last_seen", "search_hint_expired", past)
    reason = "not_currently_confirmed" if latest_absent else "historical_sighting_only"
    return _result(query, "last_seen", reason, past, hint=hint)


def _resolve_history(
    query: ObjectQuery, seen: list[ObjectEvidence], reports: list[ObjectEvidence],
    absent_frames: set[tuple], latest_absent: ObjectEvidence | None, now_us: int,
) -> ObjectTarget:
    candidates = _historical_candidates(seen, query)
    past = _select_past(candidates)
    report = max(reports, key=lambda e: e.seen_at_wall_s, default=None)
    if candidates and past is None:
        if report is not None and all(
                report.seen_at_wall_s > e.seen_at_wall_s for e in seen):
            return _result(query, "user_reported", "unverified_user_location", report)
        # No uniquely ordered historical view: do not invent its timestamp or
        # pass an arbitrary metric search hint to the route planner.
        return _result(query, "last_seen", "historical_order_uncertain")
    if report is not None and (past is None or report.seen_at_wall_s > past.seen_at_wall_s):
        return _result(query, "user_reported", "unverified_user_location", report)
    if past is not None:
        return _resolve_past(query, past, seen, absent_frames, latest_absent, now_us)
    return _result(query, "unknown", "no_qualified_observation")


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
    rejection = _request_rejection(query, owner, evidence, now_us, fresh_us, min_confidence)
    if rejection is not None:
        return _result(query, "rejected", rejection)

    records = _matching_records(query, evidence, now_us)
    seen = [e for e in records if e.source == "camera_seen"
            and e.confidence >= min_confidence]
    reports = [e for e in records if e.source == "user_reported"]
    # Contradictions attach to the frame identity, not receipt freshness.
    absent_frames = {_frame_identity(e) for e in records
                     if e.source == "camera_not_seen"}
    latest_seen, latest_absent = _latest_fresh_frames(
        records, seen, query, owner, now_us, fresh_us,
    )
    current = _resolve_current(query, seen, absent_frames, latest_seen, latest_absent)
    if current is not None:
        return current
    return _resolve_history(query, seen, reports, absent_frames, latest_absent, now_us)

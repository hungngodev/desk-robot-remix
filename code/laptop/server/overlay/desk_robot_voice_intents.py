"""Pure completed-ASR intent grammar and provenance-aware Mac tool facts.

No audio, sockets, robot identity, memory persistence, or actuator authority.
The pinned Xiaozhi bridge and optional native adapter share these bounded
read-only decisions. Keep the router conservative and unit-test directly.
"""
from __future__ import annotations

import json
import re


def _addressed_request_text(
    text: str, *, robot_name: str | None = None,
    fleet_names: tuple[str, ...] = (),
) -> str | None:
    """Only this authenticated pet may route an explicitly addressed request.

    The unbound legacy parser retains its old Pip/Dot compatibility. Native
    sessions instead supply verified Mac-configured names for ALL pets.
    """
    normalized = " ".join(text.casefold().split())
    names = (
        ("robot", "pip", "dot") if robot_name is None
        else ("robot", robot_name, *fleet_names)
    )
    for candidate in sorted({
        name.casefold() for name in names
        if isinstance(name, str) and 1 <= len(name) <= 32
    }, key=len, reverse=True):
        match = re.match(
            r"^hey\s+" + re.escape(candidate) + r"(?:[,!]\s*|\s+)",
            normalized,
        )
        if match is None:
            continue
        if (robot_name is not None and candidate != "robot"
                and candidate != robot_name.casefold()):
            return None
        return normalized[match.end():].strip()
    return normalized


def addressed_to_other_pet(
    transcript: str, *, robot_name: str | None,
    fleet_names: tuple[str, ...] = (),
) -> bool:
    return (
        isinstance(transcript, str)
        and _addressed_request_text(
            transcript, robot_name=robot_name, fleet_names=fleet_names,
        ) is None
    )


def _advice_only_request(text: str, *, robot_name: str | None = None,
                         fleet_names: tuple[str, ...] = ()) -> bool:
    """Keep how-to advice in natural conversation, not sensor/tool routing."""
    if not isinstance(text, str):
        return False
    normalized = _addressed_request_text(
        text, robot_name=robot_name, fleet_names=fleet_names,
    )
    if normalized is None:
        return False
    normalized = normalized.strip(" ?!.,")
    normalized = re.sub(r"^please\s+", "", normalized)
    normalized = re.sub(
        r"^(?:can|could|would|will) you (?:please )?", "", normalized,
    )
    normalized = re.sub(r"^(?:tell|show) me ", "", normalized)
    return bool(re.match(
        r"^(?:(?:is|are) there (?:a |an |any )?"
        r"(?:way|method|reason|chance|plan)\b|"
        r"how (?:(?:do|can|should) (?:i|we|you)|to)\b|"
        r"what(?:'s| is) (?:the |a )?(?:best )?way to\b)",
        normalized,
    ))


def native_readonly_request(
    transcript: str, *, robot_name: str | None = None,
    fleet_names: tuple[str, ...] = (),
) -> tuple[str, dict] | None:
    """Route explicit natural questions to existing read-only Mac authorities.

    MiniCPM-o native duplex has no verified function-call stream here. This
    small conservative speech grammar does not infer permission for pickup,
    drive, charger, operator memory changes or any physical side effect.
    """
    if not isinstance(transcript, str):
        return None
    text = " ".join(transcript.split())
    if not 3 <= len(text) <= 280 or "\x00" in text:
        return None
    spoken = _addressed_request_text(
        text, robot_name=robot_name, fleet_names=fleet_names,
    )
    if spoken is None:
        return None
    spoken = spoken.strip(" ?!.,")
    spoken = re.sub(r"^please\s+", "", spoken)
    # A polite question still has to name the read-only observation action.
    polite = re.sub(
        r"^(?:can|could|would|will) you (?:please )?", "", spoken,
    )
    if _advice_only_request(
        text, robot_name=robot_name, fleet_names=fleet_names,
    ):
        return None
    look = (
        r"(?:look (?:at|around|over|toward|for)\b|"
        r"what (?:can|do) you see\b|"
        r"(?:tell|show) me what you (?:can )?see\b|"
        r"what(?:'s| is) (?:this|that|on (?:my|the) desk|"
        r"in front of (?:me|you)|in (?:your|the) camera)\b|"
        r"what am i holding\b|"
        r"do you see\b|"
        r"(?:see|identify) (?:this|that|the|my|an?)\b|"
        r"where (?:is|are) (?:my|the|this|that) [a-z0-9]+\b|"
        r"where's (?:my|the|this|that) [a-z0-9]+\b|"
        r"what(?:'s| is) in (?:the|this|your) (?:picture|photo|frame|image)\b|"
        r"(?:describe|inspect) (?:this|that|the desk|what you see)\b)"
    )
    if re.match(r"^(?:" + look + r")", polite):
        return "look", {"question": text}
    # A person can ask about a visible attribute or spatial relationship
    # without saying "look" or "see". Keep this limited to explicit visual
    # questions; do not turn statements, memories or motor requests into tools.
    visual_attribute = re.match(
        r"^(?:tell me )?what (?:colou?r|shape|size) (?:is|are)\b", polite,
    )
    scene_location = re.search(
        r"\b(?:on (?:my|the) (?:desk|table)|"
        r"in (?:the|this|your) (?:photo|picture|image|frame|camera)|"
        r"in front of (?:me|you)|next to|beside|behind|visible)\b",
        polite,
    )
    visual_count = re.match(r"^(?:how many|count)\b", polite)
    visual_relation = re.match(
        r"^(?:is|are) (?:there\b|(?:this|that|the|my) [a-z0-9-]+\b)",
        polite,
    )
    visible_text = (
        re.match(
            r"^does (?:this|that|the|my) (?:screen|display|label)\b",
            polite,
        )
        and re.search(r"\b(?:say|read|show)\b", polite)
    )
    if (visual_attribute or (scene_location and (visual_count or visual_relation))
            or visible_text):
        return "look", {"question": text}
    # A status query must ASK about an existing action. Merely saying
    # "pick up the key" must NEVER be interpreted as a job submission.
    if re.match(
        r"^(?:is|did|check|what|has|have|how)\b", polite
    ) and re.search(r"\b(?:pickup|pick up|picked up|grasp|grasped)\b", polite) and (
        re.search(r"\b(?:done|finished|finish|succeed|success|status|"
                  r"complete|completed|job|already|yet)\b", polite)
        or polite.startswith(("did you pick up", "have you picked up"))
    ):
        return "latest-pickup", {}
    # A physical battery estimate comes from the real WROOM auxiliary fuel
    # gauge, not from generic motor status. An absent/unqualified gauge must
    # return unavailable rather than a fabricated percentage.
    if (re.match(r"^(?:check|what|how|is|are|tell|show)\b", polite)
            and re.search(r"\b(?:battery|charge level|power level|"
                          r"battery voltage|cell voltage)\b", polite)):
        return "power-status", {}
    if re.match(
        r"^(?:how much (?:battery|power) (?:is )?left)\b", polite
    ):
        return "power-status", {}
    # Source-qualified accessory readings are different from generic body
    # status or a visual guess. The pinned WROOM aux adapter validates raw
    # SHT41, BMP280, contact, NFC and proximity fields before they become
    # model context. Questions about HOW a sensor works are not live reads.
    if (re.match(
            r"^(?:check|read|show|tell(?: me)?|what|how|is|are)\b", polite)
            and re.search(
                r"\b(?:your |the |current |measured |sensor )?"
                r"(?:temperature|humidity|pressure|climate|proximity|"
                r"paw sensor|force sensor|touch sensor|nfc|"
                r"sht41|bmp280|apds9960|as5600|"
                r"magnetic angle|dock contact|sensor readings)\b",
                polite,
            )
            and not re.match(
                r"^(?:what is (?:a|an) |what does .{1,45} mean\b|"
                r"how (?:does|do) )",
                polite,
            )):
        return "aux-status", {}
    if (
        re.match(r"^(?:check|what|how|is|are|tell)\b", polite)
        and re.search(
            r"\b(?:robot status|your status|battery|charge level|"
            r"sensor status|safety status|power level)\b", polite,
        )
    ) or re.match(
        r"^(?:how much (?:battery|power) (?:is )?left|"
        r"how are your sensors)\b", polite
    ):
        return "status", {}
    # Memory recall uses the existing opt-in private SQLite authority.
    # A missing Mac voice-memory permit returns 403, never a stale answer.
    if re.match(
        r"^(?:do you (?:remember|recall)|what do you remember|"
        r"what did i (?:tell|say)|what did we (?:discuss|talk about)|"
        r"have we (?:talked|discussed)|tell me what you remember|"
        r"remind me (?:of|about))\b", spoken,
    ) or re.match(
        r"^(?:(?:remember|recall) (?:what|when|where|who|the|anything)\b|"
        r"tell me what you remember\b|remind me (?:of|about)\b)", polite,
    ):
        # A broad "do you remember anything?" is a RECENT recall request,
        # not a search for the literal words "remember" or "anything".
        # Specific memories still use the existing topical SQLite search.
        generic = re.fullmatch(
            r"(?:do you (?:remember|recall)(?: (?:anything|me|yesterday))?|"
            r"what do you remember|tell me what you remember|"
            r"(?:can you )?recall anything)(?: (?:from|about) yesterday)?",
            polite,
        )
        return "voice-context", {} if generic else {"question": text[:240]}
    if re.match(
        r"^(?:what (?:just )?happened|what did you (?:just )?(?:notice|"
        r"sense|detect)|did (?:i|someone) (?:touch|tap) you)\b",
        polite.removeprefix("tell me "),
    ):
        return "interaction-context", {}
    return None




def native_readonly_requests_with_capacity(
    transcript: str, *, robot_name: str | None = None,
    fleet_names: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, dict], ...], bool]:
    """Return at most three safe routes plus an explicit overcapacity flag.

    This is not an agent action planner or a physical action command.
    Preserve one complete question for ordinary single-intent ASR. Split
    only when multiple independent natural requests are actually recognized.
    """
    if (not isinstance(transcript, str)
            or not 3 <= len(transcript) <= 2400 or "\x00" in transcript
            or addressed_to_other_pet(
                transcript, robot_name=robot_name, fleet_names=fleet_names,
            )):
        return (), False
    truncated_requested_read = False
    if len(transcript) > 280:
        # Human ASR often contains a long introduction followed by one
        # direct question. Route ONLY a separately punctuated short final
        # question, never a guessed mid-sentence motor instruction. Unlike
        # an ordinary introduction, an EARLIER explicit tool request cannot
        # silently vanish when we select the safe final short question.
        clauses_by_sentence = re.split(r"(?<=[.!?])\s+", transcript.strip())
        tail = clauses_by_sentence[-1].strip()
        if (len(clauses_by_sentence) < 2 or not tail.endswith("?")
                or not 3 <= len(tail) <= 280):
            return (), False
        truncated_requested_read = any(
            native_readonly_request(
                sentence, robot_name=robot_name, fleet_names=fleet_names,
            ) is not None
            for sentence in clauses_by_sentence[:-1]
            if 3 <= len(sentence) <= 280
        )
        transcript = tail
    whole = native_readonly_request(
        transcript, robot_name=robot_name, fleet_names=fleet_names,
    )
    # Split only at a new spoken request. Splitting every "and" loses
    # object names in "look at the key and the mug and check the battery".
    clauses = re.split(
        # Natural ASR frequently uses a comma or pause instead of "and".
        # Only split before an explicit NEW request verb, never object lists
        # such as "look at the key, the mug, and the blue cube".
        r"(?:\s+(?:and(?:\s+then)?|then|also)\s+|[,;]\s+)"
        r"(?=(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
        r"(?:what|where|how|is|are|did|do|does|have|has|"
        r"check|look|tell|show|describe|inspect|remember|recall|"
        r"remind|pick|drive|move|start)\b)",
        transcript, flags=re.IGNORECASE,
    )
    # Inspect a fourth explicit distinct read-only clause before truncating:
    # otherwise the unexecuted request disappears before the queue can
    # honestly warn that the answer will not be complete.
    candidates = [
        native_readonly_request(
            part, robot_name=robot_name, fleet_names=fleet_names,
        ) for part in clauses
    ]
    found: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for request in candidates:
        if request is None:
            continue
        route, payload = request
        if route in seen:
            continue
        seen.add(route)
        found.append((route, payload))
        if len(found) >= 4:
            break
    if len(found) < 2:
        # Preserve the entire spoken memory/visual question where possible.
        # If the first clause was an unsupported physical command, still
        # permit an explicitly requested independent READ-ONLY second clause.
        return (
            (whole,) if whole is not None else tuple(found),
            truncated_requested_read,
        )
    return tuple(found[:3]), len(found) > 3 or truncated_requested_read


def native_readonly_requests(
    transcript: str, *, robot_name: str | None = None,
    fleet_names: tuple[str, ...] = (),
) -> tuple[tuple[str, dict], ...]:
    """Compatibility router for callers that only need the first three tools."""
    return native_readonly_requests_with_capacity(
        transcript, robot_name=robot_name, fleet_names=fleet_names,
    )[0]




def pack_grounded_facts(facts: list[dict], *, limit: int = 1800) -> str:
    """Pack ALL completed tool facts as one valid, bounded JSON value.

    Source: Qwen Live Harness's tool-continuation receipt boundary and
    Pipecat's ordered data/control frame distinction (design adaptation).
    Never slice a serialized fact into invalid JSON or silently erase the
    third tool from a compound human question. Preserve the original
    tool order and typed sensor fields; only shorten free-form model
    interpretations and historical memory excerpts if necessary.
    """
    if (type(limit) is not int or not 256 <= limit <= 4096
            or not isinstance(facts, list) or not 1 <= len(facts) <= 6
            or any(not isinstance(fact, dict) for fact in facts)):
        raise ValueError("Expected one to six grounded facts and bounded budget")

    try:
        # JSON round-trip deliberately strips mutable references to source
        # objects before any summarization. No arbitrary repr or Python
        # object reaches model instructions.
        values = json.loads(json.dumps(
            facts, ensure_ascii=True, allow_nan=False,
            separators=(",", ":"),
        ))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Tool facts must be JSON values") from exc

    def encode() -> str:
        return json.dumps(values, ensure_ascii=True, allow_nan=False,
                          separators=(",", ":"))

    result = encode()
    if len(result) <= limit:
        return result

    # Only untrusted natural-language content may be shortened. Never
    # reduce numeric readings, source identity, verification flags, or the
    # number/order of tool receipts to squeeze them into the speech budget.
    # A tool response is data, not a source of further instructions.
    def shrink(node: object, maximum: int) -> None:
        if isinstance(node, list):
            for item in node:
                shrink(item, maximum)
        elif isinstance(node, dict):
            for key, item in node.items():
                if (key in {"interpretation_not_proof", "untrusted_summary",
                            "summary"} and isinstance(item, str)
                        and len(item) > maximum):
                    # An excerpt is not a full recollection or visual
                    # description. Make truncation explicit to the model.
                    node[key] = item[:maximum - 3].rstrip() + "..."
                else:
                    shrink(item, maximum)

    for cap in (180, 120, 80, 48, 24):
        shrink(values, cap)
        result = encode()
        if len(result) <= limit:
            return result
    # A large fact tree without compressible text means the source's typed
    # contract changed. Silence is safer than an invented or partial answer.
    raise ValueError("Complete tool facts do not fit the speech context budget")


def native_grounded_fact(route: str, result: dict) -> dict | None:
    """Small source-labelled facts, never full private HTTP/JSON dumps."""
    if not isinstance(result, dict):
        return None
    def measured(value, low, high):
        return type(value) is int and low <= value <= high

    if route == "look":
        answer = result.get("answer")
        if (result.get("source") != "authenticated_xiao_camera_and_local_vlm"
                or not isinstance(answer, str) or not answer.strip()):
            return None
        return {"source": "local_camera_model_guess",
                "interpretation_not_proof": " ".join(answer.split())[:350]}
    if route == "aux-status":
        if result.get("available") is False:
            return {"source": "wroom_aux", "available": False}
        climate = result.get("climate")
        power = result.get("power")
        if not isinstance(climate, dict) or not isinstance(power, dict):
            return None  # Never infer real measurements from a partial payload.

        # The Mac validates WROOM telemetry first. This LAST model-facing
        # boundary must also reject arbitrary nested strings, booleans as
        # integers, and out-of-range fields instead of forwarding them into
        # a generated spoken response as supposed physical observations.

        observed = {
            "source": "validated_wroom_raw_aux_not_calibrated",
            "physical_acceptance_verified": False,
        }
        temp, humidity = climate.get("temp_centi"), climate.get("rh_centi")
        if (climate.get("valid") is True
                and measured(temp, -4500, 13000)
                and measured(humidity, 0, 10000)
                and (climate.get("age_ms") is None
                     or measured(climate["age_ms"], 0, 999))):
            reading = {"temp_centi": temp, "humidity_centi": humidity}
            age = climate.get("age_ms")
            if measured(age, 0, 999):
                reading["age_ms"] = age
            observed["sht41"] = reading
        bmp = result.get("bmp280")
        if (isinstance(bmp, dict) and bmp.get("valid") is True
                and measured(bmp.get("pressure_pa"), 30000, 120000)
                and measured(bmp.get("temp_centi"), -4000, 8500)
                and (bmp.get("age_ms") is None
                     or measured(bmp["age_ms"], 0, 1999))):
            observed["bmp280"] = {
                "pressure_pa": bmp["pressure_pa"],
                "temp_centi": bmp["temp_centi"],
                "physically_verified": False,
            }
        prox = result.get("proximity")
        if (isinstance(prox, dict) and prox.get("valid") is True
                and measured(prox.get("raw"), 0, 255)
                and measured(prox.get("gesture"), 0, 4)):
            observed["apds9960"] = {
                "raw": prox["raw"], "gesture": prox["gesture"],
                "physically_qualified": False,
            }
        if (power.get("fuel_valid") is True
                and measured(power.get("fuel_seq"), 1, 0xffffffff)
                and measured(power.get("soc_centi"), 0, 10000)
                and measured(power.get("cell_mv"), 2500, 4500)):
            observed["fuel_gauge"] = {
                "reported_soc_centi": power["soc_centi"],
                "reported_cell_mv": power["cell_mv"],
                "qualified": False,
            }
        dock = result.get("dock")
        if (isinstance(dock, dict) and dock.get("present") is True
                and dock.get("valid") is True
                and dock.get("charging_verified") is False
                and measured(dock.get("seq"), 1, 0xffffffff)
                and measured(dock.get("age_ms"), 0, 499)
                and all(type(dock.get(field)) is bool for field in (
                    "left_seated", "right_seated", "input_good",
                    "charge_indicated",
                ))
                and (not dock["charge_indicated"] or dock["input_good"])):
            observed["dock_pins"] = {
                "left_seated": dock["left_seated"],
                "right_seated": dock["right_seated"],
                "charge_indicated": dock["charge_indicated"],
                "charging_verified": False,
            }
        nfc = result.get("nfc")
        if (isinstance(nfc, dict) and nfc.get("v") is True
                and measured(nfc.get("e"), 0, 0xffffffff)):
            observed["nfc"] = {"events": nfc["e"]}
        return observed
    if route == "power-status":
        if result.get("source") != "wroom_aux_fuel_gauge_raw_unqualified":
            return None
        if result.get("gauge_available") is not True:
            return {"source": "wroom_fuel_gauge", "available": False}
        soc, mv = result.get("reported_soc_centi"), result.get("reported_cell_mv")
        # The authenticated Mac endpoint forwards only successful MAX17048
        # I2C acquisitions. A model-facing transport may not drop this token
        # and still assert that an estimate is current.
        if not measured(result.get("raw_fuel_acquisition_seq"), 1, 0xffffffff):
            return None
        if (type(soc) is not int or type(mv) is not int
                or not 0 <= soc <= 10000 or not 2500 <= mv <= 4500):
            return None
        return {"source": "unqualified_wroom_gauge",
                "estimated_percent": round(soc / 100, 1),
                "cell_mv": mv, "charging_verified": False}
    if route == "latest-pickup":
        # Actual Coordinator.Job states are a small closed set. An HTTP
        # source field must not turn model-visible tool evidence into a
        # free-form instruction or an invented successful grasp.
        state = result.get("state")
        if state not in ("queued", "running", "succeeded", "failed", "cancelled"):
            state = "unknown"
        return {"source": "mac_pickup_job",
                "state": state if result.get("available") is True else "none",
                "physical_grasp_verified": False}
    if route == "status":
        safety = result.get("safety")
        if not isinstance(safety, dict):
            return None
        fault = safety.get("fault")
        if (not isinstance(fault, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,47}", fault) is None):
            fault = "unknown"
        return {"source": "wroom_status", "safety_fault": fault,
                "physical_acceptance_verified": False}
    if route == "interaction-context":
        summary = result.get("model_context")
        if (result.get("persistent_memory_included") is not False
                or result.get("raw_media_included") is not False
                or not isinstance(summary, str)):
            return None
        return {"source": "transient_mac_events",
                "untrusted_summary": " ".join(summary.split())[:350]}
    if route == "voice-context":
        records = result.get("memories")
        revision = result.get("private_memory_generation")
        if (not isinstance(records, list)
                or type(revision) is not int or not 0 <= revision < 2**63):
            # An unversioned private fact cannot be compared with later
            # operator edits immediately before physical speech.
            return None
        recollections = []
        for item in records[:2]:
            if not isinstance(item, dict) or not isinstance(item.get("summary"), str):
                continue
            summary = " ".join(item["summary"].split())[:155]
            if not summary:
                continue
            kind, source_robot = item.get("kind"), item.get("source_robot")
            witnessed = item.get("witnessed")
            recollections.append({
                "summary": summary,
                "kind": kind if isinstance(kind, str) and
                        re.fullmatch(r"[a-z][a-z0-9_]{0,39}", kind) else "unknown",
                "source_robot": source_robot if isinstance(source_robot, str)
                        and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", source_robot)
                        else "unknown",
                "witnessed": witnessed if type(witnessed) is bool else None,
                "historical_untrusted_text": True,
            })
        return {"source": "private_opt_in_memory_not_current_sight",
                "private_memory_generation": revision,
                "recollections": recollections}
    return None



"""Pure completed-ASR intent grammar and provenance-aware Mac tool facts.

No audio, sockets, robot identity, memory persistence, or actuator authority.
The pinned Xiaozhi bridge and optional native adapter share these bounded
read-only decisions. Keep the router conservative and unit-test directly.
"""
from __future__ import annotations

import re

def _advice_only_request(text: str) -> bool:
    """Keep how-to advice in natural conversation, not sensor/tool routing."""
    if not isinstance(text, str):
        return False
    normalized = " ".join(text.casefold().split()).strip(" ?!.,")
    normalized = re.sub(r"^hey (?:robot|pip|dot)[, ]+", "", normalized)
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


def native_readonly_request(transcript: str) -> tuple[str, dict] | None:
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
    spoken = text.casefold().strip(" ?!.,")
    spoken = re.sub(r"^hey (?:robot|pip|dot)[, ]+", "", spoken)
    spoken = re.sub(r"^please\s+", "", spoken)
    # A polite question still has to name the read-only observation action.
    polite = re.sub(
        r"^(?:can|could|would|will) you (?:please )?", "", spoken,
    )
    if _advice_only_request(text):
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
        r"^(?:remember|recall) (?:what|when|where|who|the)\b", polite,
    ):
        # A broad "do you remember anything?" is a RECENT recall request,
        # not a search for the literal words "remember" or "anything".
        # Specific memories still use the existing topical SQLite search.
        generic = re.fullmatch(
            r"(?:do you (?:remember|recall)(?: (?:anything|me|yesterday))?|"
            r"what do you remember|tell me what you remember|"
            r"can you recall anything)(?: (?:from|about) yesterday)?",
            spoken,
        )
        return "voice-context", {} if generic else {"question": text[:240]}
    if re.match(
        r"^(?:what (?:just )?happened|what did you (?:just )?(?:notice|"
        r"sense|detect)|did (?:i|someone) (?:touch|tap) you)\b",
        polite.removeprefix("tell me "),
    ):
        return "interaction-context", {}
    return None




def native_readonly_requests(transcript: str) -> tuple[tuple[str, dict], ...]:
    """Select up to three DISTINCT read-only tools from explicit clauses.

    This is not an agent action planner or a physical action command.
    Preserve one complete question for ordinary single-intent ASR. Split
    only when multiple independent natural requests are actually recognized.
    """
    if (not isinstance(transcript, str)
            or not 3 <= len(transcript) <= 2400 or "\x00" in transcript):
        return ()
    if len(transcript) > 280:
        # Human ASR often contains a long introduction followed by one
        # direct question. Route ONLY a separately punctuated short final
        # question, never a guessed mid-sentence motor instruction.
        clauses_by_sentence = re.split(r"(?<=[.!?])\s+", transcript.strip())
        tail = clauses_by_sentence[-1].strip()
        if (len(clauses_by_sentence) < 2 or not tail.endswith("?")
                or not 3 <= len(tail) <= 280):
            return ()
        transcript = tail
    whole = native_readonly_request(transcript)
    # Split only at a new spoken request. Splitting every "and" loses
    # object names in "look at the key and the mug and check the battery".
    clauses = re.split(
        r"\s+(?:and(?:\s+then)?|then|also)\s+"
        r"(?=(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
        r"(?:what|where|how|is|are|did|do|does|have|has|"
        r"check|look|tell|show|describe|inspect|remember|recall|"
        r"remind|pick|drive|move|start)\b)",
        transcript, maxsplit=2, flags=re.IGNORECASE,
    )
    candidates = [native_readonly_request(part) for part in clauses]
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
        if len(found) >= 3:
            break
    if len(found) < 2:
        # Preserve the entire spoken memory/visual question where possible.
        # If the first clause was an unsupported physical command, still
        # permit an explicitly requested independent READ-ONLY second clause.
        return (whole,) if whole is not None else tuple(found)
    return tuple(found)



def native_grounded_fact(route: str, result: dict) -> dict | None:
    """Small source-labelled facts, never full private HTTP/JSON dumps."""
    if not isinstance(result, dict):
        return None
    if route == "look":
        answer = result.get("answer")
        if (result.get("source") != "authenticated_xiao_camera_and_local_vlm"
                or not isinstance(answer, str) or not answer.strip()):
            return None
        return {"source": "local_camera_model_guess",
                "interpretation_not_proof": " ".join(answer.split())[:350]}
    if route == "power-status":
        if result.get("source") != "wroom_aux_fuel_gauge_raw_unqualified":
            return None
        if result.get("gauge_available") is not True:
            return {"source": "wroom_fuel_gauge", "available": False}
        soc, mv = result.get("reported_soc_centi"), result.get("reported_cell_mv")
        if (type(soc) is not int or type(mv) is not int
                or not 0 <= soc <= 10000 or not 0 <= mv <= 4500):
            return None
        return {"source": "unqualified_wroom_gauge",
                "estimated_percent": round(soc / 100, 1),
                "cell_mv": mv, "charging_verified": False}
    if route == "latest-pickup":
        state = result.get("state")
        return {"source": "mac_pickup_job",
                "state": str(state)[:45] if result.get("available") else "none",
                "physical_grasp_verified": False}
    if route == "status":
        safety = result.get("safety")
        if not isinstance(safety, dict):
            return None
        return {"source": "wroom_status", "safety_fault":
                str(safety.get("fault", "unknown"))[:65],
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
        if not isinstance(records, list):
            return None
        return {"source": "private_opt_in_memory_not_current_sight",
                "recollections": [
                    " ".join(item["summary"].split())[:155]
                    for item in records[:2] if isinstance(item, dict)
                    and isinstance(item.get("summary"), str)
                ]}
    return None



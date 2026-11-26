"""Pure ASR dispatch contracts, independent of the native audio provider."""
from pathlib import Path

import pytest


@pytest.fixture
def intents(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]
                                    / "laptop/server/overlay"))
    import desk_robot_voice_intents

    return desk_robot_voice_intents


@pytest.mark.parametrize(("question", "expected"), [
    ("What color is the battery?", ("look", {"question": "What color is the battery?"})),
    ("Check your battery status", ("power-status", {})),
    ("Did you pick up the battery yet?", ("latest-pickup", {})),
    ("Check your temperature", ("aux-status", {})),
    ("Are your motors armed?", ("status", {})),
    ("Do you remember anything?", ("voice-context", {})),
    ("Remind me about the mug", ("voice-context", {"question": "Remind me about the mug"})),
    ("What just happened?", ("interaction-context", {})),
    ("How do I charge a battery?", None),
    ("Pick up the key", None),
    ("Arm your motors", None),
])
def test_dispatch_preserves_route_precedence(intents, question, expected):
    assert intents.native_readonly_request(question) == expected


def test_dispatch_preserves_pet_address_and_question_bounds(intents):
    kwargs = {"robot_name": "Pip", "fleet_names": ("Pip", "Dot")}
    assert intents.native_readonly_request("Hey Dot, check your battery", **kwargs) is None
    assert intents.native_readonly_request("Hey Pip, check your battery", **kwargs) == (
        "power-status", {},
    )
    camera = "Look at " + "x" * 272
    memory = "Remind me about " + "x" * 264
    assert intents.native_readonly_request(camera) == ("look", {"question": camera})
    assert intents.native_readonly_request(camera + "x") is None
    assert intents.native_readonly_request(memory) == (
        "voice-context", {"question": memory[:240]},
    )


@pytest.mark.parametrize(("route", "payload"), [
    ("look", {}),
    ("look", {"question": True}),
    ("look", {"question": "x" * 281}),
    ("look", {"question": " "}),
    ("look", {"question": "x\x00y"}),
    ("look", {"question": "x", "extra": "y"}),
    ("look", []),
    ("voice-context", {"question": "x" * 241}),
    ("power-status", {"question": "x"}),
])
def test_dispatch_rejects_malformed_matching_payload(intents, monkeypatch, route, payload):
    rule = intents._INTENT_RULES[route]
    invalid = rule._replace(handler=lambda *_: payload)
    fallback = intents._INTENT_RULES["status"]._replace(handler=lambda *_: {})
    monkeypatch.setattr(intents, "_INTENT_RULES", {route: invalid, "status": fallback})
    assert intents.native_readonly_request("Check your battery") is None


@pytest.mark.parametrize("question", ["Look at \ud800", "Remind me about \udfff"])
def test_dispatch_rejects_non_utf8_question(intents, question):
    assert intents.native_readonly_request(question) is None


def test_dispatch_preserves_valid_unicode(intents):
    question = "Look at the cà phê cup"
    assert intents.native_readonly_request(question) == ("look", {"question": question})


@pytest.mark.parametrize("answer", [
    "I can't tell from my camera right now.",
    "  I can't tell from my camera\nright now.  ",
])
def test_visual_abstention_is_an_explicit_unavailable_receipt(intents, answer):
    result = {"source": "authenticated_xiao_camera_and_local_vlm", "answer": answer}
    assert intents.native_grounded_fact("look", result) == {
        "source": "local_camera_model_guess", "route": "look", "available": False,
    }


def test_visible_answer_remains_an_unverified_interpretation(intents):
    result = {
        "source": "authenticated_xiao_camera_and_local_vlm",
        "answer": "  A blue mug might be visible.  ",
    }
    assert intents.native_grounded_fact("look", result) == {
        "source": "local_camera_model_guess",
        "interpretation_not_proof": "A blue mug might be visible.",
    }

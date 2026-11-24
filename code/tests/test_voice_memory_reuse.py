"""Explicit privacy gate for native Xiaozhi access to Mac memories."""
from pathlib import Path

import pytest
from desk_robot.config import Settings, load_settings
from fastapi import HTTPException


def _check_fake_current_tool_owner(owner, robot_id, message):
    """Standalone memory tests use the legacy Mac turn clock fixture."""
    if (not isinstance(owner, tuple) or len(owner) != 2
            or type(owner[1]) is not int
            or getattr(owner[0], "_turn_epoch", {}).get(robot_id) != owner[1]):
        raise HTTPException(409, message)


def test_voice_memory_opt_in_defaults_off_in_both_modes():
    root = Path(__file__).resolve().parents[1]
    simulation = load_settings(root / "config/fleet.simulation.toml")
    assert simulation.voice_memory_tools_enabled is False
    hydrated = Settings.model_validate(simulation.model_dump())
    assert hydrated.voice_memory_tools_enabled is False
    hydrated.voice_memory_tools_enabled = True
    assert hydrated.voice_memory_tools_enabled is True


def test_xiaozhi_memory_tool_calls_only_scoped_readonly_mac_endpoint():
    root = Path(__file__).resolve().parents[1]
    bridge = (root / "laptop/server/overlay/desk_robot_tools.py").read_text()
    api = (root / "laptop/src/desk_robot/api.py").read_text()
    routes = (root / "laptop/src/desk_robot/api_memory_routes.py").read_text()
    assert 'elif route == "voice-context"' in bridge
    voice_context = bridge.split('elif route == "voice-context":', 1)[1].split(
        'elif route == "look":', 1,
    )[0]
    assert "signed_get(" in voice_context
    assert "client.get(" not in voice_context
    assert 'f"/v1/pet/{robot}/voice-context"' in voice_context
    assert 'params={"query": payload["question"]}' in voice_context
    assert 'receipt_token = os.environ.get("DESK_ROBOT_SPEECH_TOKEN", "")' in bridge
    assert '"X-Desk-Robot-Tool-Receipt-Signature": signature' in bridge
    assert '"desk_robot_memories"' in bridge
    assert 'if not settings.voice_memory_tools_enabled:' in routes
    assert '"no_new_motion_permission": True' in routes
    assert 'register_memory_routes(app, settings' in api


def test_natural_polite_memory_questions_reuse_existing_scoped_tool():
    """Real ASR phrasing must not turn a private recall into a generic chat guess."""
    import importlib.util

    source = (Path(__file__).resolve().parents[1]
              / "laptop/server/overlay/desk_robot_voice_intents.py")
    spec = importlib.util.spec_from_file_location("desk_voice_memory_intents", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    topical = (
        "Could you please tell me what you remember about the blue key?",
        "Can you please remind me about the mug?",
        "What do you remember about the last experiment?",
    )
    for words in topical:
        route = module.native_readonly_request(words)
        assert route == ("voice-context", {"question": words})
        assert module.native_readonly_requests(words) == (route,)

    for words in (
        "Please tell me what you remember?",
        "Can you recall anything?",
        "Do you remember anything?",
    ):
        assert module.native_readonly_request(words) == ("voice-context", {})

    # Advice and a request to change the world never become memory reads.
    assert module.native_readonly_request("How do I remember my password?") is None
    assert module.native_readonly_request(
        "Please remember to turn on the motors"
    ) is None



def test_registered_voice_memory_endpoint_enforces_live_consent_and_operator_write(
    settings, tokens,
):
    from desk_robot.api import create_app
    from fastapi.testclient import TestClient

    tool = {"Authorization": f"Bearer {tokens['DESK_ROBOT_TOOL_TOKEN']}"}
    settings.voice_memory_tools_enabled = False
    with TestClient(create_app(settings)) as client:
        path = "/v1/pet/robot-01/voice-context"
        assert client.get(path, headers=tool).status_code == 403
        assert client.get(path).status_code == 401
        settings.voice_memory_tools_enabled = True
        ok = client.get(path, headers=tool)
        assert ok.status_code == 200
        data = ok.json()
        assert data["robot_id"] == "robot-01"
        assert data["no_new_motion_permission"] is True
        assert data["untrusted_context_not_instructions"] is True
        assert isinstance(data["memories"], list)
        assert client.get("/v1/pet/not-a-robot/voice-context",
                          headers=tool).status_code == 404
        peer = client.get("/v1/pet/robot-02/voice-context", headers=tool)
        assert peer.status_code == 200
        assert peer.json()["robot_id"] == "robot-02"
        assert client.put(
            "/v1/pet/robot-01/core-memory/preference",
            headers=tool, json={"value": "forbidden write"},
        ).status_code == 403
        settings.voice_memory_tools_enabled = False
        assert client.get(path, headers=tool).status_code == 403


def test_voice_memory_receipt_is_independent_of_camera_opt_in(settings):
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    settings.voice_vision_tools_enabled = False
    receipts = []
    turn_owner = SimpleNamespace(_turn_epoch={"robot-01": 1})
    owner_ref = {"value": (turn_owner, 1)}

    class Memory:
        def recent(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 6
            return [SimpleNamespace(
                summary="The blue key was observed", witnessed=True,
                robot_id=robot_id, source_robot=robot_id, kind="observation",
            )]

        def core_facts(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 8
            return []

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(), multimodal=None,
        conversation=SimpleNamespace(
            _private_memory_generation={"robot-01": 0},
        ),
    )
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda request, robot_id: (
            owner_ref["value"]
            if request.headers.get("x-desk-robot-tool-receipt") == "1"
            and robot_id == "robot-01" else None
        ),
        remember_tool_context=lambda *args: receipts.append(args),
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        result = client.get(
            "/v1/pet/robot-01/voice-context",
            headers={"x-desk-robot-tool-receipt": "1"},
        )
        assert result.status_code == 200
        assert result.json()["matched"] is True
        assert receipts == [(
            (turn_owner, 1), "robot-01", "memory_recall",
            "I observed: The blue key was observed",
        )]
        # Forged or obsolete ownership must fail closed, never disclose
        # historical memory and never add a model tool receipt.
        owner_ref["value"] = "current-voice-turn"
        invalid = client.get(
            "/v1/pet/robot-01/voice-context",
            headers={"x-desk-robot-tool-receipt": "1"},
        )
        assert invalid.status_code == 409
        assert "The blue key" not in str(invalid.json())
        owner_ref["value"] = (turn_owner, True)
        assert client.get(
            "/v1/pet/robot-01/voice-context",
            headers={"x-desk-robot-tool-receipt": "1"},
        ).status_code == 409
        assert len(receipts) == 1
        owner_ref["value"] = (turn_owner, 1)
        # An operator fetch cannot silently seed the model's next speech.
        assert client.get("/v1/pet/robot-01/voice-context").status_code == 200
        assert len(receipts) == 1
        settings.voice_memory_tools_enabled = False
        assert client.get(
            "/v1/pet/robot-01/voice-context",
            headers={"x-desk-robot-tool-receipt": "1"},
        ).status_code == 403
        assert len(receipts) == 1


@pytest.mark.parametrize("mutated_robot,expected_status", [
    ("robot-01", 409),
    ("robot-02", 200),
])
def test_voice_retrieval_fences_private_edit_during_sqlite_read(
    settings, mutated_robot, expected_status,
):
    """A private edit supersedes in-flight reads only for its own pet."""
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    settings.voice_vision_tools_enabled = False
    revisions = {"robot-01": 0, "robot-02": 0}
    receipts = []
    turn_owner = SimpleNamespace(_turn_epoch={"robot-01": 2})

    class Memory:
        def recent(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 6
            return [SimpleNamespace(
                summary="Private old preference", witnessed=True,
                robot_id=robot_id, source_robot=robot_id, kind="own_observation",
            )]

        def core_facts(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 8
            # This worker runs after the first await. In production the
            # operator PUT/PATCH/DELETE route advances this exact revision.
            revisions[mutated_robot] += 1
            return [SimpleNamespace(slot="favorite_game", value="chess")]

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(), multimodal=None,
        conversation=SimpleNamespace(_private_memory_generation=revisions),
    )
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda request, robot_id: (turn_owner, 2),
        remember_tool_context=lambda *args: receipts.append(args),
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        response = client.get("/v1/pet/robot-01/voice-context")

    assert response.status_code == expected_status
    if expected_status == 409:
        assert "Private old preference" not in response.text
        assert "chess" not in response.text
        assert receipts == []
    else:
        assert response.json()["core_facts"] == [
            {"slot": "favorite_game", "value": "chess"}
        ]
        assert response.json()["private_memory_generation"] == 0
        assert len(receipts) == 1


def test_vision_revocation_during_memory_read_clears_live_cues(settings):
    """A late opt-out must defeat cues captured before the SQLite await."""
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    settings.voice_vision_tools_enabled = True
    collected = []

    class Hub:
        def recent_events(self, robot_id, clock):
            collected.append("sensor")
            return [{"private": "camera event"}]

        def recent_tool_context(self, robot_id, clock):
            collected.append("tool")
            return [{"private": "tool interpretation"}]

        def interaction_timeline(self, robot_id, clock, *, limit):
            collected.append("timeline")
            return [{"private": "interaction timeline"}]

    class Memory:
        def recent(self, robot_id, *, limit):
            return []

        def core_facts(self, robot_id, *, limit):
            settings.voice_vision_tools_enabled = False
            return []

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(), multimodal=SimpleNamespace(hub=Hub()),
        conversation=SimpleNamespace(
            _private_memory_generation={"robot-01": 0},
        ),
    )
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda request, robot_id: None,
        remember_tool_context=lambda *args: None,
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        response = client.get("/v1/pet/robot-01/voice-context")
    assert response.status_code == 200
    assert collected == ["sensor", "tool", "timeline"]
    body = response.json()
    assert body["live_sensor_cues"] == []
    assert body["recent_tool_interpretations"] == []
    assert body["current_interaction_timeline"] == []
    assert settings.voice_memory_tools_enabled is True



@pytest.mark.parametrize("owner_type", [
    "missing_conversation", "missing_revision_dict", "invalid_dict",
    "missing_pet_revision", "bool_revision", "float_revision",
    "negative_revision", "string_revision", "oversized_revision",
    "missing_pet_revision_with_invalidator",
])
def test_model_voice_memory_requires_revision_owner_before_any_read(
    settings, owner_type,
):
    """Legacy/injected runtimes cannot bypass private memory edit fencing."""
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True

    class NoReads:
        def recent(self, *args, **kwargs):
            raise AssertionError("Missing revision owner must reject before SQLite")

        def search(self, *args, **kwargs):
            raise AssertionError("Missing revision owner must reject before SQLite")

        def core_facts(self, *args, **kwargs):
            raise AssertionError("Missing revision owner must reject before SQLite")

    runtime = SimpleNamespace(memory=NoReads(), multimodal=None)
    if owner_type != "missing_conversation":
        if owner_type == "missing_revision_dict":
            runtime.conversation = SimpleNamespace()
        else:
            revisions = {
                "invalid_dict": None,
                "missing_pet_revision": {"robot-02": 3},
                "missing_pet_revision_with_invalidator": {"robot-02": 3},
                "oversized_revision": {"robot-01": 2**63},
                "bool_revision": {"robot-01": True},
                "float_revision": {"robot-01": 1.0},
                "negative_revision": {"robot-01": -1},
                "string_revision": {"robot-01": "1"},
            }[owner_type]
            runtime.conversation = SimpleNamespace(
                _private_memory_generation=revisions,
            )
            if owner_type == "missing_pet_revision_with_invalidator":
                runtime.conversation.invalidate_private_memory = lambda robot_id: None
    app = FastAPI()
    app.state.runtime = runtime
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda *args: None,
        remember_tool_context=lambda *args: None,
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        for suffix in ("", "?query=some%20private%20fact"):
            response = client.get("/v1/pet/robot-01/voice-context" + suffix)
            assert response.status_code == 409
            assert "Private memory revision unavailable" in response.json()["detail"]
            assert "private fact" not in response.text



def test_live_runtime_registers_per_pet_memory_revision_owners(settings, tokens):
    """Production create_app must pass the strict privacy gate on first read."""
    from desk_robot.api import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as client:
        conversation = client.app.state.runtime.conversation
        assert conversation._private_memory_generation == {
            robot.id: 0 for robot in settings.robots
        }

@pytest.mark.parametrize(
    ("query", "expected", "matched"),
    [
        ("What do you remember about my favorite color?",
         "operator curated fact: favorite_color: blue", True),
        ("Can you recall my favorite game?",
         "operator curated fact: favorite_game: chess", True),
        ("Do you remember my favorite snack?",
         "No matching historical memories for this query", False),
        (None, "operator curated fact: favorite_color: blue", True),
    ],
)
def test_native_voice_recall_uses_relevant_operator_core_fact_without_episodes(
    settings, query, expected, matched,
):
    """A current Xiaozhi turn must hear a curated fact, not an empty recall."""
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    receipts = []
    turn = SimpleNamespace(_turn_epoch={"robot-01": 7})

    class Memory:
        def recent(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 6
            return []

        def search(self, robot_id, words, *, limit):
            assert robot_id == "robot-01" and words == query and limit == 6
            return []

        def core_facts(self, robot_id, *, limit):
            assert robot_id == "robot-01" and limit == 8
            return [
                SimpleNamespace(slot="favorite_color", value="blue"),
                SimpleNamespace(slot="favorite_game", value="chess"),
            ]

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(), multimodal=None,
        conversation=SimpleNamespace(
            _private_memory_generation={"robot-01": 0},
        ),
    )
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda *args: (turn, 7),
        remember_tool_context=lambda *args: receipts.append(args),
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        response = client.get(
            "/v1/pet/robot-01/voice-context",
            params={"query": query} if query is not None else None,
        )
        assert response.status_code == 200
        assert response.json()["matched"] is matched
        assert response.json()["core_facts"] == [
            {"slot": "favorite_color", "value": "blue"},
            {"slot": "favorite_game", "value": "chess"},
        ]
        chosen = response.json()["selected_core_fact"]
        if matched:
            slot, value = expected.removeprefix("operator curated fact: ").split(": ", 1)
            assert chosen == {"slot": slot, "value": value}
        else:
            assert chosen is None
        assert receipts == [((turn, 7), "robot-01", "memory_recall", expected)]
        receipts.clear()
        # A stale human turn may still read JSON, but may not be promoted
        # into an authoritative receipt on a different turn.
        turn._turn_epoch["robot-01"] = 8
        stale = client.get(
            "/v1/pet/robot-01/voice-context",
            params={"query": query} if query is not None else None,
        )
        assert stale.status_code == 409
        assert "blue" not in stale.text and "chess" not in stale.text
        assert receipts == []


@pytest.mark.parametrize("revoke_and_regrant", (False, True))
def test_native_curated_fact_recall_never_survives_memory_consent_change(
    settings, revoke_and_regrant,
):
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    receipts = []
    turn = SimpleNamespace(_turn_epoch={"robot-01": 1})

    class Memory:
        def search(self, robot_id, words, *, limit):
            return []

        def core_facts(self, robot_id, *, limit):
            settings.voice_memory_tools_enabled = False
            if revoke_and_regrant:
                settings.voice_memory_tools_enabled = True
            return [SimpleNamespace(slot="favorite_color", value="private blue")]

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(), multimodal=None,
        conversation=SimpleNamespace(
            _private_memory_generation={"robot-01": 0},
        ),
    )
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda *args: (turn, 1),
        remember_tool_context=lambda *args: receipts.append(args),
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        response = client.get(
            "/v1/pet/robot-01/voice-context",
            params={"query": "What is my favorite color?"},
        )
    assert response.status_code == 403
    assert "private blue" not in response.text
    assert receipts == []


@pytest.mark.parametrize("elapsed", [1.0, 31.0])
def test_voice_context_samples_volatile_cues_after_final_sqlite_read(
    settings, monkeypatch, elapsed,
):
    """Slow persistent reads cannot prolong live sensor or tool evidence."""
    import time
    from types import SimpleNamespace

    from desk_robot import api_memory_routes
    from desk_robot.multimodal import CameraFrameHub
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    settings.voice_vision_tools_enabled = True
    started = time.monotonic()
    clock = [started]
    monkeypatch.setattr(
        api_memory_routes, "time", SimpleNamespace(monotonic=lambda: clock[0]),
    )
    hub = CameraFrameHub(["robot-01"])
    hub.event_history["robot-01"].append(("touch", started))
    hub.remember_tool("robot-01", "memory_recall", "Past blue key", started)

    class Memory:
        def recent(self, robot_id, *, limit):
            return []

        def core_facts(self, robot_id, *, limit):
            clock[0] += elapsed
            return []

    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        memory=Memory(), multimodal=SimpleNamespace(hub=hub),
        conversation=SimpleNamespace(
            _private_memory_generation={"robot-01": 0},
        ),
    )
    api_memory_routes.register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda *args: None,
        remember_tool_context=lambda *args: None,
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        response = client.get("/v1/pet/robot-01/voice-context")
    assert response.status_code == 200
    body = response.json()
    if elapsed == 1.0:
        assert body["live_sensor_cues"][0]["age_ms"] == 1000
        assert body["recent_tool_interpretations"][0]["age_ms"] == 1000
        assert {item["kind"] for item in body["current_interaction_timeline"]} == {
            "touch", "memory_recall",
        }
    else:
        assert body["live_sensor_cues"] == []
        assert body["recent_tool_interpretations"] == []
        assert body["current_interaction_timeline"] == []


@pytest.mark.parametrize("mutation", ["missing", "bool", "float", "new_owner", "none"])
def test_voice_memory_rejects_invalid_or_replaced_revision_after_read(
    settings, mutation,
):
    from types import SimpleNamespace

    from desk_robot.api_memory_routes import register_voice_context_route
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings.voice_memory_tools_enabled = True
    owner = SimpleNamespace(
        _private_memory_generation={"robot-01": 0},
        invalidate_private_memory=lambda robot_id: None,
    )
    receipts = []
    turn = SimpleNamespace(_turn_epoch={"robot-01": 1})
    runtime = SimpleNamespace(conversation=owner, multimodal=None)

    class Memory:
        def recent(self, robot_id, *, limit):
            return [SimpleNamespace(
                summary="Private prior session words", witnessed=True,
                robot_id=robot_id, source_robot=robot_id, kind="heard_human",
            )]

        def core_facts(self, robot_id, *, limit):
            if mutation == "missing":
                owner._private_memory_generation.pop(robot_id)
            elif mutation == "bool":
                owner._private_memory_generation[robot_id] = False
            elif mutation == "float":
                owner._private_memory_generation[robot_id] = 0.0
            elif mutation == "new_owner":
                runtime.conversation = SimpleNamespace(
                    _private_memory_generation={robot_id: 0},
                )
            return []

    runtime.memory = Memory()
    app = FastAPI()
    app.state.runtime = runtime
    register_voice_context_route(
        app, settings, authorize=lambda: None,
        requested_tool_context=lambda *args: (turn, 1),
        remember_tool_context=lambda *args: receipts.append(args),
        current_tool_context=_check_fake_current_tool_owner,
    )
    with TestClient(app) as client:
        response = client.get("/v1/pet/robot-01/voice-context")
    if mutation == "none":
        assert response.status_code == 200
        assert response.json()["private_memory_generation"] == 0
        assert len(receipts) == 1
    else:
        assert response.status_code == 409
        assert "Private prior session words" not in response.text
        assert receipts == []


def test_voice_transcript_persists_across_sessions_without_unrelated_recall(
    settings, tokens, tmp_path,
):
    """Real authenticated routes and reopened private SQLite, no audio claim."""
    import time
    from types import SimpleNamespace

    from desk_robot.api import create_app
    from desk_robot.memory import MemoryStore
    from fastapi.testclient import TestClient

    settings.mode = "hardware"
    settings.voice_vision_tools_enabled = True
    settings.voice_memory_tools_enabled = True
    settings.voice_transcript_memory_enabled = True
    robot, peer = settings.robots[:2]
    root = tmp_path / "private"
    ids = [pet.id for pet in settings.robots]
    headers = {"Authorization": "Bearer " + tokens["DESK_ROBOT_TOOL_TOKEN"]}

    async def noop():
        pass

    def runtime():
        return SimpleNamespace(
            coordinator=SimpleNamespace(robot=settings.robot),
            memory=MemoryStore(root, ids), multimodal=None,
            conversation=SimpleNamespace(
                _private_memory_generation=dict.fromkeys(ids, 0),
            ),
            start=noop, close=noop,
        )

    first = runtime()
    with TestClient(create_app(settings, runtime=first)) as client:
        stamp = time.monotonic_ns() // 1000
        heard = client.post(
            f"/v1/pet/{robot.id}/omni-heard", headers=headers,
            json={
                "event_id": "omni_" + "a" * 12 + "_" + "b" * 20,
                "transcript": "Do you remember the red mug?",
                "accepted_at_us": stamp,
                "audio_committed_at_us": stamp,
            },
        )
        assert heard.status_code == 200
        assert heard.json()["episode_persisted"] is True
        assert heard.json()["speaker_identity_verified"] is False

    second = runtime()
    assert second.memory is not first.memory
    with TestClient(create_app(settings, runtime=second)) as client:
        startup = client.get(f"/v1/pet/{robot.id}/omni-context", headers=headers)
        assert startup.status_code == 200
        data = startup.json()
        assert "red mug" in data["untrusted_historical_evidence"]["recent"]
        assert "red mug" not in data["instructions"]
        path = f"/v1/pet/{robot.id}/voice-context"
        same = client.get(path, headers=headers, params={
            "query": "Do you remember the red mug?",
        })
        assert same.status_code == 200
        assert same.json()["matched"] is True
        assert same.json()["memories"][0]["source_robot"] == robot.id
        assert same.json()["memories"][0]["kind"] == "heard_human"
        unrelated = client.get(path, headers=headers, params={
            "query": "What do you remember about my violin?",
        })
        assert unrelated.status_code == 200
        assert unrelated.json()["matched"] is False
        assert unrelated.json()["memories"] == []
        peer_result = client.get(
            f"/v1/pet/{peer.id}/voice-context", headers=headers,
            params={"query": "red mug"},
        )
        assert peer_result.status_code == 200
        assert peer_result.json()["memories"] == []
        settings.voice_memory_tools_enabled = False
        assert client.get(path, headers=headers).status_code == 403
        disabled = client.get(f"/v1/pet/{robot.id}/omni-context", headers=headers)
        assert disabled.status_code == 200
        assert disabled.json()["untrusted_historical_evidence"] == {
            "core": "", "recent": "",
        }

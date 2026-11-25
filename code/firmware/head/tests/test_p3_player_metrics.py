"""Regression tests for the pinned upstream P3 host player overlay."""

import ast
import importlib.util
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

HEAD = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("DESK_ROBOT_UPSTREAM", HEAD.parents[1] / "upstream/xiaozhi-esp32"))
P3_SOURCE = UPSTREAM / "scripts/p3_tools/p3_gui_player.py"

spec = importlib.util.spec_from_file_location("p3_overlay", HEAD / "install_overlay.py")
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


def make_player(source, flags, available, times, *, fail_at=None):
    flags = iter(flags)
    available = iter(available)
    times = iter(times)
    calls = []

    class Stream:
        latency = 0.04

        @property
        def write_available(self):
            return next(available)

        def start(self):
            calls.append("start")
            if fail_at == "start":
                raise OSError("start failure")

        def write(self, audio):
            calls.append(len(audio))
            if fail_at == "write":
                raise OSError("write failure")
            return next(flags)

        def stop(self):
            calls.append("stop")
            if fail_at == "stop":
                raise OSError("stop failure")

        def close(self):
            calls.append("close")

    class Decoder:
        def __init__(self, sample_rate, channels):
            assert (sample_rate, channels) == (16000, 1)

        def decode(self, data, frame_size):
            assert frame_size == 960
            return bytes(2 * int(data))

    ns = {
        "sd": SimpleNamespace(OutputStream=lambda **kwargs: Stream()),
        "opuslib": SimpleNamespace(Decoder=Decoder),
        "np": SimpleNamespace(frombuffer=lambda data, **kwargs: range(len(data) // 2), int16=0),
        "struct": struct,
        "time": SimpleNamespace(monotonic=lambda: next(times), sleep=lambda _: None),
    }
    function = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "play_p3_file"
    )
    # Run the real playback function without optional GUI/PortAudio dependencies.
    exec(compile(ast.Module(body=[function], type_ignores=[]), "p3_gui_player.py", "exec"), ns)
    return ns["play_p3_file"], calls


def packets(path, *frames):
    payloads = [str(n).encode() for n in frames]
    path.write_bytes(b"".join(struct.pack(">BBH", 0, 0, len(p)) + p for p in payloads))
    return path


@pytest.fixture
def source():
    if not P3_SOURCE.is_file():
        pytest.skip("Pinned upstream P3 fixture unavailable")
    return P3_SOURCE.read_text()


def test_reports_underflow_pressure_and_host_timing(source, tmp_path):
    path = packets(tmp_path / "audio.p3", 960, 480, 960)
    player, calls = make_player(
        overlay.instrument_p3_player(source), [True, False, True],
        [0, 480, 100], [10, 10.01, 10.03, 10.04, 10.05, 10.06, 10.10],
    )
    states = iter([False, True, False, False, False])
    metrics = player(path, pause_event=SimpleNamespace(is_set=lambda: next(states)))
    assert metrics["submitted_frames"] == 2400
    assert metrics["write_calls"] == 3
    assert metrics["underflow_reports"] == 2
    assert metrics["underflow_reports_first_write"] == 1
    assert metrics["underflow_reports_after_pause"] == 0
    assert metrics["underflow_reports_active"] == 1
    assert metrics["termination"] == "eof"
    assert metrics["output_overrun_reports"] is None
    assert metrics["writes_exceeding_available_frames"] == 2
    assert metrics["min_write_available_frames"] == 0
    assert metrics["output_latency_estimate_ms"] == pytest.approx(40)
    assert metrics["stream_start_to_first_write_return_ms"] == pytest.approx(30)
    assert metrics["max_write_ms"] == pytest.approx(40)
    assert calls == ["start", 960, 480, 960, "stop", "close"]


def test_pause_underflow_report_separate(source, tmp_path):
    path = packets(tmp_path / "audio.p3", 960, 960)
    player, _ = make_player(
        overlay.instrument_p3_player(source), [False, True], [960, 960],
        [0, 0.01, 0.02, 2, 2.01],
    )
    states = iter([False, True, False, False])
    metrics = player(path, pause_event=SimpleNamespace(is_set=lambda: next(states)))
    assert metrics["underflow_reports"] == metrics["underflow_reports_after_pause"] == 1
    assert metrics["underflow_reports_first_write"] == 0
    assert metrics["underflow_reports_active"] == 0
    assert metrics["max_write_ms"] == pytest.approx(10)


def test_empty_file_no_fabricated_measurements(source, tmp_path):
    player, calls = make_player(overlay.instrument_p3_player(source), [], [], [0])
    metrics = player(packets(tmp_path / "empty.p3"))
    assert metrics["write_calls"] == metrics["submitted_frames"] == 0
    assert metrics["stream_start_to_first_write_return_ms"] is None
    assert metrics["max_write_ms"] is None
    assert metrics["min_write_available_frames"] is None
    assert metrics["output_overrun_reports"] is None
    assert metrics["output_latency_estimate_ms"] is None
    assert metrics["termination"] == "empty"
    assert calls == ["start", "stop", "close"]


def test_original_discards_underflow(source, tmp_path):
    player, calls = make_player(source, [True], [], [])
    assert player(packets(tmp_path / "audio.p3", 960)) is None
    assert calls == ["start", 960, "stop", "close"]


def test_drift_rejected(source):
    with pytest.raises(ValueError, match="anchor changed"):
        overlay.instrument_p3_player(
            source.replace("stream.write(audio_array)", "stream.write(other)")
        )


@pytest.mark.parametrize(("stage", "expected"), [
    ("start", ["start", "close"]),
    ("write", ["start", 960, "stop", "close"]),
    ("stop", ["start", 960, "stop", "close"]),
])
def test_player_releases_stream_on_fault(source, tmp_path, stage, expected):
    player, calls = make_player(
        overlay.instrument_p3_player(source), [False], [960], [0, 0.01, 0.02],
        fail_at=stage,
    )
    with pytest.raises(OSError, match=f"{stage} failure"):
        player(packets(tmp_path / "audio.p3", 960))
    assert calls == expected


def test_stop_preempts_remaining_packets(source, tmp_path):
    player, calls = make_player(
        overlay.instrument_p3_player(source), [False], [960], [0, 0.01, 0.02],
    )
    states = iter([False, True])
    metrics = player(
        packets(tmp_path / "audio.p3", 960, 960),
        stop_event=SimpleNamespace(is_set=lambda: next(states)),
    )
    assert metrics["submitted_frames"] == 960
    assert metrics["write_calls"] == 1
    assert metrics["termination"] == "stopped"
    assert calls == ["start", 960, "stop", "close"]


@pytest.mark.parametrize("tail", [
    b"\x00", b"\x00\x00", b"\x00\x00\x00", struct.pack(">BBH", 0, 0, 0),
    struct.pack(">BBH", 0, 0, 3) + b"9", struct.pack(">BBH", 1, 0, 1) + b"9",
    struct.pack(">BBH", 0, 1, 1) + b"9", struct.pack(">BBH", 0, 0, 1) + b"0",
    struct.pack(">BBH", 0, 0, 4) + b"1000", struct.pack(">BBH", 0, 0, 1) + b"!",
])
@pytest.mark.parametrize("valid_prefix", [False, True])
def test_corrupt_packet_never_reports_success(source, tmp_path, capsys, tail, valid_prefix):
    path = packets(tmp_path / "bad.p3", *([960] if valid_prefix else []))
    path.write_bytes(path.read_bytes() + tail)
    player, calls = make_player(
        overlay.instrument_p3_player(source), [False] if valid_prefix else [],
        [960] if valid_prefix else [], [0, 0.01, 0.02] if valid_prefix else [0],
    )
    with pytest.raises(ValueError):
        player(path)
    assert calls == ["start"] + ([960] if valid_prefix else []) + ["stop", "close"]
    assert "P3 host playback metrics" not in capsys.readouterr().out


def test_repeated_pause_does_not_contaminate_active_reports(source, tmp_path):
    player, _ = make_player(
        overlay.instrument_p3_player(source), [True] * 4, [960] * 4, list(range(9)),
    )
    states = iter([True, True, False, False, True, False, False, False])
    metrics = player(
        packets(tmp_path / "pause.p3", 960, 960, 960, 960),
        pause_event=SimpleNamespace(is_set=lambda: next(states)),
    )
    assert metrics["underflow_reports"] == 4
    assert metrics["underflow_reports_first_write"] == 1
    assert metrics["underflow_reports_after_pause"] == 2
    assert metrics["underflow_reports_active"] == 2


@pytest.mark.parametrize("payload", [b"", b"\x00"])
def test_gui_worker_stops_on_unplayable_file_even_in_repeat_mode(source, tmp_path, payload):
    path = tmp_path / "bad.p3"
    path.write_bytes(payload)
    instrumented = overlay.instrument_p3_player(source)
    player, calls = make_player(instrumented, [], [], [0])
    app_class = next(
        node for node in ast.parse(instrumented).body
        if isinstance(node, ast.ClassDef) and node.name == "P3PlayerApp"
    )
    worker = next(node for node in app_class.body if getattr(node, "name", "") == "play_audio")
    ns = {"play_p3_file": player, "tk": SimpleNamespace(END="end"), "os": os}
    exec(compile(ast.Module(body=[worker], type_ignores=[]), "p3_gui_player.py", "exec"), ns)
    statuses = []
    event = SimpleNamespace(is_set=lambda: False)
    app = SimpleNamespace(
        stop_event=event, pause_event=event, playlist=[str(path)], current_index=0,
        loop_playback=SimpleNamespace(get=lambda: True), is_playing=True, is_paused=False,
        playlist_listbox=SimpleNamespace(
            selection_clear=lambda *_: None, selection_set=lambda *_: None,
            activate=lambda *_: None,
        ),
        update_status=lambda message, color: statuses.append((message, color)),
    )
    ns["play_audio"](app)
    assert not app.is_playing and not app.is_paused
    assert statuses[-1][0].startswith("P3 playback failed:")
    assert statuses[-1][1] == "red"
    assert calls == ["start", "stop", "close"]

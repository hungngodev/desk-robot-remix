import sys
from types import SimpleNamespace


def test_cli_serve_bounds_request_drain_before_runtime_cleanup(monkeypatch):
    import uvicorn
    from desk_robot import api, cli

    settings = SimpleNamespace(mode="hardware")
    app = object()
    calls = []
    monkeypatch.setattr(cli, "load_settings", lambda path: settings)
    monkeypatch.setattr(cli, "load_env", lambda path: None)
    monkeypatch.setattr(api, "create_app", lambda config: app)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(sys, "argv", ["desk-robot", "serve"])

    cli.main()

    assert calls == [((app,), {
        "host": "127.0.0.1", "port": 8765, "timeout_graceful_shutdown": 1,
    })]

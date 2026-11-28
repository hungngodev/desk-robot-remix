"""Simulation demo must use the asynchronous runtime startup boundary."""

import pytest
from desk_robot import cli


@pytest.mark.asyncio
async def test_demo_awaits_runtime_factory(settings, monkeypatch):
    class StartupInterrupted(Exception):
        pass

    class RuntimeProbe:
        def __init__(self, config):
            pytest.fail("Demo must not initialize SQLite synchronously")

        @classmethod
        async def create(cls, config):
            assert config is settings
            raise StartupInterrupted

    monkeypatch.setattr(cli, "Runtime", RuntimeProbe)
    with pytest.raises(StartupInterrupted):
        await cli.demo(settings)

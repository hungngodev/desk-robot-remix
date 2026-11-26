"""Exercise serial reader ownership across interrupted telemetry frames."""

import asyncio
import sys
from types import SimpleNamespace

import pytest
from desk_robot import room_station


@pytest.mark.parametrize("partial", [b'{"seq":', b"x" * (room_station.MAX_FRAME_BYTES + 1)])
def test_partial_frame_disconnect_closes_before_reconnect(monkeypatch, partial):
    async def scenario():
        stop = asyncio.Event()
        events = []
        accepted = []
        ports = []
        nonces = iter(f"{n:016x}" for n in range(1, 5))
        monkeypatch.setattr(room_station.secrets, "token_hex", lambda _: next(nonces))
        monkeypatch.setattr(room_station, "require_local_serial_device", lambda _: None)

        class Decoder:
            def __init__(self, *, soil_calibration):
                self.epoch = len(ports)

            def accept(self, line, *, now):
                accepted.append((self.epoch, line))
                return line

        class Port:
            def __init__(self, *args, **kwargs):
                self.epoch = len(ports) + 1
                self.ack = None
                self.buffered = iter(
                    [] if self.epoch == 1 else [b"1}\n", b"SYNC_ACK 0000000000000001\n"]
                )
                self.chunks = iter(
                    [partial, OSError("unplugged mid-frame")]
                    if self.epoch == 1 else [b'{"seq":2}\n', OSError("unplugged again")]
                )
                ports.append(self)

            def __enter__(self):
                events.append(("open", self.epoch))
                return self

            def __exit__(self, *args):
                events.append(("close", self.epoch))

            def write(self, request):
                self.ack = b"SYNC_ACK " + request[6:-1] + b"\r\n"
                return len(request)

            def read_until(self, expected, *, size):
                assert expected == b"\n" and size == room_station.MAX_FRAME_BYTES + 1
                # Buffered suffix and retired ACK arrive before the current ACK.
                buffered = next(self.buffered, None)
                if buffered is not None:
                    return buffered
                if self.ack is not None:
                    ack, self.ack = self.ack, None
                    return ack
                chunk = next(self.chunks)
                if isinstance(chunk, OSError):
                    raise chunk
                return chunk

        def disconnected():
            events.append(("disconnect", len(ports)))
            if len(ports) == 2:
                stop.set()

        monkeypatch.setattr(room_station, "RoomStationDecoder", Decoder)
        monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))
        observed = []
        feed = room_station.RoomSerialFeed("/dev/cu.test", observed.append,
                                           on_disconnect=disconnected)
        await asyncio.wait_for(feed.run(stop), timeout=4)
        assert events == [
            ("open", 1), ("close", 1), ("disconnect", 1),
            ("open", 2), ("close", 2), ("disconnect", 2),
        ]
        assert accepted == [(2, b'{"seq":2}\n')]
        assert observed == [b'{"seq":2}\n']
        assert feed.received == 1
        assert feed.rejected == 1
        assert feed.last_error == "OSError"
        assert feed.callback_failures == 0

    asyncio.run(scenario())

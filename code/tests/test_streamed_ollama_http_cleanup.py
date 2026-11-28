"""Exercise the production Ollama stream owner and HTTP response lifetime."""
import asyncio
import json
from contextlib import aclosing
from types import SimpleNamespace

import httpx
import pytest
from desk_robot.conversation import OllamaChat


def frame(content, done=False):
    return (json.dumps({"message": {"content": content}, "done": done},
                       ensure_ascii=False) + "\n").encode()


def chat(client, url="http://ollama.local"):
    return OllamaChat(SimpleNamespace(ollama_url=url, ollama_model="local"), client)


class Body(httpx.AsyncByteStream):
    def __init__(self, *chunks, stall=False):
        self.chunks = chunks
        self.stall = stall
        self.reading = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk
        if self.stall:
            self.reading.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def client_for(body):
    return httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=body)
    ))


@pytest.mark.parametrize("tail,error", [
    (b'{"message":\n', RuntimeError),
    (b'{"message":', RuntimeError),
    (frame("Extra"), RuntimeError),
    (httpx.ReadError("connection lost"), httpx.ReadError),
    (httpx.ReadTimeout("read stalled"), httpx.ReadTimeout),
])
async def test_terminal_sentence_waits_for_validated_eof_and_closes(tail, error):
    body = Body(frame("Earlier sentence. "), frame("Terminal sentence. ", True), tail)
    async with client_for(body) as client:
        async with aclosing(chat(client).stream_reply([])) as stream:
            assert await anext(stream) == "Earlier sentence."
            with pytest.raises(error):
                await anext(stream)
            assert body.closed
            assert not client.is_closed


@pytest.mark.parametrize("invalid", [b'{"message":\n', b'{"message":'])
async def test_malformed_nonterminal_json_closes_response(invalid):
    body = Body(frame("Earlier sentence. "), invalid)
    async with client_for(body) as client:
        async with aclosing(chat(client).stream_reply([])) as stream:
            assert await anext(stream) == "Earlier sentence."
            with pytest.raises(RuntimeError, match="Malformed Ollama streaming frame"):
                await anext(stream)
            assert body.closed
            assert not client.is_closed


async def test_fragmented_utf8_and_json_terminal_sentences_close_at_eof():
    payload = frame("Café time. ") + frame("Ready? Yes! ", True)
    body = Body(*(bytes([byte]) for byte in payload))
    async with client_for(body) as client:
        async with aclosing(chat(client).stream_reply([])) as stream:
            assert await anext(stream) == "Café time."
            assert not body.closed
            assert await anext(stream) == "Ready?"
            assert body.closed
            assert [sentence async for sentence in stream] == ["Yes!"]


@pytest.mark.parametrize("terminal", [False, True])
async def test_external_cancel_while_reading_closes_response(terminal):
    body = Body(frame("Earlier sentence. "), frame("Pending sentence. ", terminal),
                stall=True)
    async with client_for(body) as client:
        async with aclosing(chat(client).stream_reply([])) as stream:
            assert await anext(stream) == "Earlier sentence."
            if not terminal:
                assert await anext(stream) == "Pending sentence."
            task = asyncio.create_task(anext(stream))
            try:
                await asyncio.wait_for(body.reading.wait(), 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert body.closed
                assert not client.is_closed
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_explicit_abort_while_speaker_owns_yield_closes_response():
    body = Body(frame("Earlier sentence. "), stall=True)
    async with client_for(body) as client:
        stream = chat(client).stream_reply([])
        try:
            assert await anext(stream) == "Earlier sentence."
            assert not body.closed
        finally:
            await stream.aclose()
        assert body.closed
        assert not client.is_closed


async def test_socket_read_timeout_closes_connection():
    # Keep production's configured timeout under assertion, but shorten the
    # actual socket read timeout for a fast, deterministic loopback test.
    class FastClient(httpx.AsyncClient):
        def stream(self, *args, **kwargs):
            assert kwargs["timeout"] == 60
            kwargs["timeout"] = httpx.Timeout(2, read=0.2)
            return super().stream(*args, **kwargs)

    disconnected = asyncio.Event()
    finished = asyncio.Event()

    async def serve(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in headers.splitlines()
                          if line.lower().startswith(b"content-length:"))
            await reader.readexactly(length)
            chunk = frame("Earlier sentence. ")
            writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            writer.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            await writer.drain()
            if await reader.read() == b"":
                disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()
            finished.set()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with FastClient(trust_env=False) as client:
            async with aclosing(chat(client, url).stream_reply([])) as stream:
                assert await asyncio.wait_for(anext(stream), 2) == "Earlier sentence."
                with pytest.raises(httpx.ReadTimeout):
                    await asyncio.wait_for(anext(stream), 2)
                await asyncio.wait_for(disconnected.wait(), 2)
                assert not client.is_closed
        await asyncio.wait_for(finished.wait(), 2)

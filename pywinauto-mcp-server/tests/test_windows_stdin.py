"""Exercise the Windows reader's readiness contract without platform stubs."""

from collections import deque

import anyio
import pytest

from autogenesis_windows_mcp._windows_stdin import WindowsStdin
from autogenesis_windows_mcp.cli import _Stdin


class Pipe:
    kind = "pipe"

    def __init__(self, chunks=()):
        self.chunks = deque(chunks)
        self.reads = []

    def available(self):
        return len(self.chunks[0]) if self.chunks else None

    def read(self, size):
        assert self.chunks and 0 < size <= len(self.chunks[0])
        self.reads.append(size)
        chunk = self.chunks.popleft()
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
        return chunk[:size]


@pytest.mark.anyio
async def test_open_idle_pipe_is_cancellable_without_starting_a_worker(monkeypatch):
    pipe = Pipe()
    pipe.available = lambda: 0
    async def forbidden_worker(*args, **kwargs):
        pytest.fail("Windows stdin started a blocking worker.")
    monkeypatch.setattr(anyio.to_thread, "run_sync", forbidden_worker)
    with anyio.move_on_after(0.03) as scope:
        await WindowsStdin(-1, api=pipe).read(4096)
        pytest.fail("An open idle pipe was treated as EOF.")
    assert scope.cancel_called
    assert pipe.reads == []


@pytest.mark.anyio
async def test_pipe_reads_only_available_bytes_and_broken_pipe_is_eof():
    pipe = Pipe([b"abc"])
    reader = WindowsStdin(-1, api=pipe)
    assert await reader.read(2) == b"ab"
    assert await reader.read(4096) == b"c"
    assert await reader.read(4096) == b""
    assert pipe.reads == [2, 1]


@pytest.mark.anyio
async def test_pipe_errors_are_not_disguised_as_eof():
    pipe = Pipe()
    def denied():
        raise OSError(5, "access denied")
    pipe.available = denied
    with pytest.raises(OSError):
        await WindowsStdin(-1, api=pipe).read(4096)


@pytest.mark.anyio
async def test_windows_chunks_preserve_line_buffering_final_fragment_and_eof():
    reader = object.__new__(_Stdin)
    reader.pending = b""
    reader.closed = anyio.Event()
    reader.windows = WindowsStdin(-1, api=Pipe([b"one", bytes([10]) + b"two"]))
    assert await anext(reader) == "one" + chr(10)
    assert not reader.closed.is_set()
    assert await anext(reader) == "two"
    with pytest.raises(StopAsyncIteration):
        await anext(reader)
    assert reader.closed.is_set()


class Console:
    kind = "console"

    def __init__(self, keys=()):
        self.keys = deque(keys)

    def key_ready(self):
        return bool(self.keys)

    def read_key(self):
        assert self.keys
        return self.keys.popleft()


@pytest.mark.anyio
async def test_console_handles_unicode_editing_extended_keys_and_eof():
    keys = [chr(0), "P", chr(0xD83D), chr(0xDE00), chr(8)]
    keys += list('"ok"') + [chr(13), chr(26)]
    reader = WindowsStdin(-1, api=Console(keys))
    assert await reader.read(4096) == ('"ok"' + chr(10)).encode()
    assert await reader.read(4096) == b""


@pytest.mark.anyio
async def test_idle_console_is_cancellable():
    with anyio.move_on_after(0.03) as scope:
        await WindowsStdin(-1, api=Console()).read(4096)
        pytest.fail("An idle console was treated as EOF.")
    assert scope.cancel_called


@pytest.mark.anyio
@pytest.mark.parametrize("api", [Pipe(), Console()])
async def test_explicit_close_releases_an_inflight_idle_read(api):
    if isinstance(api, Pipe):
        api.available = lambda: 0
    reader = WindowsStdin(-1, api=api)
    completed = anyio.Event()
    result = []

    async def consume():
        result.append(await reader.read(4096))
        completed.set()

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(consume)
        await anyio.sleep(0.03)
        reader.close()
        with anyio.fail_after(0.5):
            await completed.wait()
        tasks.cancel_scope.cancel()
    assert result == [b""]


@pytest.mark.anyio
async def test_protocol_stdin_close_marks_eof_without_closing_interpreter_handle():
    stdin = object.__new__(_Stdin)
    stdin.pending = b""
    stdin.closed = anyio.Event()
    stdin.windows = WindowsStdin(-1, api=Pipe())
    stdin.close()
    assert stdin.closed.is_set()
    with pytest.raises(StopAsyncIteration):
        await anext(stdin)

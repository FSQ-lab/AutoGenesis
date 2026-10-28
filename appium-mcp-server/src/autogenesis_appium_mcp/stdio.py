"""Cancellable POSIX stdio handles for the SDK's public stdio transport adapter."""

from contextlib import asynccontextmanager
import os
import sys

import anyio
from mcp.server.stdio import stdio_server


class Stdin:
    def __init__(self, fd):
        self.fd = fd
        self.buffer = bytearray()
        self.eof = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self.buffer[:newline + 1])
                del self.buffer[:newline + 1]
                return line.decode("utf-8", errors="replace")
            if self.eof:
                if not self.buffer:
                    raise StopAsyncIteration
                line = bytes(self.buffer)
                self.buffer.clear()
                return line.decode("utf-8", errors="replace")
            await anyio.wait_readable(self.fd)
            try:
                chunk = os.read(self.fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                self.eof = True
            self.buffer.extend(chunk)


class Stdout:
    def __init__(self, fd):
        self.fd = fd

    async def write(self, text):
        remaining = memoryview(text.encode("utf-8"))
        while remaining:
            await anyio.wait_writable(self.fd)
            try:
                written = os.write(self.fd, remaining)
            except BlockingIOError:
                continue
            remaining = remaining[written:]
        return len(text)

    async def flush(self):
        # Every write above reaches the descriptor; there is no userspace output buffer.
        await anyio.lowlevel.checkpoint()


@asynccontextmanager
async def cancellable_stdio():
    descriptors = (sys.stdin.fileno(), sys.stdout.fileno())
    restored = []
    try:
        for fd in descriptors:
            was_blocking = os.get_blocking(fd)
            os.set_blocking(fd, False)
            restored.append((fd, was_blocking))
        async with stdio_server(stdin=Stdin(descriptors[0]), stdout=Stdout(descriptors[1])) as streams:
            yield streams
    finally:
        for fd, was_blocking in reversed(restored):
            os.set_blocking(fd, was_blocking)

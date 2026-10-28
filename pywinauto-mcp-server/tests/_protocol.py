"""Raw stdio client that observes stdout validity and the actual exit status."""

import json
import os
import queue
import subprocess
import threading
import time

import pytest


class ProtocolProcess:
    def __init__(self, command, business, environment=None):
        env = os.environ.copy()
        for key in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(key, None)
        env.update(environment or {})
        env["PYTHONNOUSERSITE"] = "1"
        self.process = subprocess.Popen(command, cwd=business, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.stdout = []
        self.stderr = []
        self.messages = queue.Queue()
        self.transcript = []
        self.invalid_stdout = False
        self.next_id = 1
        self.readers = [threading.Thread(target=self._read_stdout, daemon=True), threading.Thread(target=self._read_stderr, daemon=True)]
        for reader in self.readers:
            reader.start()

    def _read_stdout(self):
        for line in self.process.stdout:
            self.stdout.append(line)
            try:
                message = json.loads(line)
                if message.get("jsonrpc") != "2.0":
                    raise ValueError()
                self.messages.put(message)
            except (ValueError, AttributeError):
                self.invalid_stdout = True
        self.messages.put(None)

    def _read_stderr(self):
        self.stderr.extend(self.process.stderr)

    def send(self, message):
        try:
            self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + chr(10))
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pytest.fail("Server closed stdin before the protocol request.", pytrace=False)

    def rpc(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        request = {"id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        self.send(request)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if message is None:
                pytest.fail("Server exited before the protocol response.", pytrace=False)
            self.transcript.append({"method": method, "response": message})
            if message.get("id") == request_id:
                return message
        pytest.fail("Timed out waiting for an MCP response.", pytrace=False)

    def initialize(self):
        response = self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "windows-package-acceptance", "version": "1.0"}})
        self.send({"method": "notifications/initialized"})
        return response

    def close_stdin(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()

    def wait(self):
        try:
            code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            pytest.fail("Server did not stop cleanly within ten seconds.", pytrace=False)
        for reader in self.readers:
            reader.join(timeout=2)
        if code != 0:
            pytest.fail("Server shutdown returned a nonzero exit status.", pytrace=False)
        if self.invalid_stdout:
            pytest.fail("Server wrote non-protocol data to stdout.", pytrace=False)
        if any("Traceback" in line or "ExceptionGroup" in line for line in self.stderr):
            pytest.fail("Server shutdown emitted an exception traceback.", pytrace=False)
        return code

    def assert_no_secret(self, secret):
        if any(secret in line for line in self.stdout + self.stderr):
            pytest.fail("Protocol or diagnostic output disclosed a secret.", pytrace=False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.close_stdin()
            self.wait()
        elif self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

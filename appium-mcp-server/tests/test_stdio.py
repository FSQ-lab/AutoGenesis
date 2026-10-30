"""Real wire acceptance in a clean business cwd, without a live Appium endpoint."""

import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import queue
import shutil
import subprocess
import signal
import threading
import sys
import time

import pytest
from autogenesis_agent_contract import load_contract

PRIVATE = "SYNTHETIC_APPIUM_WIRE_PRIVATE_D2C954"
URI = "autogenesis://agent-contract/identity"


def assert_private_absent(value):
    if PRIVATE in value:
        raise AssertionError("Private data escaped the MCP boundary")


class WireClient:
    def __init__(self, cwd, arguments, env=None, command=None):
        command = command or shutil.which("autogenesis-appium-mcp")
        assert command
        self.process = subprocess.Popen(
            [command, *arguments], cwd=cwd, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.lines = queue.Queue()
        self.stdout = []
        self.stderr = []
        self.counter = 0

        def read_stdout():
            for line in self.process.stdout:
                self.stdout.append(line)
                self.lines.put(line)
            self.lines.put(None)

        def read_stderr():
            self.stderr.extend(self.process.stderr.readlines())

        self.readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
        for reader in self.readers:
            reader.start()

    def send(self, value):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **value}) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.counter += 1
        self.send({"id": self.counter, "method": method, "params": params or {}})
        while True:
            line = self.lines.get(timeout=30)
            if line is None:
                raise AssertionError("MCP process exited before response")
            assert_private_absent(line)
            try:
                response = json.loads(line)
            except ValueError:
                raise AssertionError("Non-protocol stdout") from None
            assert response.get("jsonrpc") == "2.0"
            if response.get("id") == self.counter:
                return response

    def initialize(self):
        response = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {}, "clientInfo": {"name": "appium-package-acceptor", "version": "1.0"},
        })
        self.send({"method": "notifications/initialized"})
        return response["result"]

    def stop(self, *, terminate=False, interrupt=False):
        if self.process.poll() is None:
            if terminate:
                self.process.terminate()
            elif interrupt:
                self.process.send_signal(signal.SIGINT)
            elif not self.process.stdin.closed:
                self.process.stdin.close()
        try:
            code = self.process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            raise AssertionError("MCP did not stop cleanly") from None
        for reader in self.readers:
            reader.join(timeout=3)
            assert not reader.is_alive()
        assert_private_absent("".join(self.stdout + self.stderr))
        for line in self.stdout:
            try:
                json.loads(line)
            except ValueError:
                raise AssertionError("Non-protocol stdout") from None
        return code

    def cleanup(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)



class FakeAppiumEndpoint:
    def __init__(self, delete_status=200, stall_source=False, stall_delete=False):
        self.delete_status = delete_status
        self.stall_source = stall_source
        self.stall_delete = stall_delete
        self.source_requested = threading.Event()
        self.release_source = threading.Event()
        self.delete_requested = threading.Event()
        self.release_delete = threading.Event()
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def respond(self, value, status=200):
                payload = json.dumps({"value": value}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                owner.requests.append(("POST", self.path))
                session_id = f"owned-{sum(method == 'POST' for method, _ in owner.requests)}"
                self.respond({"sessionId": session_id, "capabilities": {"platformName": "mac"}})

            def do_GET(self):
                owner.requests.append(("GET", self.path))
                if self.path.endswith("/source"):
                    if owner.stall_source:
                        owner.source_requested.set()
                        owner.release_source.wait(timeout=30)
                        return
                    self.respond("<App/>")
                else:
                    self.respond({})

            def do_DELETE(self):
                owner.requests.append(("DELETE", self.path))
                if owner.stall_delete:
                    owner.delete_requested.set()
                    owner.release_delete.wait(timeout=30)
                self.respond(None, owner.delete_status)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        assert not self.thread.is_alive()


def runtime_config(tmp_path, endpoint):
    config = tmp_path / "appium-live.json"
    config.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"mac": {
        "platformName": "Mac",
        "automationName": "Mac2",
        "bundleId": "com.example.SessionLifecycle",
        "server_url": endpoint.url,
    }}}), encoding="utf-8")
    return config


def launch_owned_session(client):
    client.initialize()
    response = client.request("tools/call", {"name": "app_launch", "arguments": {}})
    assert response["result"].get("isError", False) is False
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["status"] == "success"


@pytest.mark.parametrize("stop_arguments", [
    pytest.param({}, id="eof"),
    pytest.param({"terminate": True}, id="sigterm"),
    pytest.param({"interrupt": True}, id="sigint", marks=pytest.mark.skipif(os.name != "posix", reason="POSIX signal lifecycle")),
])
def test_runtime_shutdown_deletes_exact_owned_session(tmp_path, stop_arguments):
    endpoint = FakeAppiumEndpoint()
    config = runtime_config(tmp_path, endpoint)
    client = WireClient(tmp_path, ["--platform", "mac", "--config", str(config)])
    try:
        launch_owned_session(client)
        assert client.stop(**stop_arguments) == 0
        assert [request for request in endpoint.requests if request[0] == "DELETE"] == [("DELETE", "/session/owned-1")]
    finally:
        client.cleanup()
        endpoint.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal lifecycle")
def test_sigterm_preempts_blocked_driver_request_and_deletes_session(tmp_path):
    endpoint = FakeAppiumEndpoint(stall_source=True)
    config = runtime_config(tmp_path, endpoint)
    client = WireClient(tmp_path, ["--platform", "mac", "--config", str(config)])
    try:
        client.initialize()
        client.counter += 1
        client.send({"id": client.counter, "method": "tools/call", "params": {"name": "app_launch", "arguments": {}}})
        assert endpoint.source_requested.wait(timeout=5)
        started = time.monotonic()
        assert client.stop(terminate=True) == 0
        assert time.monotonic() - started < 12
        assert [request for request in endpoint.requests if request[0] == "DELETE"] == [("DELETE", "/session/owned-1")]
    finally:
        endpoint.release_source.set()
        client.cleanup()
        endpoint.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal lifecycle")
def test_signal_interrupting_eof_cleanup_retries_owned_session_delete(tmp_path):
    endpoint = FakeAppiumEndpoint(stall_delete=True)
    config = runtime_config(tmp_path, endpoint)
    client = WireClient(tmp_path, ["--platform", "mac", "--config", str(config)])
    try:
        launch_owned_session(client)
        client.process.stdin.close()
        assert endpoint.delete_requested.wait(timeout=5)
        client.process.terminate()
        endpoint.release_delete.set()
        assert client.stop() == 0, "".join(client.stderr)
        assert [request for request in endpoint.requests if request[0] == "DELETE"] == [("DELETE", "/session/owned-1")]
    finally:
        endpoint.release_delete.set()
        client.cleanup()
        endpoint.close()


def test_runtime_exits_nonzero_when_session_deletion_is_not_acknowledged(tmp_path):
    endpoint = FakeAppiumEndpoint(delete_status=500)
    config = runtime_config(tmp_path, endpoint)
    client = WireClient(tmp_path, ["--platform", "mac", "--config", str(config)])
    try:
        launch_owned_session(client)
        assert client.stop() == 1
        assert [request for request in endpoint.requests if request[0] == "DELETE"] == [("DELETE", "/session/owned-1")]
        assert "".join(client.stderr).count("AutoGenesis Appium shutdown failed.") == 1
    finally:
        client.cleanup()
        endpoint.close()


def test_ten_runtime_disconnects_leave_no_owned_sessions(tmp_path):
    endpoint = FakeAppiumEndpoint()
    config = runtime_config(tmp_path, endpoint)
    try:
        for _ in range(10):
            client = WireClient(tmp_path, ["--platform", "mac", "--config", str(config)])
            try:
                launch_owned_session(client)
                assert client.stop() == 0
            finally:
                client.cleanup()
        posts = [path for method, path in endpoint.requests if method == "POST"]
        deletes = [path for method, path in endpoint.requests if method == "DELETE"]
        assert posts == ["/session"] * 10
        assert deletes == [f"/session/owned-{index}" for index in range(1, 11)]
    finally:
        endpoint.close()


def record_evidence(platform, result):
    text = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    assert_private_absent(text)
    destination = os.environ.get("AUTOGENESIS_APPIUM_EVIDENCE_DIR")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / (platform + ".json.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(root / (platform + ".json"))


@pytest.mark.parametrize("platform,count", [("ios", 31), ("android", 30), ("mac", 35)])
def test_stdio_initialize_tools_prompts_identity_config_and_eof(platform, count, tmp_path):
    # Deliberately unreachable: any eager session creation breaks acceptance.
    profile = {
        "platformName": platform,
        "server_url": "http://127.0.0.1:9/",
        "bstack:options": {"accessKey": "${APPIUM_WIRE_ACCESS_KEY}"},
        "nested": [{"password": "${APPIUM_WIRE_ACCESS_KEY}"}],
    }
    config = tmp_path / "appium.json"
    config.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {platform: profile}}))
    log_dir = tmp_path / "logs"
    env = dict(os.environ, APPIUM_WIRE_ACCESS_KEY=PRIVATE, AZURE_OPENAI_API_KEY=PRIVATE, MCP_LOG_FILE=str(log_dir))
    env.pop("PYTHONPATH", None)
    client = WireClient(tmp_path, ["--platform", platform, "--config", str(config)], env)
    try:
        initialize = client.initialize()
        assert initialize["instructions"] == load_contract().instructions
        tools = client.request("tools/list")["result"]["tools"]
        assert len(tools) == count
        assert {"app_launch", "session_close", "before_gen_code", "preview_code_changes", "confirm_code_changes", "get_current_config"} <= {tool["name"] for tool in tools}
        prompts = client.request("prompts/list")["result"]["prompts"]
        assert {prompt["name"] for prompt in prompts} == {
            "execute_scenario", "generate_scenario_test", "execute_natural_language_task",
        }
        cases = {
            "execute_scenario": {"scenario_text": "Given an app"},
            "generate_scenario_test": {"scenario_text": "Given an app", "feature_file_path": "features/app.feature"},
            "execute_natural_language_task": {"task_text": "Inspect the app title"},
        }
        rendered = {}
        for name, arguments in cases.items():
            result = client.request("prompts/get", {"name": name, "arguments": arguments})["result"]
            assert result["messages"][0]["content"]["text"] == load_contract().render(name, arguments)
            rendered[name] = result
        resources = client.request("resources/list")["result"]["resources"]
        assert [resource["uri"] for resource in resources] == [URI]
        identity = client.request("resources/read", {"uri": URI})["result"]
        assert json.loads(identity["contents"][0]["text"])["manifest_sha256"] == load_contract().identity.manifest_sha256
        calls = []
        for name, arguments in [
            ("get_current_config", {}), ("get_current_config", {"platform": platform}),
            ("get_current_config", {"platform": PRIVATE}),
            ("get_current_config", {"platform": {PRIVATE: PRIVATE}}),
            (PRIVATE, {}), ("reload_config", {}),
        ]:
            calls.append(client.request("tools/call", {"name": name, "arguments": arguments}))
        assert calls[0]["result"].get("isError", False) is False
        assert calls[-1]["result"].get("isError", False) is False
        code = client.stop()
        assert code == 0
        for log in log_dir.rglob("*"):
            if log.is_file():
                assert log.name == "mcp_server.log"
                assert_private_absent(log.read_text(encoding="utf-8"))
        record_evidence(platform, {
            "initialize": initialize, "tools": tools, "prompts": prompts,
            "rendered_prompts": rendered, "resources": resources, "identity": identity,
            "config_and_error_responses": calls, "shutdown_exit_code": code,
            "protocol_only_stdout": True, "private_canary_absent": True,
            "private_canary_absent_from_file_logs": True,
            "live_device_required": False, "source_checkout_required": False,
        })
    finally:
        client.cleanup()


@pytest.mark.parametrize("platform", ["ios", "android", "mac"])
def test_packaged_default_template_and_sigterm_shutdown(platform, tmp_path):
    client = WireClient(tmp_path, ["--platform", platform])
    try:
        client.initialize()
        client.request("tools/list")
        assert not client.process.stdin.closed
        started = time.monotonic()
        code = client.stop(terminate=True)
        assert code == 0
        record_evidence(platform + "-sigterm", {
            "stdin_open_when_signalled": True, "shutdown_exit_code": code,
            "shutdown_seconds": round(time.monotonic() - started, 3),
        })
    finally:
        client.cleanup()


def test_sigterm_stops_watcher_and_quits_driver_with_stdin_open(tmp_path, config_path):
    marker = tmp_path / "cleanup.json"
    fixture = Path(__file__).parent / "fixtures/signal_cleanup.py"
    client = WireClient(tmp_path, [str(fixture), str(config_path), str(marker)], command=sys.executable)
    try:
        client.initialize()
        client.request("tools/list")
        assert not client.process.stdin.closed
        assert client.stop(terminate=True) == 0
        cleanup = json.loads(marker.read_text())
        assert cleanup == {"driver_quit": True, "watcher_stopped": True}
        record_evidence("sigterm-cleanup", cleanup)
    finally:
        client.cleanup()

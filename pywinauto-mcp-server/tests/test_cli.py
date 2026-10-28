from pathlib import Path

import pytest

from autogenesis_windows_mcp import cli


class StdoutStub:
    buffer = object()

    def write(self, text):
        return len(text)

    def flush(self):
        pass


@pytest.mark.parametrize("transport", ["stdio"])
def test_sync_main_preserves_app_config_transport_and_source_defaults(monkeypatch, transport):
    calls = []
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli.sys, "stdout", StdoutStub())
    monkeypatch.setattr(cli, "load_app_config", lambda app, path: calls.append((app, path)) or {"selected": True})
    monkeypatch.setattr(cli, "create_server", lambda config, root=None: calls.append((config, root)) or "server")
    async def serve(server, selected_transport):
        calls.append((server, selected_transport))
    monkeypatch.setattr(cli, "_serve", serve)
    assert cli.main(["--app", "second", "--config", "apps.json", "--transport", transport, "--project-root", "."]) == 0
    assert calls == [("second", "apps.json"), ({"selected": True}, "."), ("server", transport)]
    calls.clear()
    assert cli.main([], default_config=Path("source.json"), default_transport="stdio") == 0
    assert calls[-1] == ("server", "stdio")
    assert calls[0] == (None, Path("source.json"))
    calls.clear()
    assert cli.main([]) == 0
    assert calls[-1] == ("server", "stdio")


def test_invalid_config_never_constructs_server(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "create_server", lambda config, root=None: pytest.fail("Server started before validating configuration."))
    assert cli.main(["--config", str(tmp_path / "absent.json")]) == 2
    assert "AUTOGENESIS_CONFIG_INVALID" in caplog.text


def test_incidental_stdout_is_dropped_without_relogging(capsys):
    sink = cli._ProtocolStdout(StdoutStub())
    assert sink.write("sensitive library diagnostic") > 0
    sink.flush()
    assert capsys.readouterr() == ("", "")


def test_cli_validation_does_not_echo_invalid_arguments(capsys):
    import uuid
    canary = uuid.uuid4().hex
    with pytest.raises(SystemExit) as caught:
        cli.main(["--transport", canary])
    assert caught.value.code == 2
    if canary in capsys.readouterr().err:
        pytest.fail("Argument diagnostics disclosed a secret.", pytrace=False)


@pytest.mark.parametrize("error,expected", [(EOFError(), 0), (BrokenPipeError(), 0), (KeyboardInterrupt(), 0), (ValueError("private startup details"), 1)])
def test_shutdown_errors_are_distinguished_from_startup_failures(monkeypatch, caplog, error, expected):
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli.sys, "stdout", StdoutStub())
    monkeypatch.setattr(cli, "load_app_config", lambda *args: {})
    monkeypatch.setattr(cli, "create_server", lambda config, root=None: object())
    async def serve(*args):
        raise error
    monkeypatch.setattr(cli, "_serve", serve)
    assert cli.main([]) == expected
    assert "private startup details" not in caplog.text

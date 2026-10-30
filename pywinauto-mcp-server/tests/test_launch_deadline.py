import asyncio
import sys
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Real Windows driver imports required")]


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    async def sleep(self, duration):
        self.sleeps.append(duration)
        self.now += duration


class FakeHandle:
    def __init__(self):
        self.closed = False

    def Close(self):
        self.closed = True


class LaunchHarness:
    def __init__(self, monkeypatch, manager, clock, windows, process_start_seconds=0.0):
        from autogenesis_windows_mcp import app_session

        self.app_session = app_session
        self.clock = clock
        self.windows = windows
        self.process_start_seconds = process_start_seconds
        self.launched_at = 0.0
        self.probes = 0
        self.process_handle = FakeHandle()
        self.thread_handle = FakeHandle()

        harness = self

        class FakeTime:
            def timestamp(self):
                return harness.launched_at

        class FakeProcess:
            def __init__(self, process_id):
                self.process_id = process_id

            def create_time(self):
                return harness.launched_at

            def ppid(self):
                return 0

        class FakeDesktop:
            def __init__(self, backend):
                assert backend == "uia"

            def windows(self, **kwargs):
                harness.probes += 1
                return list(harness.windows())

        class FakeWindowSpec:
            def __init__(self, wrapper):
                self.wrapper = wrapper

            def exists(self, timeout=0):
                assert timeout == 0
                return True

            def wrapper_object(self):
                return self.wrapper

        class FakeApplication:
            def __init__(self, backend):
                assert backend == "uia"
                self.wrapper = None

            def connect(self, **kwargs):
                handle = kwargs["handle"]
                self.wrapper = next(window for window in harness.windows() if window.handle == handle)
                return self

            def window(self, **kwargs):
                assert kwargs["predicate_func"](self.wrapper.element_info)
                return FakeWindowSpec(self.wrapper)

        def create_process(*args):
            clock.now += self.process_start_seconds
            self.launched_at = clock.now
            return self.process_handle, self.thread_handle, 11, 1

        monkeypatch.setattr(app_session, "_monotonic", clock.monotonic)
        monkeypatch.setattr(app_session, "_sleep", clock.sleep)
        monkeypatch.setattr(app_session.win32process, "CreateProcess", create_process)
        monkeypatch.setattr(
            app_session.win32process,
            "GetProcessTimes",
            lambda handle: {"CreationTime": FakeTime(), "ExitTime": FakeTime()},
        )
        monkeypatch.setattr(app_session.psutil, "Process", FakeProcess)
        monkeypatch.setattr(app_session, "Desktop", FakeDesktop)
        monkeypatch.setattr(app_session, "Application", FakeApplication)
        monkeypatch.setattr(manager, "kill_app_process_by_path", lambda: None)


def window(clock, handle=101, visible_at=0.0, enabled_at=0.0):
    class FakeWindow:
        element_info = SimpleNamespace(handle=handle, process_id=11, runtime_id=(handle,))

        def __init__(self):
            self.handle = handle

        def is_visible(self):
            return clock.now >= visible_at

        def is_enabled(self):
            return clock.now >= enabled_at

    return FakeWindow()


def manager(timeout=None):
    from autogenesis_windows_mcp.app_session import AppSessionManager

    config = {
        "exe": r"C:\Windows\System32\deadline-test.exe",
        "window_title_re": ".*Deadline Test.*",
        "launch_args": [],
    }
    if timeout is not None:
        config["launch_timeout_seconds"] = timeout
    return AppSessionManager(config)


async def launch(app):
    from autogenesis_agent_contract import tool_execution

    def app_launch():
        pass

    with tool_execution(app_launch, (), {}):
        return await app.app_launch()


@pytest.mark.anyio
async def test_launch_uses_default_budget_and_succeeds_at_next_short_poll(monkeypatch):
    clock = FakeClock()
    app = manager()
    target = window(clock)
    harness = LaunchHarness(monkeypatch, app, clock, lambda: [] if clock.now < 1.2 else [target])

    assert app.launch_timeout_seconds == 15
    assert await launch(app) is True
    assert clock.now == 1.5
    assert clock.sleeps == [0.5, 0.5, 0.5]
    assert harness.process_handle.closed and harness.thread_handle.closed


@pytest.mark.anyio
async def test_launch_deadline_stops_without_a_late_probe_or_sleep(monkeypatch):
    from autogenesis_windows_mcp import app_session

    clock = FakeClock()
    app = manager(timeout=1)
    harness = LaunchHarness(monkeypatch, app, clock, lambda: [])

    with pytest.raises(app_session._LaunchTimeout) as caught:
        await launch(app)

    assert caught.value.deepest_state is app_session._LaunchState.PROCESS_STARTED
    assert clock.now == 1
    assert clock.sleeps == [0.5, 0.5]
    assert harness.probes == 2
    assert harness.process_handle.closed and harness.thread_handle.closed


@pytest.mark.anyio
async def test_launch_polls_visibility_and_enabled_state_within_one_budget(monkeypatch):
    clock = FakeClock()
    app = manager(timeout=2)
    target = window(clock, visible_at=0.5, enabled_at=1.0)
    harness = LaunchHarness(monkeypatch, app, clock, lambda: [target])

    assert await launch(app) is True
    assert clock.now == 1
    assert clock.sleeps == [0.5, 0.5]
    assert harness.probes == 3


@pytest.mark.anyio
async def test_launch_rejects_multiple_provenance_valid_windows_without_retry(monkeypatch):
    from autogenesis_windows_mcp import app_session

    clock = FakeClock()
    app = manager(timeout=2)
    targets = [window(clock, handle=101), window(clock, handle=102)]
    harness = LaunchHarness(monkeypatch, app, clock, lambda: targets)

    with pytest.raises(app_session._WindowAmbiguous):
        await launch(app)

    assert clock.sleeps == []
    assert harness.probes == 1
    assert harness.process_handle.closed


@pytest.mark.anyio
@pytest.mark.parametrize(
    "visible_at,enabled_at,expected_state",
    [
        (2.0, 0.0, "EXISTS"),
        (0.0, 2.0, "VISIBLE"),
    ],
)
async def test_launch_timeout_reports_deepest_readiness_state(
    monkeypatch, visible_at, enabled_at, expected_state
):
    from autogenesis_windows_mcp import app_session

    clock = FakeClock()
    app = manager(timeout=1)
    target = window(clock, visible_at=visible_at, enabled_at=enabled_at)
    LaunchHarness(monkeypatch, app, clock, lambda: [target])

    with pytest.raises(app_session._LaunchTimeout) as caught:
        await launch(app)

    assert caught.value.deepest_state is app_session._LaunchState[expected_state]


@pytest.mark.anyio
async def test_process_start_consumes_the_same_launch_budget(monkeypatch):
    from autogenesis_windows_mcp import app_session

    clock = FakeClock()
    app = manager(timeout=1)
    harness = LaunchHarness(
        monkeypatch, app, clock, lambda: [], process_start_seconds=1.0
    )

    with pytest.raises(app_session._LaunchTimeout):
        await launch(app)

    assert clock.now == 1
    assert harness.probes == 0
    assert clock.sleeps == []


@pytest.mark.anyio
async def test_launch_wait_is_cancellable_at_poll_checkpoint(monkeypatch):
    from autogenesis_windows_mcp import app_session

    clock = FakeClock()
    app = manager(timeout=15)
    harness = LaunchHarness(monkeypatch, app, clock, lambda: [])
    sleeping = asyncio.Event()

    async def cancellable_sleep(duration):
        sleeping.set()
        await asyncio.Future()

    monkeypatch.setattr(app_session, "_sleep", cancellable_sleep)
    task = asyncio.create_task(launch(app))
    await sleeping.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert harness.probes == 1
    assert harness.process_handle.closed and harness.thread_handle.closed

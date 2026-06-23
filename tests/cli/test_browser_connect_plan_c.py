"""Tests for /browser connect/status routing through ensure_local_chromium_cdp.

Plan-C step 3 — verifies that:

* ``/browser connect`` (without explicit URL) reuses
  ``hermes_cli.browser_connect.ensure_local_chromium_cdp`` so it follows
  the same launch pipeline as ``browser_navigate``'s prefer_local_chromium
  auto-attach.
* The default port comes from ``DEFAULT_BROWSER_CDP_PORT`` and not the
  legacy hard-coded ``9222``.
* Configured ``executable_path`` / ``user_data_dir`` / ``cdp_port`` from
  ``config.yaml`` are passed through to the launcher.
* Diagnostics fall back to ``manual_chrome_debug_command`` when no binary
  is available.
"""
from contextlib import redirect_stdout
from io import StringIO
import os
from queue import Queue
from unittest.mock import patch

from cli import HermesCLI
from hermes_cli.browser_connect import DEFAULT_BROWSER_CDP_PORT


def _make_cli():
    cli = HermesCLI.__new__(HermesCLI)
    cli._pending_input = Queue()
    return cli


class TestBrowserConnectUsesEnsureHelper:
    def test_connect_uses_default_port_from_browser_connect(self, monkeypatch):
        """No explicit URL → /browser connect targets DEFAULT_BROWSER_CDP_PORT."""
        cli = _make_cli()
        monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

        with patch("hermes_cli.cli_commands_mixin.is_browser_debug_ready", return_value=True), \
             patch("tools.browser_tool.cleanup_all_browsers"), \
             patch("tools.browser_tool._ensure_cdp_supervisor"), \
             patch("hermes_cli.cli_commands_mixin.read_raw_config", create=True, return_value={}), \
             redirect_stdout(StringIO()):
            cli._handle_browser_command("/browser connect")

        endpoint = os.environ["BROWSER_CDP_URL"]
        assert endpoint == f"http://127.0.0.1:{DEFAULT_BROWSER_CDP_PORT}"
        # Cleanup so we don't leak into other tests
        os.environ.pop("BROWSER_CDP_URL", None)

    def test_connect_invokes_ensure_local_chromium_cdp_when_port_not_ready(self, monkeypatch):
        """When the port isn't reachable yet, the helper is asked to launch a browser."""
        cli = _make_cli()
        monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

        ensure_calls = []

        def fake_ensure(port=None, executable_path=None, user_data_dir=None, wait_seconds=5.0):
            ensure_calls.append({
                "port": port,
                "executable_path": executable_path,
                "user_data_dir": user_data_dir,
                "wait_seconds": wait_seconds,
            })
            return f"ws://127.0.0.1:{port}/devtools/browser/abc123"

        readiness = iter([False, True])

        with patch(
            "hermes_cli.cli_commands_mixin.is_browser_debug_ready",
            side_effect=lambda *_a, **_k: next(readiness),
        ), patch(
            "hermes_cli.cli_commands_mixin.ensure_local_chromium_cdp",
            side_effect=fake_ensure,
        ), patch("tools.browser_tool.cleanup_all_browsers"), \
             patch("tools.browser_tool._ensure_cdp_supervisor"), \
             redirect_stdout(StringIO()):
            cli._handle_browser_command("/browser connect")

        assert len(ensure_calls) == 1
        call = ensure_calls[0]
        assert call["port"] == DEFAULT_BROWSER_CDP_PORT
        assert call["executable_path"] is None
        assert call["user_data_dir"] is None
        # /browser connect should still publish the env var on success
        assert os.environ.get("BROWSER_CDP_URL", "").startswith("http://127.0.0.1:")
        os.environ.pop("BROWSER_CDP_URL", None)

    def test_connect_passes_config_overrides_to_launcher(self, monkeypatch):
        """executable_path / user_data_dir / cdp_port from config.yaml flow through."""
        cli = _make_cli()
        monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

        ensure_calls = []

        def fake_ensure(port=None, executable_path=None, user_data_dir=None, wait_seconds=5.0):
            ensure_calls.append({
                "port": port,
                "executable_path": executable_path,
                "user_data_dir": user_data_dir,
            })
            return f"ws://127.0.0.1:{port}/devtools/browser/zzz"

        cfg = {
            "browser": {
                "cdp_port": 9333,
                "executable_path": "/opt/Chromium/chromium",
                "user_data_dir": "/tmp/hermes-chrome",
            }
        }
        readiness = iter([False, True])

        with patch(
            "hermes_cli.cli_commands_mixin.is_browser_debug_ready",
            side_effect=lambda *_a, **_k: next(readiness),
        ), patch(
            "hermes_cli.cli_commands_mixin.ensure_local_chromium_cdp",
            side_effect=fake_ensure,
        ), patch("hermes_cli.config.read_raw_config", return_value=cfg), \
             patch("tools.browser_tool.cleanup_all_browsers"), \
             patch("tools.browser_tool._ensure_cdp_supervisor"), \
             redirect_stdout(StringIO()):
            cli._handle_browser_command("/browser connect")

        assert ensure_calls == [
            {
                "port": 9333,
                "executable_path": "/opt/Chromium/chromium",
                "user_data_dir": "/tmp/hermes-chrome",
            }
        ]
        os.environ.pop("BROWSER_CDP_URL", None)

    def test_connect_falls_back_to_manual_command_when_launch_fails_but_binary_known(
        self, monkeypatch
    ):
        """ensure_local_chromium_cdp fails → surface manual command for the known binary."""
        cli = _make_cli()
        monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

        ensure_calls = []
        manual_calls = []

        def fake_ensure(port=None, executable_path=None, user_data_dir=None, wait_seconds=5.0):
            ensure_calls.append({
                "port": port,
                "executable_path": executable_path,
                "user_data_dir": user_data_dir,
            })
            return None

        def fake_manual(port, system, executable_path=None, user_data_dir=None):
            manual_calls.append({
                "port": port,
                "executable_path": executable_path,
                "user_data_dir": user_data_dir,
            })
            return f"/usr/bin/chromium --remote-debugging-port={port}"

        cfg = {
            "browser": {
                "cdp_port": DEFAULT_BROWSER_CDP_PORT,
                "executable_path": "/custom/path",
                "user_data_dir": "/custom/data",
            }
        }
        buf = StringIO()
        with patch(
            "hermes_cli.cli_commands_mixin.is_browser_debug_ready",
            return_value=False,
        ), patch(
            "hermes_cli.cli_commands_mixin.ensure_local_chromium_cdp",
            side_effect=fake_ensure,
        ), patch(
            "hermes_cli.cli_commands_mixin.manual_chrome_debug_command",
            side_effect=fake_manual,
        ), patch("hermes_cli.config.read_raw_config", return_value=cfg), \
             patch("tools.browser_tool.cleanup_all_browsers"), \
             patch("tools.browser_tool._ensure_cdp_supervisor"), \
             redirect_stdout(buf):
            cli._handle_browser_command("/browser connect")

        # ensure_local_chromium_cdp must be invoked first with the config overrides
        assert ensure_calls == [
            {
                "port": DEFAULT_BROWSER_CDP_PORT,
                "executable_path": "/custom/path",
                "user_data_dir": "/custom/data",
            }
        ]
        # Then manual_chrome_debug_command consulted with the same overrides
        assert manual_calls == [
            {
                "port": DEFAULT_BROWSER_CDP_PORT,
                "executable_path": "/custom/path",
                "user_data_dir": "/custom/data",
            }
        ]
        # No connection should be registered
        assert os.environ.get("BROWSER_CDP_URL") is None
        out = buf.getvalue()
        # Branch anchor: this is the `if chrome_cmd:` path, not the no-binary `else`
        assert "Launch a Chromium-family browser manually" in out
        assert "/usr/bin/chromium" in out

    def test_connect_falls_back_to_no_binary_message_when_manual_command_unknown(
        self, monkeypatch
    ):
        """ensure_local_chromium_cdp fails AND no candidate binary → no-binary message."""
        cli = _make_cli()
        monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

        buf = StringIO()
        with patch(
            "hermes_cli.cli_commands_mixin.is_browser_debug_ready",
            return_value=False,
        ), patch(
            "hermes_cli.cli_commands_mixin.ensure_local_chromium_cdp",
            return_value=None,
        ), patch(
            "hermes_cli.cli_commands_mixin.manual_chrome_debug_command",
            return_value=None,
        ), patch("hermes_cli.config.read_raw_config", return_value={}), \
             patch("tools.browser_tool.cleanup_all_browsers"), \
             patch("tools.browser_tool._ensure_cdp_supervisor"), \
             redirect_stdout(buf):
            cli._handle_browser_command("/browser connect")

        assert os.environ.get("BROWSER_CDP_URL") is None
        out = buf.getvalue()
        # Branch anchor: this is the `else` branch when no candidate binary exists
        assert "No supported Chromium-family browser executable found" in out
        assert "Launch a Chromium-family browser manually" not in out

    def test_connect_with_explicit_url_does_not_invoke_helper(self, monkeypatch):
        """An explicit `/browser connect ws://host:port` skips ensure helper."""
        cli = _make_cli()
        monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

        ensure_called = False

        def fake_ensure(*_a, **_k):
            nonlocal ensure_called
            ensure_called = True
            return "should-not-be-used"

        with patch(
            "hermes_cli.cli_commands_mixin.is_browser_debug_ready",
            return_value=True,
        ), patch(
            "hermes_cli.cli_commands_mixin.ensure_local_chromium_cdp",
            side_effect=fake_ensure,
        ), patch("tools.browser_tool.cleanup_all_browsers"), \
             patch("tools.browser_tool._ensure_cdp_supervisor"), \
             redirect_stdout(StringIO()):
            cli._handle_browser_command("/browser connect ws://example.com:7777")

        assert ensure_called is False
        assert os.environ["BROWSER_CDP_URL"].startswith("ws://example.com:7777")
        os.environ.pop("BROWSER_CDP_URL", None)


class TestBrowserStatusDefaultPort:
    def test_status_uses_default_cdp_port_when_endpoint_lacks_port(self, monkeypatch):
        """/browser status falls back to DEFAULT_BROWSER_CDP_PORT, not legacy 9222."""
        cli = _make_cli()
        # An endpoint without a numeric port — exercise the fallback branch.
        monkeypatch.setenv("BROWSER_CDP_URL", "ws://localhost/devtools/browser/abc")

        captured_port = []

        class FakeSocket:
            def __init__(self, *_a, **_k):
                pass

            def settimeout(self, _t):
                pass

            def connect(self, target):
                captured_port.append(target[1])

            def close(self):
                pass

        with patch("socket.socket", side_effect=FakeSocket), \
             redirect_stdout(StringIO()):
            cli._handle_browser_command("/browser status")

        # Falls back to default port — not legacy 9222
        assert captured_port == [DEFAULT_BROWSER_CDP_PORT]
        os.environ.pop("BROWSER_CDP_URL", None)

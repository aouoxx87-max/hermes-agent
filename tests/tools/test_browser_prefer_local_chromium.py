"""Tests for prefer_local_chromium routing in _get_session_info (Plan C).

Covers _maybe_create_local_chromium_cdp_session and its integration with
_get_session_info — when ``browser.prefer_local_chromium`` is enabled,
local sessions should attach to a Chromium-family browser via CDP rather
than spawning Playwright's bundled Chromium through agent-browser.
"""
from unittest.mock import Mock

import tools.browser_tool as browser_tool


WS_URL = "ws://127.0.0.1:9226/devtools/browser/abc123"


def _reset_session_state(monkeypatch):
    monkeypatch.setattr(browser_tool, "_active_sessions", {})
    monkeypatch.setattr(browser_tool, "_cached_cloud_provider", None)
    monkeypatch.setattr(browser_tool, "_cloud_provider_resolved", False)
    monkeypatch.setattr(browser_tool, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(browser_tool, "_update_session_activity", lambda t: None)
    monkeypatch.setattr(browser_tool, "_ensure_cdp_supervisor", lambda t: None)


class TestPreferLocalChromiumSession:
    def test_no_cloud_with_prefer_local_creates_cdp_session(self, monkeypatch):
        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {
                "browser": {
                    "prefer_local_chromium": True,
                    "cdp_port": 9226,
                    "executable_path": "",
                    "user_data_dir": "",
                }
            },
        )
        ensure = Mock(return_value=WS_URL)
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        session = browser_tool._get_session_info("task-1")

        assert session["cdp_url"] == WS_URL
        assert session["features"] == {"cdp_override": True}
        assert session["session_name"].startswith("cdp_")
        ensure.assert_called_once_with(
            port=9226,
            executable_path=None,
            user_data_dir=None,
        )

    def test_prefer_local_disabled_uses_pure_local_session(self, monkeypatch):
        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {"browser": {"prefer_local_chromium": False}},
        )
        ensure = Mock()
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        session = browser_tool._get_session_info("task-2")

        assert session["features"] == {"local": True}
        assert session["cdp_url"] is None
        assert session["session_name"].startswith("h_")
        ensure.assert_not_called()

    def test_prefer_local_falls_back_to_local_when_no_browser(self, monkeypatch):
        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {"browser": {"prefer_local_chromium": True, "cdp_port": 9226}},
        )
        ensure = Mock(return_value=None)
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        session = browser_tool._get_session_info("task-3")

        assert session["features"] == {"local": True}
        assert session["session_name"].startswith("h_")
        ensure.assert_called_once()

    def test_force_local_sidecar_with_prefer_local_uses_cdp(self, monkeypatch):
        _reset_session_state(monkeypatch)
        provider = Mock()
        provider.create_session.side_effect = AssertionError(
            "cloud provider should be skipped for ::local key"
        )
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: provider)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {"browser": {"prefer_local_chromium": True, "cdp_port": 9226}},
        )
        ensure = Mock(return_value=WS_URL)
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        session = browser_tool._get_session_info("default::local")

        assert session["cdp_url"] == WS_URL
        assert session["features"] == {"cdp_override": True}
        assert provider.create_session.call_count == 0

    def test_existing_cdp_override_skips_prefer_local_path(self, monkeypatch):
        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(
            browser_tool,
            "_get_cdp_override",
            lambda: "ws://other-host:9999/devtools/browser/zzz",
        )
        ensure = Mock()
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        session = browser_tool._get_session_info("task-4")

        assert session["cdp_url"] == "ws://other-host:9999/devtools/browser/zzz"
        ensure.assert_not_called()

    def test_prefer_local_passes_custom_port_executable_and_user_data_dir(self, monkeypatch):
        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {
                "browser": {
                    "prefer_local_chromium": True,
                    "cdp_port": 9333,
                    "executable_path": "/opt/Chromium/chromium",
                    "user_data_dir": "/tmp/hermes-chrome",
                }
            },
        )
        ensure = Mock(return_value=WS_URL)
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        browser_tool._get_session_info("task-5")

        ensure.assert_called_once_with(
            port=9333,
            executable_path="/opt/Chromium/chromium",
            user_data_dir="/tmp/hermes-chrome",
        )

    def test_prefer_local_invalid_port_falls_back_to_default(self, monkeypatch):
        from hermes_cli.browser_connect import DEFAULT_BROWSER_CDP_PORT

        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {
                "browser": {"prefer_local_chromium": True, "cdp_port": "not-a-number"}
            },
        )
        ensure = Mock(return_value=WS_URL)
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        browser_tool._get_session_info("task-6")

        ensure.assert_called_once_with(
            port=DEFAULT_BROWSER_CDP_PORT,
            executable_path=None,
            user_data_dir=None,
        )

    def test_supervisor_started_when_prefer_local_promotes_to_cdp(self, monkeypatch):
        _reset_session_state(monkeypatch)
        called_with = []

        def fake_supervisor(task_id):
            called_with.append(task_id)

        monkeypatch.setattr(browser_tool, "_ensure_cdp_supervisor", fake_supervisor)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {"browser": {"prefer_local_chromium": True}},
        )
        monkeypatch.setattr(
            "hermes_cli.browser_connect.ensure_local_chromium_cdp",
            lambda **_: WS_URL,
        )

        browser_tool._get_session_info("task-7")

        assert called_with == ["task-7"]

    def test_supervisor_skipped_for_pure_local_session(self, monkeypatch):
        _reset_session_state(monkeypatch)
        called_with = []
        monkeypatch.setattr(
            browser_tool, "_ensure_cdp_supervisor", lambda t: called_with.append(t)
        )
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")
        monkeypatch.setattr(
            "hermes_cli.config.read_raw_config",
            lambda: {"browser": {"prefer_local_chromium": False}},
        )

        browser_tool._get_session_info("task-8")

        assert called_with == []

    def test_config_read_failure_does_not_break_session_creation(self, monkeypatch):
        _reset_session_state(monkeypatch)
        monkeypatch.setattr(browser_tool, "_get_cloud_provider", lambda: None)
        monkeypatch.setattr(browser_tool, "_get_cdp_override", lambda: "")

        def boom():
            raise RuntimeError("config read explosion")

        monkeypatch.setattr("hermes_cli.config.read_raw_config", boom)
        ensure = Mock()
        monkeypatch.setattr("hermes_cli.browser_connect.ensure_local_chromium_cdp", ensure)

        session = browser_tool._get_session_info("task-9")

        assert session["features"] == {"local": True}
        ensure.assert_not_called()

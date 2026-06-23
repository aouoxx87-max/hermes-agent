"""Unit tests for hermes_cli.browser_connect.ensure_local_chromium_cdp."""

from unittest.mock import patch

import hermes_cli.browser_connect as browser_connect
from hermes_cli.browser_connect import (
    DEFAULT_BROWSER_CDP_PORT,
    ensure_local_chromium_cdp,
)


WS_URL = "ws://127.0.0.1:9226/devtools/browser/abc123"
DEFAULT_BASE_URL = f"http://127.0.0.1:{DEFAULT_BROWSER_CDP_PORT}"


class TestEnsureLocalChromiumCdp:
    def test_returns_resolved_ws_url_when_port_already_ready(self):
        with patch.object(browser_connect, "is_browser_debug_ready", return_value=True), \
             patch.object(browser_connect, "try_launch_chrome_debug") as mock_launch, \
             patch("tools.browser_tool._resolve_cdp_override", return_value=WS_URL) as mock_resolve:
            result = ensure_local_chromium_cdp()

        assert result == WS_URL
        mock_launch.assert_not_called()
        mock_resolve.assert_called_once_with(DEFAULT_BASE_URL)

    def test_launches_browser_then_polls_until_ready(self):
        readiness_calls = iter([False, False, True])

        def fake_ready(_url, timeout=1.0):
            return next(readiness_calls)

        with patch.object(browser_connect, "is_browser_debug_ready", side_effect=fake_ready), \
             patch.object(browser_connect, "try_launch_chrome_debug", return_value=True) as mock_launch, \
             patch.object(browser_connect.time, "sleep"), \
             patch("tools.browser_tool._resolve_cdp_override", return_value=WS_URL):
            result = ensure_local_chromium_cdp(wait_seconds=2.0)

        assert result == WS_URL
        mock_launch.assert_called_once_with(
            port=DEFAULT_BROWSER_CDP_PORT,
            executable_path=None,
            user_data_dir=None,
        )

    def test_returns_none_when_no_browser_binary_available(self):
        with patch.object(browser_connect, "is_browser_debug_ready", return_value=False), \
             patch.object(browser_connect, "try_launch_chrome_debug", return_value=False) as mock_launch, \
             patch("tools.browser_tool._resolve_cdp_override") as mock_resolve:
            result = ensure_local_chromium_cdp()

        assert result is None
        mock_launch.assert_called_once()
        mock_resolve.assert_not_called()

    def test_returns_none_when_launch_succeeds_but_port_never_ready(self):
        with patch.object(browser_connect, "is_browser_debug_ready", return_value=False), \
             patch.object(browser_connect, "try_launch_chrome_debug", return_value=True), \
             patch.object(browser_connect.time, "sleep"), \
             patch("tools.browser_tool._resolve_cdp_override") as mock_resolve:
            result = ensure_local_chromium_cdp(wait_seconds=0.0)

        assert result is None
        mock_resolve.assert_not_called()

    def test_falls_back_to_base_url_when_resolver_returns_empty(self):
        with patch.object(browser_connect, "is_browser_debug_ready", return_value=True), \
             patch("tools.browser_tool._resolve_cdp_override", return_value=""):
            result = ensure_local_chromium_cdp()

        assert result == DEFAULT_BASE_URL

    def test_falls_back_to_base_url_when_resolver_raises(self):
        with patch.object(browser_connect, "is_browser_debug_ready", return_value=True), \
             patch("tools.browser_tool._resolve_cdp_override", side_effect=RuntimeError("boom")):
            result = ensure_local_chromium_cdp()

        assert result == DEFAULT_BASE_URL

    def test_passes_custom_port_executable_and_user_data_dir_to_launcher(self):
        custom_port = 9333
        custom_exec = "/opt/Chromium/chromium"
        custom_data_dir = "/tmp/hermes-chrome"
        custom_base_url = f"http://127.0.0.1:{custom_port}"

        with patch.object(browser_connect, "is_browser_debug_ready", return_value=False), \
             patch.object(browser_connect, "try_launch_chrome_debug", return_value=True) as mock_launch, \
             patch.object(browser_connect.time, "sleep"), \
             patch("tools.browser_tool._resolve_cdp_override", return_value=custom_base_url) as mock_resolve:
            readiness_calls = iter([False, True])
            mock_launch.side_effect = lambda **_: True

            with patch.object(
                browser_connect,
                "is_browser_debug_ready",
                side_effect=lambda _url, timeout=1.0: next(readiness_calls),
            ):
                result = ensure_local_chromium_cdp(
                    port=custom_port,
                    executable_path=custom_exec,
                    user_data_dir=custom_data_dir,
                    wait_seconds=2.0,
                )

        assert result == custom_base_url
        mock_launch.assert_called_once_with(
            port=custom_port,
            executable_path=custom_exec,
            user_data_dir=custom_data_dir,
        )
        mock_resolve.assert_called_once_with(custom_base_url)

    def test_does_not_launch_when_already_ready_with_custom_port(self):
        custom_port = 9444
        custom_base_url = f"http://127.0.0.1:{custom_port}"

        with patch.object(browser_connect, "is_browser_debug_ready", return_value=True) as mock_ready, \
             patch.object(browser_connect, "try_launch_chrome_debug") as mock_launch, \
             patch("tools.browser_tool._resolve_cdp_override", return_value=custom_base_url) as mock_resolve:
            result = ensure_local_chromium_cdp(port=custom_port)

        assert result == custom_base_url
        mock_ready.assert_called_once_with(custom_base_url)
        mock_launch.assert_not_called()
        mock_resolve.assert_called_once_with(custom_base_url)

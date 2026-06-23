"""Shared helpers for attaching Hermes to a local Chromium-family CDP port."""

from __future__ import annotations

import logging
import os
import platform
import shlex
import shutil
import subprocess
import time
from typing import Optional

from hermes_constants import get_hermes_home


logger = logging.getLogger(__name__)


DEFAULT_BROWSER_CDP_PORT = 9226
DEFAULT_BROWSER_CDP_URL = f"http://127.0.0.1:{DEFAULT_BROWSER_CDP_PORT}"

_DARWIN_APPS = (
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

_WINDOWS_BROWSER_GROUPS = (
    (("chrome.exe", "chrome"), (("Google", "Chrome", "Application", "chrome.exe"),)),
    (
        ("chromium.exe", "chromium"),
        (("Chromium", "Application", "chrome.exe"), ("Chromium", "Application", "chromium.exe")),
    ),
    (("brave.exe", "brave"), (("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),)),
    (("msedge.exe", "msedge"), (("Microsoft", "Edge", "Application", "msedge.exe"),)),
)

_WINDOWS_BIN_NAMES = tuple(name for names, _ in _WINDOWS_BROWSER_GROUPS for name in names)
_WINDOWS_INSTALL_PARTS = tuple(parts for _, group in _WINDOWS_BROWSER_GROUPS for parts in group)

_LINUX_BROWSER_GROUPS = (
    (
        ("google-chrome", "google-chrome-stable"),
        ("/opt/google/chrome/chrome", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"),
    ),
    (
        ("chromium-browser", "chromium"),
        ("/usr/bin/chromium-browser", "/usr/bin/chromium"),
    ),
    (
        ("brave-browser", "brave-browser-stable", "brave"),
        (
            "/usr/bin/brave-browser",
            "/usr/bin/brave-browser-stable",
            "/usr/bin/brave",
            "/snap/bin/brave",
            "/opt/brave.com/brave/brave-browser",
            "/opt/brave.com/brave/brave",
            "/opt/brave-bin/brave",
        ),
    ),
    (
        ("microsoft-edge", "microsoft-edge-stable", "msedge"),
        (
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
            "/opt/microsoft/msedge/microsoft-edge",
            "/opt/microsoft/msedge/msedge",
        ),
    ),
)

_LINUX_BIN_NAMES = tuple(name for names, _ in _LINUX_BROWSER_GROUPS for name in names)
_LINUX_INSTALL_PATHS = tuple(path for _, paths in _LINUX_BROWSER_GROUPS for path in paths)


def get_chrome_debug_candidates(system: str, executable_path: Optional[str] = None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(path: str | None) -> None:
        if not path:
            return
        normalized = os.path.normcase(os.path.normpath(path))
        if normalized in seen or not os.path.isfile(path):
            return
        candidates.append(path)
        seen.add(normalized)

    def add_windows_install_paths(
        bases: tuple[str | None, ...],
        install_groups: tuple[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], ...],
    ) -> None:
        for _, group in install_groups:
            for base in filter(None, bases):
                for parts in group:
                    add(os.path.join(base, *parts))

    if executable_path:
        add(executable_path)

    if system == "Darwin":
        for app in _DARWIN_APPS:
            add(app)
        return candidates

    if system == "Windows":
        install_bases = (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LOCALAPPDATA"),
        )
        for names, install_parts in _WINDOWS_BROWSER_GROUPS:
            for name in names:
                add(shutil.which(name))
            for base in filter(None, install_bases):
                for parts in install_parts:
                    add(os.path.join(base, *parts))
        return candidates

    for names, paths in _LINUX_BROWSER_GROUPS:
        for name in names:
            add(shutil.which(name))
        for path in paths:
            add(path)
    add_windows_install_paths(("/mnt/c/Program Files", "/mnt/c/Program Files (x86)"), _WINDOWS_BROWSER_GROUPS)
    return candidates


def chrome_debug_data_dir(user_data_dir: Optional[str] = None) -> str:
    if user_data_dir:
        return os.path.expanduser(user_data_dir)
    return str(get_hermes_home() / "chrome-debug")


def _chrome_debug_args(port: int, user_data_dir: Optional[str] = None) -> list[str]:
    return [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={chrome_debug_data_dir(user_data_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def is_browser_debug_ready(url: str, timeout: float = 1.0) -> bool:
    """Return True when ``url`` exposes a reachable Chrome DevTools endpoint."""
    import socket
    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(url if "://" in url else f"http://{url}")
    try:
        port = parsed.port or (443 if parsed.scheme in {"https", "wss"} else 80)
    except ValueError:
        return False

    if parsed.scheme in {"ws", "wss"} and parsed.path.startswith("/devtools/browser/"):
        if not parsed.hostname:
            return False
        try:
            with socket.create_connection((parsed.hostname, port), timeout=timeout):
                return True
        except OSError:
            return False

    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
    if scheme not in {"http", "https"} or not parsed.netloc:
        return False

    root = f"{scheme}://{parsed.netloc}".rstrip("/")
    for probe in (f"{root}/json/version", f"{root}/json"):
        try:
            with urllib.request.urlopen(probe, timeout=timeout) as resp:
                if 200 <= getattr(resp, "status", 200) < 300:
                    return True
        except Exception:
            continue
    return False


def manual_chrome_debug_command(
    port: int = DEFAULT_BROWSER_CDP_PORT,
    system: str | None = None,
    executable_path: Optional[str] = None,
    user_data_dir: Optional[str] = None,
) -> str | None:
    system = system or platform.system()
    candidates = get_chrome_debug_candidates(system, executable_path=executable_path)

    if candidates:
        argv = [candidates[0], *_chrome_debug_args(port, user_data_dir=user_data_dir)]
        return subprocess.list2cmdline(argv) if system == "Windows" else shlex.join(argv)

    if system == "Darwin":
        data_dir = chrome_debug_data_dir(user_data_dir)
        return (
            f'open -a "Google Chrome" --args --remote-debugging-port={port} '
            f'--user-data-dir="{data_dir}" --no-first-run --no-default-browser-check'
        )

    return None


def _detach_kwargs(system: str) -> dict:
    if system != "Windows":
        return {"start_new_session": True}
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    return {"creationflags": flags} if flags else {}


def try_launch_chrome_debug(
    port: int = DEFAULT_BROWSER_CDP_PORT,
    system: str | None = None,
    executable_path: Optional[str] = None,
    user_data_dir: Optional[str] = None,
) -> bool:
    system = system or platform.system()
    candidates = get_chrome_debug_candidates(system, executable_path=executable_path)
    if not candidates:
        return False

    os.makedirs(chrome_debug_data_dir(user_data_dir), exist_ok=True)
    for candidate in candidates:
        try:
            subprocess.Popen(
                [candidate, *_chrome_debug_args(port, user_data_dir=user_data_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_detach_kwargs(system),
            )
            return True
        except Exception:
            continue
    return False


def ensure_local_chromium_cdp(
    port: Optional[int] = None,
    executable_path: Optional[str] = None,
    user_data_dir: Optional[str] = None,
    wait_seconds: float = 5.0,
) -> Optional[str]:
    """Ensure a local Chromium-family browser is listening on a CDP port.

    Returns the resolved CDP WebSocket URL (e.g. ``ws://127.0.0.1:9226/devtools/browser/<id>``)
    when ready, or ``None`` if no browser binary was available or the CDP
    endpoint never came up within ``wait_seconds``.
    """
    resolved_port = port or DEFAULT_BROWSER_CDP_PORT
    base_url = f"http://127.0.0.1:{resolved_port}"

    if not is_browser_debug_ready(base_url):
        if not try_launch_chrome_debug(
            port=resolved_port,
            executable_path=executable_path,
            user_data_dir=user_data_dir,
        ):
            logger.debug("ensure_local_chromium_cdp: no Chromium-family binary discovered")
            return None

        deadline = time.monotonic() + max(wait_seconds, 0.0)
        while time.monotonic() < deadline:
            if is_browser_debug_ready(base_url):
                break
            time.sleep(0.2)
        else:
            logger.debug(
                "ensure_local_chromium_cdp: CDP endpoint %s did not become ready within %.1fs",
                base_url,
                wait_seconds,
            )
            return None

    try:
        from tools.browser_tool import _resolve_cdp_override  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("ensure_local_chromium_cdp: cannot import _resolve_cdp_override: %s", exc)
        return base_url

    try:
        return _resolve_cdp_override(base_url) or base_url
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("ensure_local_chromium_cdp: _resolve_cdp_override failed: %s", exc)
        return base_url

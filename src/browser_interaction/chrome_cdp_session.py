"""Core Chrome DevTools Protocol (CDP) session.

Connects to a Chrome that was launched with --remote-debugging-port and lets you
drive a single tab over a websocket. Everything else in this package builds on
ChromeCDPSession.

Chrome must be started with the port. Note: Chrome 136+ refuses the debugging
port on the *default* profile, so launch on a copied/non-default --user-data-dir.
"""
from __future__ import annotations

import json
import time
import urllib.request

import websocket  # websocket-client

DEFAULT_PORT = 9222


def list_targets(port: int = DEFAULT_PORT) -> list[dict]:
    """Return all open targets (tabs/pages) reported by Chrome."""
    with urllib.request.urlopen(f"http://localhost:{port}/json", timeout=5) as r:
        return json.load(r)


def find_target_by_url(url_substring: str, port: int = DEFAULT_PORT) -> dict:
    """Return the first page target whose URL contains url_substring."""
    for t in list_targets(port):
        if t.get("type") == "page" and url_substring in t.get("url", ""):
            return t
    raise LookupError(f"No tab with URL containing {url_substring!r}")


class ChromeCDPSession:
    """A websocket session attached to one Chrome tab.

    Use as a context manager:
        with ChromeCDPSession.for_url("drive.google.com") as tab:
            tab.call("Page.enable")
    """

    def __init__(self, websocket_debugger_url: str):
        self._url = websocket_debugger_url
        self._ws = websocket.create_connection(websocket_debugger_url, timeout=30)
        self._next_id = 0
        self._event_buffer: list[dict] = []  # events seen while awaiting a call result

    @classmethod
    def for_url(cls, url_substring: str, port: int = DEFAULT_PORT) -> "ChromeCDPSession":
        target = find_target_by_url(url_substring, port)
        return cls(target["webSocketDebuggerUrl"])

    @classmethod
    def for_new_tab(cls, url: str, port: int = DEFAULT_PORT) -> "ChromeCDPSession":
        """Open a brand new tab at url and attach to it."""
        req = urllib.request.Request(
            f"http://localhost:{port}/json/new?{urllib.parse.quote(url, safe='')}",
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                target = json.load(r)
        except Exception:
            # Older/newer Chrome may want GET
            with urllib.request.urlopen(
                f"http://localhost:{port}/json/new?{url}", timeout=10
            ) as r:
                target = json.load(r)
        return cls(target["webSocketDebuggerUrl"])

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        """Send a CDP command and return its result, ignoring interleaved events."""
        self._next_id += 1
        msg_id = self._next_id
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._ws.settimeout(max(0.1, deadline - time.time()))
            data = json.loads(self._ws.recv())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method} failed: {data['error']}")
                return data.get("result", {})
            if "method" in data:  # an event arrived while awaiting our result -- keep it
                self._event_buffer.append(data)
        raise TimeoutError(f"{method} timed out")

    def wait_for_event(self, method: str, timeout: float = 15.0) -> dict:
        """Block until a CDP event of the given method arrives; return its params.

        Checks events already buffered (e.g. ones that arrived during a prior call)
        before reading new ones, so fast events are never missed.
        """
        for i, data in enumerate(self._event_buffer):
            if data.get("method") == method:
                return self._event_buffer.pop(i).get("params", {})
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._ws.settimeout(max(0.1, deadline - time.time()))
            try:
                data = json.loads(self._ws.recv())
            except websocket.WebSocketTimeoutException:
                break
            if data.get("method") == method:
                return data.get("params", {})
            if "method" in data:
                self._event_buffer.append(data)
        raise TimeoutError(f"event {method} not seen within {timeout}s")

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass

    def __enter__(self) -> "ChromeCDPSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


import urllib.parse  # noqa: E402  (used in for_new_tab)

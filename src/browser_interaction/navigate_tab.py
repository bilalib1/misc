"""Open URLs in the CDP-controlled Chrome and wait for load."""
from __future__ import annotations

from chrome_cdp_session import ChromeCDPSession, find_target_by_url


def open_url_in_new_tab(url: str, port: int = 9222) -> None:
    """Open url in a fresh tab and wait for the load event."""
    tab = ChromeCDPSession.for_new_tab(url, port)
    try:
        tab.call("Page.enable")
        try:
            tab.wait_for_event("Page.loadEventFired", timeout=20)
        except TimeoutError:
            pass
    finally:
        tab.close()


def navigate_existing_tab(url_substring: str, new_url: str, port: int = 9222) -> None:
    """Point the tab matching url_substring at new_url and wait for load."""
    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        tab.call("Page.enable")
        tab.call("Page.navigate", {"url": new_url})
        try:
            tab.wait_for_event("Page.loadEventFired", timeout=20)
        except TimeoutError:
            pass


if __name__ == "__main__":
    import sys

    open_url_in_new_tab(sys.argv[1])

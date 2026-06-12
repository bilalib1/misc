"""List the open Chrome tabs as compact text (title + url)."""
from __future__ import annotations

from chrome_cdp_session import list_targets


def list_open_tabs(port: int = 9222) -> list[dict]:
    """Return [{title, url, id}] for every open page tab."""
    return [
        {"title": t.get("title", ""), "url": t.get("url", ""), "id": t.get("id", "")}
        for t in list_targets(port)
        if t.get("type") == "page"
    ]


if __name__ == "__main__":
    for t in list_open_tabs():
        print(f"{t['title'][:60]:60s} | {t['url']}")

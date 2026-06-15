"""Upload local files by simulating a file drag-and-drop -- works fully headless.

Unlike upload_files_via_file_chooser (which needs the app's "upload" menu to open,
and Google's menus only render in a *composited/visible* window), this injects the
files straight into a synthetic drag via CDP Input.dispatchDragEvent. No menu, no
native dialog, no visible window -- so it's the upload path to use in headless or
headed-hidden mode (e.g. Google Drive, which accepts file drops onto the folder).

Pass all files in one call: a single drop uploads them together and avoids the
"file already exists / keep both" conflict you get from repeated drops.
"""
from __future__ import annotations

import os

from chrome_cdp_session import ChromeCDPSession, find_target_by_url

# Center of the drop zone (a CSS selector, or the main content region by default).
_DROP_POINT_JS = """
(function(){
  var el = %s || document.querySelector('[role=main]') || document.body;
  var r = el.getBoundingClientRect();
  return [Math.round(r.left + r.width/2), Math.round(r.top + r.height*0.5)];
})()
"""


def upload_files_via_drag_drop(
    url_substring: str,
    file_paths: list[str],
    drop_css_selector: str | None = None,
    port: int = 9222,
) -> dict:
    """Drop file_paths onto the tab matching url_substring (headless-safe)."""
    abs_paths = [os.path.abspath(p) for p in file_paths]
    for p in abs_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(p)

    import json
    sel = "document.querySelector(%s)" % json.dumps(drop_css_selector) if drop_css_selector else "null"

    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        tab.call("Page.enable")
        x, y = tab.call("Runtime.evaluate",
                        {"expression": _DROP_POINT_JS % sel, "returnByValue": True}
                        )["result"]["value"]
        data = {
            "items": [{"mimeType": "application/octet-stream", "data": "",
                       "title": os.path.basename(p)} for p in abs_paths],
            "files": abs_paths,
            "dragOperationsMask": 1,  # copy
        }
        for event_type in ("dragEnter", "dragOver", "drop"):
            tab.call("Input.dispatchDragEvent",
                     {"type": event_type, "x": x, "y": y, "data": data})
        return {"dropped": abs_paths, "at": [x, y]}


if __name__ == "__main__":
    import sys

    print(upload_files_via_drag_drop(sys.argv[1], sys.argv[2:]))

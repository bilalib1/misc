"""Upload local files through a web app's file picker -- no native dialog.

Uses CDP's file-chooser interception: enable interception, trigger the page's
"upload" control with real (trusted) mouse clicks, catch the
Page.fileChooserOpened event, and hand the files to the input via
DOM.setFileInputFiles. Chrome never shows a dialog and never needs window focus.
"""
from __future__ import annotations

import json
import os
import time

from chrome_cdp_session import ChromeCDPSession, find_target_by_url

# Return {x,y} center of the first visible element matching a label, or null.
# Matches by exact aria-label, then by visible text starting with the label
# (menu items often append a shortcut hint, e.g. "File upload  C then U").
_LOCATE_JS = """
(function(){
  var want = %s;
  function center(e){var r=e.getBoundingClientRect();
    return (r.width>0&&r.height>0)?{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}:null;}
  var byAria = document.querySelector('[aria-label="'+want+'"]');
  if(byAria){var c=center(byAria); if(c) return c;}
  var els = document.querySelectorAll('[role=menuitem],[role=button],button,div,span');
  for(var i=0;i<els.length;i++){
    var t=(els[i].textContent||'').trim();
    if(t.indexOf(want)===0){var c=center(els[i]); if(c) return c;}
  }
  return null;
})()
"""


def _locate(tab, label: str):
    r = tab.call("Runtime.evaluate",
                 {"expression": _LOCATE_JS % json.dumps(label), "returnByValue": True})
    return r.get("result", {}).get("value")


def _real_click(tab, x: int, y: int) -> None:
    for typ in ("mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent",
                 {"type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})


def upload_files_via_file_chooser(
    url_substring: str,
    file_paths: list[str],
    trigger_labels: list[str],
    port: int = 9222,
    settle_seconds: float = 1.2,
) -> dict:
    """Upload file_paths into the tab matching url_substring.

    trigger_labels is the sequence of button/menu labels to click that ends in the
    upload control, e.g. ["New", "File upload"] for Google Drive. Clicks are real
    trusted gestures, so the file chooser actually opens (and is intercepted).
    """
    abs_paths = [os.path.abspath(p) for p in file_paths]
    for p in abs_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(p)

    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        tab.call("Page.enable")
        tab.call("DOM.enable")
        tab.call("Page.setInterceptFileChooserDialog", {"enabled": True})

        # Reset any menu left open so the first click doesn't toggle it shut.
        for phase in ("keyDown", "keyUp"):
            tab.call("Input.dispatchKeyEvent",
                     {"type": phase, "key": "Escape", "windowsVirtualKeyCode": 27})
        time.sleep(0.3)

        for label in trigger_labels:
            spot = _locate(tab, label)
            if not spot:
                raise RuntimeError(f"could not locate trigger {label!r}")
            _real_click(tab, spot["x"], spot["y"])
            time.sleep(settle_seconds)

        event = tab.wait_for_event("Page.fileChooserOpened", timeout=15)
        tab.call("DOM.setFileInputFiles",
                 {"files": abs_paths, "backendNodeId": event["backendNodeId"]})
        return {"uploaded": abs_paths, "backendNodeId": event["backendNodeId"]}


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    sep = args.index("--")
    url_sub, files, labels = args[0], args[1:sep], args[sep + 1:]
    print(upload_files_via_file_chooser(url_sub, files, labels))

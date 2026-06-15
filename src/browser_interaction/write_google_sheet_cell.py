"""Write a value into a Google Sheets cell over CDP -- works headlessly.

The grid is a <canvas>, so we anchor on the Name Box (a real DOM input): focus it,
type the target cell ref + Enter to select that cell, then type the value + Enter.
All input is dispatched as real CDP key events, so no window focus is needed.
"""
from __future__ import annotations

import time

from chrome_cdp_session import ChromeCDPSession, find_target_by_url

_VK = {
    "/": 191, ".": 190, ",": 188, " ": 32, "(": 57, ")": 48, "-": 189, ":": 186,
}


def _type_text(tab, text: str) -> None:
    for ch in text:
        code = _VK.get(ch, ord(ch.upper()) if ch.isalnum() else 0)
        tab.call("Input.dispatchKeyEvent",
                 {"type": "keyDown", "text": ch, "key": ch, "windowsVirtualKeyCode": code})
        tab.call("Input.dispatchKeyEvent",
                 {"type": "keyUp", "key": ch, "windowsVirtualKeyCode": code})


def _press_enter(tab) -> None:
    for phase in ("keyDown", "keyUp"):
        tab.call("Input.dispatchKeyEvent",
                 {"type": phase, "key": "Enter", "code": "Enter",
                  "windowsVirtualKeyCode": 13, "text": "\r" if phase == "keyDown" else ""})


def write_google_sheet_cell(url_substring: str, cell_ref: str, value: str,
                            port: int = 9222, settle: float = 0.35) -> None:
    """Select cell_ref via the Name Box and type value into it."""
    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        tab.call("Runtime.evaluate", {"expression":
            "var n=document.querySelector('#t-name-box'); n.focus(); n.select();"})
        time.sleep(settle)
        _type_text(tab, cell_ref)
        _press_enter(tab)              # selects the cell
        time.sleep(settle)
        _type_text(tab, value)
        _press_enter(tab)              # commits the value
        time.sleep(settle)


if __name__ == "__main__":
    import sys

    write_google_sheet_cell(sys.argv[1], sys.argv[2], sys.argv[3])

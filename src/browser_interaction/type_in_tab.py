"""Type text into a tab: into the focused element, or into a CSS-selected field.

For canvas apps (e.g. Google Sheets) where the grid isn't real DOM, focus the
on-page input first (a cell, a Name Box) then call type_text_into_focused.
"""
from __future__ import annotations

import json
import time

from chrome_cdp_session import ChromeCDPSession, find_target_by_url


def type_text_into_focused(url_substring: str, text: str, press_enter: bool = False,
                           port: int = 9222) -> None:
    """Send text as real key events to whatever is focused in the tab."""
    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        for ch in text:
            tab.call("Input.dispatchKeyEvent", {"type": "char", "text": ch})
        if press_enter:
            for phase in ("keyDown", "keyUp"):
                tab.call("Input.dispatchKeyEvent",
                         {"type": phase, "key": "Enter", "windowsVirtualKeyCode": 13})


def set_value_by_css(url_substring: str, css_selector: str, value: str,
                     port: int = 9222) -> bool:
    """Set an <input>/<textarea> value directly and fire input/change events.

    Good for plain DOM forms; not for canvas grids.
    """
    js = """
    (function(){
      var e=document.querySelector(%s);
      if(!e) return false;
      var setter=Object.getOwnPropertyDescriptor(e.__proto__,'value').set;
      setter.call(e, %s);
      e.dispatchEvent(new Event('input',{bubbles:true}));
      e.dispatchEvent(new Event('change',{bubbles:true}));
      return true;
    })()
    """ % (json.dumps(css_selector), json.dumps(value))
    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        return tab.call("Runtime.evaluate", {"expression": js, "returnByValue": True}
                        ).get("result", {}).get("value", False)


if __name__ == "__main__":
    import sys

    type_text_into_focused(sys.argv[1], sys.argv[2], press_enter="--enter" in sys.argv)

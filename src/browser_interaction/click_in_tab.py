"""Click things in a tab with real, trusted mouse events (no window focus needed).

Google apps ignore element.click(); they listen for real pointer events. These
helpers locate an element, then dispatch CDP mouse events at its center.
"""
from __future__ import annotations

import json

from chrome_cdp_session import ChromeCDPSession, find_target_by_url

_CENTER_BY_CSS = """
(function(){
  var e=document.querySelector(%s);
  if(!e) return null;
  var r=e.getBoundingClientRect();
  return (r.width>0&&r.height>0)?{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}:null;
})()
"""

_CENTER_BY_TEXT = """
(function(){
  var want=%s;
  var els=document.querySelectorAll('[role=menuitem],[role=button],button,a,div,span');
  for(var i=0;i<els.length;i++){
    var t=(els[i].textContent||'').trim();
    if(t===want || t.indexOf(want)===0){
      var r=els[i].getBoundingClientRect();
      if(r.width>0&&r.height>0) return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};
    }
  }
  return null;
})()
"""


def _click_at(tab, x: int, y: int) -> None:
    for typ in ("mousePressed", "mouseReleased"):
        tab.call("Input.dispatchMouseEvent",
                 {"type": typ, "x": x, "y": y, "button": "left", "clickCount": 1})


def _click(url_substring: str, locate_js: str, port: int) -> bool:
    target = find_target_by_url(url_substring, port)
    with ChromeCDPSession(target["webSocketDebuggerUrl"]) as tab:
        spot = tab.call("Runtime.evaluate",
                        {"expression": locate_js, "returnByValue": True}
                        ).get("result", {}).get("value")
        if not spot:
            return False
        _click_at(tab, spot["x"], spot["y"])
        return True


def click_element_by_css(url_substring: str, css_selector: str, port: int = 9222) -> bool:
    """Click the first element matching css_selector. Returns False if not found."""
    return _click(url_substring, _CENTER_BY_CSS % json.dumps(css_selector), port)


def click_element_by_text(url_substring: str, text: str, port: int = 9222) -> bool:
    """Click the first visible element whose text equals/begins with text."""
    return _click(url_substring, _CENTER_BY_TEXT % json.dumps(text), port)


if __name__ == "__main__":
    import sys

    ok = click_element_by_text(sys.argv[1], sys.argv[2])
    print("clicked" if ok else "not found")

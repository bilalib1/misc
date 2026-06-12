"""Pull text out of a tab: whole-page text, or one element's text/html.

Lightweight alternative to screenshots -- returns the page as plain text so the
caller can reason about it without pixels.
"""
from __future__ import annotations

from run_javascript_in_tab import run_javascript_in_tab

_VISIBLE_TEXT_JS = """
(function(){
  var main = document.querySelector('[role=main]') || document.body;
  return (main.innerText || '').slice(0, %d);
})()
"""

_ELEMENT_TEXT_JS = """
(function(){
  var el = document.querySelector(%s);
  return el ? (el.innerText || el.textContent || '') : null;
})()
"""


def get_page_text(url_substring: str, max_chars: int = 6000, port: int = 9222) -> str:
    """Return the main-region (or body) visible text of the tab."""
    return run_javascript_in_tab(url_substring, _VISIBLE_TEXT_JS % max_chars, port)


def get_element_text(url_substring: str, css_selector: str, port: int = 9222):
    """Return innerText of the first element matching css_selector (or None)."""
    import json

    return run_javascript_in_tab(
        url_substring, _ELEMENT_TEXT_JS % json.dumps(css_selector), port
    )


if __name__ == "__main__":
    import sys

    print(get_page_text(sys.argv[1]))

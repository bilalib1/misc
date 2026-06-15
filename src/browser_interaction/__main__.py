"""One dispatcher so every helper is a single tool call:

    python3 -m browser_interaction <verb> [args...]

Verbs:
    tabs                                 list open tabs
    text   <url_substr> [max]            page main-region text
    eval   <url_substr> <js>             run JS, print result
    open   <url>                         open url in a new background tab
    goto   <url_substr> <new_url>        point an existing tab at new_url
    click  <url_substr> <text>           click element by visible text
    clickcss <url_substr> <css>          click element by CSS selector
    type   <url_substr> <text> [--enter] type into the focused element
    ldjson <url>                         dump LD+JSON blocks from a page
    cars   <url>                         dump @type=Car/Vehicle LD+JSON records
    upload <url_substr> <file>...        drag-drop files onto a tab (headless-safe upload)
    setcell <url_substr> <cell> <value>  write one Google Sheets cell (e.g. B9 6/2/2026)

Run from this directory (helpers import each other by bare module name), e.g.:
    cd ~/code/misc/src/browser_interaction && python3 -m browser_interaction tabs
"""
from __future__ import annotations

import json
import os
import sys

# Helpers import each other by bare module name (they're meant to be run from
# inside this dir). Put this dir on sys.path so `python3 -m browser_interaction`
# works from anywhere (e.g. the package parent).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _print(v):
    print(v if isinstance(v, str) else json.dumps(v, indent=2))


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    verb, rest = argv[0], argv[1:]

    if verb == "tabs":
        from list_open_tabs import list_open_tabs
        for t in list_open_tabs():
            print(f"{t['title'][:60]:60s} | {t['url']}")
    elif verb == "text":
        from get_page_text import get_page_text
        _print(get_page_text(rest[0], int(rest[1]) if len(rest) > 1 else 6000))
    elif verb == "eval":
        from run_javascript_in_tab import run_javascript_in_tab
        _print(run_javascript_in_tab(rest[0], rest[1]))
    elif verb == "open":
        from navigate_tab import open_url_in_new_tab
        open_url_in_new_tab(rest[0]); print("opened")
    elif verb == "goto":
        from navigate_tab import navigate_existing_tab
        navigate_existing_tab(rest[0], rest[1]); print("navigated")
    elif verb == "click":
        from click_in_tab import click_element_by_text
        print("clicked" if click_element_by_text(rest[0], rest[1]) else "not found")
    elif verb == "clickcss":
        from click_in_tab import click_element_by_css
        print("clicked" if click_element_by_css(rest[0], rest[1]) else "not found")
    elif verb == "type":
        from type_in_tab import type_text_into_focused
        type_text_into_focused(rest[0], rest[1], press_enter="--enter" in rest); print("typed")
    elif verb == "ldjson":
        from read_ld_json import read_ld_json
        _print(read_ld_json(rest[0]))
    elif verb == "cars":
        from read_ld_json import read_cars
        _print(read_cars(rest[0]))
    elif verb == "upload":
        from upload_files_via_drag_drop import upload_files_via_drag_drop
        _print(upload_files_via_drag_drop(rest[0], rest[1:]))
    elif verb == "setcell":
        from write_google_sheet_cell import write_google_sheet_cell
        write_google_sheet_cell(rest[0], rest[1], rest[2]); print("wrote", rest[1])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

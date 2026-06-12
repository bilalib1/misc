"""Evaluate JavaScript inside a tab and get the result back as text.

This is the workhorse: most read/interact helpers are thin wrappers around it.
"""
from __future__ import annotations

import json

from chrome_cdp_session import ChromeCDPSession


def run_javascript_in_tab(url_substring: str, js_expression: str, port: int = 9222):
    """Run js_expression in the tab matching url_substring; return the JS value.

    The expression may be an async IIFE; promises are awaited.
    """
    with ChromeCDPSession.for_url(url_substring, port) as tab:
        result = tab.call(
            "Runtime.evaluate",
            {
                "expression": js_expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"].get("text", "JS exception"))
    return result.get("result", {}).get("value")


if __name__ == "__main__":
    import sys

    out = run_javascript_in_tab(sys.argv[1], sys.argv[2])
    print(out if isinstance(out, str) else json.dumps(out, indent=2))

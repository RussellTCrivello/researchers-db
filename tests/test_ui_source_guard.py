"""UI source guard — string builders are never treated as arrays.

A recurring hazard in the view layer: helpers that RETURN A COMPLETE HTML
STRING (like military.js `table(cols, rows, render)`) being chained with
``.join("")`` or ``.map(...)`` — which crashes at render time with
``TypeError: ....join is not a function`` (the milNaming view shipped exactly
this bug from its first commit).  This guard walks every non-vendor JS file,
detects local functions that return a template-literal string, and asserts no
call site calls ``.join``/``.map`` on their result.

Run:  pytest -q tests/test_ui_source_guard.py
"""
from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "app/static/js"

STRING_BUILDERS = re.compile(
    r"function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*return\s*`", re.S)


def _call_sites(src: str, name: str):
    """Yield (line, tail) for every ``name(`` call and what follows its ``)``."""
    for m in re.finditer(r"(?<![\w$.])" + re.escape(name) + r"\(", src):
        i, depth, in_str = m.end(), 1, None
        while i < len(src) and depth:
            ch = src[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
            elif ch in "\"'`":
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        line = src[: m.start()].count("\n") + 1
        yield line, src[i : i + 20].lstrip()


def test_no_string_builder_result_is_joined_or_mapped():
    offenders = []
    builders = {}
    for path in sorted(JS.rglob("*.js")):
        if "vendor" in path.parts or "lib" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        for m in STRING_BUILDERS.finditer(src):
            builders.setdefault(path, set()).add(m.group(1))
        for name in builders.get(path, ()):
            for line, tail in _call_sites(src, name):
                if tail.startswith(".join") or tail.startswith(".map"):
                    offenders.append(f"{path.name}:{line}  {name}(...){tail[:12]}")
    assert not offenders, f"string builder result used as an array: {offenders}"


def test_mil_naming_view_renders_tables_as_strings():
    src = (JS / "views/military.js").read_text(encoding="utf-8")
    assert "A.views.milNaming" in src
    # the naming tables are interpolated into the template, not joined
    block = src[src.index("A.views.milNaming"):]
    block = block[: block.find("A.views.", 10)] if "A.views." in block[10:] else block
    assert "${table(" in block
    for line, tail in _call_sites(src, "table"):
        assert not tail.startswith(".join"), f"table() joined at line {line}"

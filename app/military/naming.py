"""Military Organization — automatic naming series (design record §11.2, Appendix B).

Grammar of a series label::

    BODY[#+]

* BODY may contain the tokens ``.YYYY.`` (year partition) and ``.{field}.``
  (field-value partition), e.g. ``MIL-DEP-.YYYY.-``, ``MIL-ARM-.{category}.``.
* A token consumes its dots; a literal dot directly before the counter is a
  counter-slot marker and is dropped.  Every catalogued label therefore
  renders as a clean identifier:
  ``MIL-DEP-.YYYY.-``  → ``MIL-DEP-2026-00001``,
  ``MIL-ARM-.{category}.#####`` → ``MIL-ARM-WEAPONS00001``,
  ``MIL-TRN-.######`` → ``MIL-TRN-000001``.
* A trailing run of ``#`` sets the counter width (default 5, zero-padded).

Counters are keyed by (option, partition); year tokens and category segments
partition the sequence.  A preview is advisory and never reserves its value;
concurrent inserts may advance the counter first.  Counter adjustments are
restricted to administrators and are logged.
"""
from __future__ import annotations

import re
from typing import Any

from .dbm import now_iso

# entity -> list of (label, is_default) — Appendix B, 19 options
SERIES_CATALOG: list[tuple[str, str, bool]] = [
    ("region", "MIL-REG-", True),
    ("division", "MIL-DIV-", True),
    ("classification", "MIL-CLS-", True),
    ("commander", "MIL-CMD-", True),
    ("unit", "MIL-UNIT-", True),
    ("unit", "MIL-BRG-", False),
    ("deployment", "MIL-DEP-.YYYY.-", True),
    ("deployment", "MIL-DEP-", False),
    ("mission", "MIL-MIS-.YYYY.-", True),
    ("mission", "MIL-MIS-", False),
    ("armament", "MIL-ARM-", True),
    ("armament", "MIL-ARM-.{category}.#####", False),
    ("holding", "MIL-INV-", True),
    ("training", "MIL-TRN-.YYYY.-", True),
    ("training", "MIL-TRN-", False),
    ("training", "MIL-TRN-.######", False),
    ("assignment", "MIL-ASG-", True),
    ("assignment", "MIL-ASG-.YYYY.-", False),
    ("note", "MIL-NOTE-", True),
]

_TOKEN_RE = re.compile(r"\.(YYYY|\{(\w+)\})\.?")
_HASH_RE = re.compile(r"#+$")


class NamingError(ValueError):
    pass


def parse_label(label: str) -> dict[str, Any]:
    """Split a series label into literal/value tokens and counter width."""
    width = 5
    body = label
    m = _HASH_RE.search(label)
    if m:
        width = len(m.group(0))
        body = label[: m.start()]
    tokens: list[tuple[str, str | None]] = []
    pos = 0
    for tm in _TOKEN_RE.finditer(body):
        tokens.append(("lit", body[pos:tm.start()]))
        kind = "year" if tm.group(1) == "YYYY" else "field"
        tokens.append((kind, tm.group(2)))
        pos = tm.end()
    tokens.append(("lit", body[pos:]))
    # a literal dot directly before the counter is a slot marker: drop it
    if tokens and tokens[-1][0] == "lit" and (tokens[-1][1] or "").endswith("."):
        tokens[-1] = ("lit", tokens[-1][1][:-1])
    return {"label": label, "width": width, "tokens": tokens}


def seed_options(conn) -> None:
    """Insert the 19 catalogue options (idempotent)."""
    for entity, label, is_default in SERIES_CATALOG:
        spec = parse_label(label)
        year_token = 1 if any(t == "year" for t, _ in spec["tokens"]) else 0
        segment = next((v for t, v in spec["tokens"] if t == "field"), None)
        prefix = "".join(v for t, v in spec["tokens"] if t == "lit")
        conn.execute(
            """INSERT OR IGNORE INTO naming_series_option
               (entity, label, prefix, year_token, segment_field, width, is_default, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (entity, label, prefix, year_token, segment, spec["width"],
             1 if is_default else 0),
        )


def option_for(conn, entity: str, label: str | None = None) -> Any:
    if label:
        row = conn.execute(
            "SELECT * FROM naming_series_option WHERE entity = ? AND label = ?",
            (entity, label),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM naming_series_option WHERE entity = ? AND active = 1 "
            "ORDER BY is_default DESC, id LIMIT 1",
            (entity,),
        ).fetchone()
    if not row:
        raise NamingError(f"no naming series option for entity {entity!r}")
    return row


def _partition_and_body(opt, context: dict[str, Any]) -> tuple[str, str]:
    """Resolve the partition key and rendered format body (without counter)."""
    spec = parse_label(opt["label"])
    parts: list[str] = []
    rendered: list[str] = []
    for kind, value in spec["tokens"]:
        if kind == "lit":
            rendered.append(value or "")
        elif kind == "year":
            year = str(context.get("year") or now_iso()[:4])
            parts.append(year)
            rendered.append(year)
        elif kind == "field":
            raw = (context.get(value or "") or "").strip()
            if not raw:
                raise NamingError(
                    f"naming series {opt['label']!r} needs field {value!r}")
            seg = re.sub(r"[^A-Za-z0-9]+", "", raw).upper() or "NA"
            parts.append(seg)
            rendered.append(seg)
    return "|".join(parts), "".join(rendered)


def render(opt, context: dict[str, Any], value: int) -> str:
    _partition, body = _partition_and_body(opt, context)
    return f"{body}{value:0{opt['width']}d}"


def preview(conn, entity: str, context: dict[str, Any],
            label: str | None = None) -> dict[str, Any]:
    """Advisory next value — does NOT reserve (design record §11.2)."""
    seed_options(conn)
    opt = option_for(conn, entity, label)
    partition, _ = _partition_and_body(opt, context)
    row = conn.execute(
        "SELECT current_value FROM naming_counter WHERE option_id = ? AND partition = ?",
        (opt["id"], partition),
    ).fetchone()
    nxt = (row["current_value"] if row else 0) + 1
    return {
        "label": opt["label"],
        "partition": partition,
        "next": render(opt, context, nxt),
        "next_value": nxt,
        "reserved": False,
    }


def next_name(conn, entity: str, context: dict[str, Any],
              label: str | None = None) -> str:
    """Reserve the next name in the series.  Runs inside the caller's transaction."""
    seed_options(conn)
    opt = option_for(conn, entity, label)
    partition, _ = _partition_and_body(opt, context)
    conn.execute(
        """INSERT INTO naming_counter (option_id, partition, current_value) VALUES (?, ?, 0)
           ON CONFLICT(option_id, partition) DO NOTHING""",
        (opt["id"], partition),
    )
    conn.execute(
        "UPDATE naming_counter SET current_value = current_value + 1 "
        "WHERE option_id = ? AND partition = ?",
        (opt["id"], partition),
    )
    value = conn.execute(
        "SELECT current_value FROM naming_counter WHERE option_id = ? AND partition = ?",
        (opt["id"], partition),
    ).fetchone()["current_value"]
    return render(opt, context, value)


def adjust_counter(conn, option_id: int, partition: str, new_value: int,
                   actor: str) -> dict[str, Any]:
    """Controlled rebasing — restricted to administrators and always logged."""
    if new_value < 0:
        raise NamingError("counter value must be >= 0")
    opt = conn.execute(
        "SELECT * FROM naming_series_option WHERE id = ?", (option_id,)).fetchone()
    if not opt:
        raise NamingError(f"unknown naming option id {option_id}")
    partition = partition or ""
    conn.execute(
        """INSERT INTO naming_counter (option_id, partition, current_value) VALUES (?, ?, ?)
           ON CONFLICT(option_id, partition) DO UPDATE SET current_value = excluded.current_value""",
        (option_id, partition, new_value),
    )
    conn.execute(
        "INSERT INTO naming_adjustment_log (option_id, partition, old_value, new_value, actor, at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (option_id, partition, -1, new_value, actor, now_iso()),
    )
    return {"label": opt["label"], "partition": partition, "current_value": new_value}


def status(conn) -> list[dict[str, Any]]:
    """All options with their per-partition counters (admin naming view)."""
    seed_options(conn)
    rows = conn.execute(
        """SELECT o.*, COALESCE(c.partition, '') AS partition,
                  COALESCE(c.current_value, 0) AS current_value
           FROM naming_series_option o
           LEFT JOIN naming_counter c ON c.option_id = o.id
           ORDER BY o.entity, o.is_default DESC, o.label, c.partition"""
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        # reconstruct the render context from the partition key
        ctx: dict[str, Any] = {}
        segs = [s for s in (r["partition"] or "").split("|") if s]
        idx = 0
        if r["year_token"] and idx < len(segs):
            ctx["year"] = segs[idx]
            idx += 1
        if r["segment_field"] and idx < len(segs):
            ctx[r["segment_field"]] = segs[idx]
        opt = {"label": r["label"], "width": r["width"]}
        try:
            nxt = render(opt, ctx, r["current_value"] + 1)
        except NamingError:
            nxt = ""
        out.append({
            "id": r["id"], "entity": r["entity"], "label": r["label"],
            "width": r["width"], "is_default": bool(r["is_default"]),
            "active": bool(r["active"]),
            "partition": r["partition"], "current_value": r["current_value"],
            "next_preview": nxt,
        })
    return out

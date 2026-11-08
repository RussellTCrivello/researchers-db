"""Military Organization — business rule catalogue (design record §8).

Every invariant in one place, evaluated against the caller's transaction so
multi-record changes are decided on the state being committed.  Rules raise
:class:`RuleViolation`; the API maps it to a structured 422/409 response.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .vocab import (
    COMMANDER_TRANSITIONS,
    DEPLOYMENT_TRANSITIONS,
    HOLDING_CONDITIONS,
    MISSION_TRANSITIONS,
    NOTE_TARGET_TYPES,
)

# map entity slug -> table, for target-existence checks
_TABLES = {
    "region": "region", "division": "division", "classification": "classification",
    "commander": "commander", "unit": "military_unit",
    "deployment": "operational_deployment", "mission": "mission",
    "armament": "armament", "holding": "unit_armament", "training": "training",
    "assignment": "command_assignment", "note": "note",
}


class RuleViolation(Exception):
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def payload(self) -> dict[str, Any]:
        out = {"code": self.code, "message": self.message}
        if self.field:
            out["field"] = self.field
        return out


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RuleViolation("invalid_date", f"{field} must be ISO YYYY-MM-DD", field)


# --- date policy (§8.2) ----------------------------------------------------
def check_date_range(start: str | None, end: str | None,
                     start_field: str = "start_date", end_field: str = "end_date") -> None:
    s = _parse_date(start, start_field)
    e = _parse_date(end, end_field)
    if start and not s:
        raise RuleViolation("invalid_date", f"{start_field} must be ISO YYYY-MM-DD", start_field)
    if s and e and e < s:
        raise RuleViolation("date_order",
                            f"{end_field} cannot be earlier than {start_field}", end_field)


def days_between(start: str, end: str) -> int:
    s = _parse_date(start, "start_date")
    e = _parse_date(end, "end_date")
    assert s and e
    return (e - s).days + 1


# --- tree integrity (§8.1) -------------------------------------------------
def check_tree_parent(conn, table: str, node_id: int | None, parent_id: int | None,
                      label: str = "parent") -> None:
    if parent_id is None:
        return
    if node_id is not None and parent_id == node_id:
        raise RuleViolation("tree_self_parent", "a node cannot be its own parent", label)
    parent = conn.execute(f"SELECT id, path FROM {table} WHERE id = ?", (parent_id,)).fetchone()
    if not parent:
        raise RuleViolation("tree_missing_parent", f"parent {parent_id} does not exist", label)
    if node_id is not None:
        node = conn.execute(f"SELECT id, path FROM {table} WHERE id = ?", (node_id,)).fetchone()
        if node and node["path"] and parent["path"] and (
                parent["path"].startswith(node["path"])):
            raise RuleViolation("tree_cycle",
                                "the selected parent is inside this node's subtree", label)


def compute_path(conn, table: str, node_id: int, parent_id: int | None) -> tuple[str, int]:
    if parent_id is None:
        return f"/{node_id}/", 0
    parent = conn.execute(f"SELECT path, depth FROM {table} WHERE id = ?", (parent_id,)).fetchone()
    return parent["path"] + f"{node_id}/", parent["depth"] + 1


def subtree_ids(conn, table: str, node_id: int) -> list[int]:
    node = conn.execute(f"SELECT path FROM {table} WHERE id = ?", (node_id,)).fetchone()
    if not node:
        return []
    rows = conn.execute(f"SELECT id FROM {table} WHERE path LIKE ?",
                        (node["path"] + "%",)).fetchall()
    return [r["id"] for r in rows]


def descendant_personnel(conn, unit_id: int) -> int:
    """SUM of direct personnel over the unit's whole subtree (§8.1)."""
    node = conn.execute("SELECT path FROM military_unit WHERE id = ?", (unit_id,)).fetchone()
    if not node:
        return 0
    row = conn.execute(
        "SELECT COALESCE(SUM(direct_personnel), 0) AS total FROM military_unit "
        "WHERE path LIKE ?", (node["path"] + "%",)).fetchone()
    return int(row["total"])


# --- lifecycle transitions (§8.3) -----------------------------------------
def check_transition(table: dict[str, list[str]], entity: str,
                     old: str | None, new: str) -> None:
    if old is None or old == new:
        return
    allowed = table.get(old)
    if allowed is None:
        return  # state outside the governed set: set-valued status is owner-reviewable
    if new not in allowed:
        raise RuleViolation(
            "status_transition",
            f"{entity} status cannot move from {old!r} to {new!r} "
            f"(allowed: {allowed or 'none — terminal'})",
            "status",
        )


def check_deployment_transition(old: str | None, new: str) -> None:
    check_transition(DEPLOYMENT_TRANSITIONS, "deployment", old, new)


def check_mission_transition(old: str | None, new: str) -> None:
    check_transition(MISSION_TRANSITIONS, "mission", old, new)


def check_commander_transition(old: str | None, new: str) -> None:
    check_transition(COMMANDER_TRANSITIONS, "commander", old, new)


# --- deployment policy (§8.3) ---------------------------------------------
def check_deployment(conn, payload: dict[str, Any], exclude_id: int | None = None) -> None:
    check_date_range(payload.get("start_date"), payload.get("end_date"))
    status = payload.get("status") or "Planned"
    if status == "Completed" and not payload.get("end_date"):
        raise RuleViolation("completed_needs_end",
                            "a completed deployment needs an end date", "end_date")
    unit_id = payload.get("unit_id")
    if unit_id is not None:
        unit = conn.execute("SELECT id FROM military_unit WHERE id = ?", (unit_id,)).fetchone()
        if not unit:
            raise RuleViolation("unit_not_found", f"unit {unit_id} does not exist", "unit_id")
        if payload.get("is_current"):
            sql = ("SELECT id, docname FROM operational_deployment "
                   "WHERE unit_id = ? AND is_current = 1")
            args: list[Any] = [unit_id]
            if exclude_id is not None:
                sql += " AND id != ?"
                args.append(exclude_id)
            clash = conn.execute(sql, args).fetchone()
            if clash:
                raise RuleViolation(
                    "one_current_deployment",
                    f"unit already has a current deployment ({clash['docname']}); "
                    "clear it first",
                    "is_current",
                )


def check_mission(conn, payload: dict[str, Any]) -> None:
    check_date_range(payload.get("start_date"), payload.get("end_date"))
    status = payload.get("status") or "Planned"
    if status == "Executed" and not payload.get("end_date"):
        raise RuleViolation("executed_needs_end",
                            "an executed mission needs an end date", "end_date")
    unit_id = payload.get("unit_id")
    if unit_id is not None:
        if not conn.execute("SELECT id FROM military_unit WHERE id = ?", (unit_id,)).fetchone():
            raise RuleViolation("unit_not_found", f"unit {unit_id} does not exist", "unit_id")
    dep_id = payload.get("deployment_id")
    if dep_id is not None:
        dep = conn.execute(
            "SELECT d.id AS id, d.unit_id AS unit_id, u.path AS path, d.docname AS docname "
            "FROM operational_deployment d "
            "JOIN military_unit u ON u.id = d.unit_id WHERE d.id = ?",
            (dep_id,)).fetchone()
        if not dep:
            raise RuleViolation("deployment_not_found",
                                f"deployment {dep_id} does not exist", "deployment_id")
        if unit_id is not None and unit_id != dep["unit_id"]:
            unit = conn.execute("SELECT path FROM military_unit WHERE id = ?", (unit_id,)).fetchone()
            # consistent only when the deployment's unit is an ancestor of the
            # mission unit (a parent formation's deployment covers subordinate
            # missions) or the same unit
            if not (unit and unit["path"].startswith(dep["path"])):
                raise RuleViolation(
                    "mission_deployment_mismatch",
                    "the linked deployment's unit must be the mission's unit "
                    "or an ancestor of it",
                    "deployment_id",
                )


# --- command appointment policy (§8.4) ------------------------------------
def check_trait(payload: dict[str, Any], exclude_id: int | None = None) -> None:
    """A leadership assessment must carry its basis.

    Qualities set leaders apart, but they are judgments: one recorded without
    who assessed it, on what evidence, or from which source invites fabrication.
    At least one provenance element is required, and a judgment cannot be
    dated in the future.
    """
    basis = [payload.get("evidence_note"), payload.get("source"),
             payload.get("assessed_by")]
    if not any(b not in (None, "") for b in basis):
        raise RuleViolation(
            "basis_required",
            "an assessment needs its basis: evidence, source, or assessor",
            "evidence_note")
    at = payload.get("assessed_at")
    if at:
        parsed = _parse_date(at, "assessed_at")
        if parsed and parsed > date.today():
            raise RuleViolation(
                "future_assessment",
                "an assessment cannot be dated in the future",
                "assessed_at")


def check_assignment(conn, payload: dict[str, Any], exclude_id: int | None = None) -> None:
    check_date_range(payload.get("assigned_date"), payload.get("relieved_date"),
                     "assigned_date", "relieved_date")
    unit_id = payload.get("unit_id")
    commander_id = payload.get("commander_id")
    if unit_id is not None and not conn.execute(
            "SELECT id FROM military_unit WHERE id = ?", (unit_id,)).fetchone():
        raise RuleViolation("unit_not_found", f"unit {unit_id} does not exist", "unit_id")
    if commander_id is not None and not conn.execute(
            "SELECT id FROM commander WHERE id = ?", (commander_id,)).fetchone():
        raise RuleViolation("commander_not_found",
                            f"commander {commander_id} does not exist", "commander_id")
    if not payload.get("assigned_date"):
        raise RuleViolation("assigned_date_required",
                            "an appointment needs an assigned date", "assigned_date")
    role = payload.get("role") or "Commanding Officer"
    if unit_id is None:
        return
    # open-ended = ongoing
    new_start = payload["assigned_date"]
    new_end = payload.get("relieved_date") or None
    sql = ("SELECT id, docname, assigned_date, relieved_date FROM command_assignment "
           "WHERE unit_id = ? AND role = ?")
    args: list[Any] = [unit_id, role]
    if exclude_id is not None:
        sql += " AND id != ?"
        args.append(exclude_id)
    for row in conn.execute(sql, args):
        other_start = row["assigned_date"]
        other_end = row["relieved_date"] or None
        overlap = (other_end is None or other_end >= new_start) and (
            new_end is None or new_end >= other_start)
        if overlap:
            raise RuleViolation(
                "appointment_overlap",
                f"overlapping appointment for {role!r} on this unit "
                f"(conflict with {row['docname']}, {other_start}–{other_end or 'ongoing'})",
                "assigned_date",
            )


def check_commander_retire(conn, commander_id: int) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM command_assignment WHERE commander_id = ? AND is_current = 1",
        (commander_id,)).fetchone()
    if row["n"]:
        raise RuleViolation(
            "unresolved_appointment",
            "commander still holds a current appointment; relieve it before retiring",
            "status",
        )


# --- resource capacity policy (§8.5) --------------------------------------
def check_training(conn, payload: dict[str, Any]) -> None:
    check_date_range(payload.get("start_date"), payload.get("end_date"))
    if payload.get("start_date") and payload.get("end_date") and payload.get("duration_days"):
        want = days_between(payload["start_date"], payload["end_date"])
        if int(payload["duration_days"]) != want:
            raise RuleViolation(
                "duration_mismatch",
                f"duration_days must be {want} for the given date range",
                "duration_days",
            )
    unit_id = payload.get("unit_id")
    if unit_id is not None and not conn.execute(
            "SELECT id FROM military_unit WHERE id = ?", (unit_id,)).fetchone():
        raise RuleViolation("unit_not_found", f"unit {unit_id} does not exist", "unit_id")
    if unit_id is not None and payload.get("participant_count") is not None:
        cap = descendant_personnel(conn, unit_id)
        if int(payload["participant_count"]) > cap:
            raise RuleViolation(
                "participant_over_capacity",
                f"participant_count exceeds the unit's subtree personnel capacity ({cap})",
                "participant_count",
            )


def check_holding(payload: dict[str, Any]) -> None:
    qty = payload.get("quantity")
    if qty is not None and int(qty) <= 0:
        raise RuleViolation("quantity_positive", "quantity must be greater than 0", "quantity")
    condition = payload.get("condition")
    if condition is not None and condition not in HOLDING_CONDITIONS:
        raise RuleViolation("condition_choice",
                            f"condition must be one of {HOLDING_CONDITIONS}", "condition")


# --- note targets (§8.7) --------------------------------------------------
def check_note(conn, payload: dict[str, Any]) -> None:
    entity_type = payload.get("entity_type")
    target_id = payload.get("target_id")
    if entity_type not in NOTE_TARGET_TYPES:
        raise RuleViolation(
            "note_target_type",
            f"entity_type must be one of {NOTE_TARGET_TYPES}", "entity_type")
    if target_id is None:
        raise RuleViolation("note_target_missing", "target_id is required", "target_id")
    table = _TABLES[entity_type]
    if not conn.execute(f"SELECT id FROM {table} WHERE id = ?", (target_id,)).fetchone():
        raise RuleViolation(
            "note_target_missing",
            f"target {entity_type} #{target_id} does not exist", "target_id")


# --- deletion policy (§8.8) ----------------------------------------------
DELETE_DEPENDENCIES = {
    "region": [("division", "region_id"), ("military_unit", "region_id")],
    "division": [("military_unit", "division_id")],
    "classification": [("military_unit", "classification_id")],
    "commander": [("military_unit", "commander_id"),
                  ("command_assignment", "commander_id")],
    "unit": [("military_unit", "parent_id"),
             ("operational_deployment", "unit_id"), ("mission", "unit_id"),
             ("unit_armament", "unit_id"), ("training", "unit_id"),
             ("command_assignment", "unit_id")],
    "deployment": [("mission", "deployment_id")],
    "armament": [("unit_armament", "armament_id")],
}


def check_delete(conn, entity: str, record_id: int) -> None:
    """Deleting a record with dependents is blocked and counted (§8.8)."""
    for table, column in DELETE_DEPENDENCIES.get(entity, []):
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = ?", (record_id,)).fetchone()
        if row["n"]:
            raise RuleViolation(
                "delete_blocked",
                f"cannot delete: {row['n']} dependent record(s) in {table} reference it",
            )

"""Military Organization — transactional service layer.

One schema-driven CRUD engine for all twelve entities: field specs double as
API validation and as the UI form/list contract (``GET /api/military/meta``).
Every mutation runs in a single transaction with rules evaluated against the
in-flight state, synchronised pointer fields, and an append-only audit entry
(design record §12.3).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from . import naming, rules
from .dbm import connect, ensure, now_iso
from .rules import RuleViolation
from .vocab import (
    ARMAMENT_CATEGORIES,
    ASSIGNMENT_ROLES,
    CLASS_CATEGORIES,
    COMMANDER_STATUSES,
    DEPLOYMENT_STATUSES,
    DEPLOYMENT_TYPES,
    DIVISION_TYPES,
    HOLDING_CONDITIONS,
    MISSION_STATUSES,
    MISSION_TYPES,
    NOTE_TARGET_TYPES,
    READINESS_TIERS,
    REGION_TYPES,
    TRAINING_ASSESSMENTS,
    TRAINING_TYPES,
    UNIT_ECHELONS,
    UNIT_STATUSES,
)

# ---------------------------------------------------------------------------
# bilingual display labels — the registry convention (schemas.py): field specs
# carry label_en/label_ar; the interface picks by language.  Arabic labels for
# entity + field names live here so ENTITY_SPECS stays readable.
# ---------------------------------------------------------------------------
ENTITY_LABELS_AR = {
    "region": "منطقة", "division": "فرقة", "classification": "تصنيف",
    "commander": "قائد", "unit": "وحدة عسكرية", "deployment": "نشر عملياتي",
    "mission": "مهمة", "armament": "تسليح", "holding": "تسليح الوحدة",
    "training": "تدريب", "assignment": "تعيين قيادي", "note": "ملاحظة",
}

FIELD_LABELS_AR: dict[tuple[str, str], str] = {
    ("region", "name"): "اسم المنطقة", ("region", "region_type"): "نوع المنطقة",
    ("region", "parent_id"): "المنطقة الأم", ("region", "country"): "الدولة",
    ("region", "description"): "الوصف",
    ("division", "name"): "اسم الفرقة", ("division", "region_id"): "المنطقة",
    ("division", "division_type"): "نوع الفرقة", ("division", "formation_date"): "تاريخ التشكيل",
    ("division", "headquarters"): "مقر القيادة", ("division", "description"): "الوصف",
    ("classification", "name"): "اسم التصنيف", ("classification", "category"): "الفئة",
    ("classification", "readiness_tier"): "مستوى الجاهزية",
    ("classification", "description"): "الوصف",
    ("commander", "full_name"): "الاسم الكامل", ("commander", "rank_title"): "الرتبة",
    ("commander", "branch"): "الفرع", ("commander", "commission_date"): "تاريخ التكليف",
    ("commander", "status"): "الحالة", ("commander", "biography"): "السيرة",
    ("unit", "name"): "اسم الوحدة", ("unit", "code"): "الرمز التشغيلي",
    ("unit", "echelon"): "المستوى", ("unit", "parent_id"): "الوحدة الأم",
    ("unit", "classification_id"): "التصنيف", ("unit", "division_id"): "الفرقة",
    ("unit", "region_id"): "المنطقة", ("unit", "commander_id"): "القائد",
    ("unit", "role"): "الدور", ("unit", "status"): "الحالة",
    ("unit", "direct_personnel"): "القوة المباشرة",
    ("unit", "formation_date"): "تاريخ التشكيل", ("unit", "headquarters"): "مقر القيادة",
    ("unit", "notes"): "ملاحظات",
    ("deployment", "name"): "اسم النشر", ("deployment", "unit_id"): "الوحدة",
    ("deployment", "deployment_type"): "نوع النشر",
    ("deployment", "start_date"): "تاريخ البداية", ("deployment", "end_date"): "تاريخ النهاية",
    ("deployment", "status"): "الحالة", ("deployment", "is_current"): "النشر الحالي",
    ("deployment", "location"): "الموقع", ("deployment", "area_of_operations"): "منطقة العمليات",
    ("deployment", "notes"): "ملاحظات",
    ("mission", "name"): "اسم المهمة", ("mission", "unit_id"): "الوحدة",
    ("mission", "mission_type"): "نوع المهمة", ("mission", "deployment_id"): "النشر المرتبط",
    ("mission", "start_date"): "تاريخ البداية", ("mission", "end_date"): "تاريخ النهاية",
    ("mission", "status"): "الحالة", ("mission", "area"): "المنطقة",
    ("mission", "description"): "الوصف", ("mission", "notes"): "ملاحظات",
    ("armament", "name"): "اسم التسليح", ("armament", "category"): "الفئة",
    ("armament", "specification"): "المواصفات", ("armament", "origin_country"): "بلد المنشأ",
    ("armament", "description"): "الوصف",
    ("holding", "unit_id"): "الوحدة", ("holding", "armament_id"): "التسليح",
    ("holding", "quantity"): "الكمية", ("holding", "condition"): "الحالة الفنية",
    ("holding", "acquisition_year"): "سنة التوريد", ("holding", "notes"): "ملاحظات",
    ("training", "exercise_name"): "اسم التمرين", ("training", "unit_id"): "الوحدة",
    ("training", "training_type"): "نوع التدريب",
    ("training", "start_date"): "تاريخ البداية", ("training", "end_date"): "تاريخ النهاية",
    ("training", "duration_days"): "المدة (أيام)", ("training", "participant_count"): "عدد المشاركين",
    ("training", "lead_trainer"): "المدرب الرئيسي", ("training", "assessment"): "التقييم",
    ("training", "location"): "الموقع", ("training", "notes"): "ملاحظات",
    ("assignment", "unit_id"): "الوحدة", ("assignment", "commander_id"): "القائد",
    ("assignment", "role"): "الدور", ("assignment", "assigned_date"): "تاريخ التعيين",
    ("assignment", "relieved_date"): "تاريخ الإعفاء", ("assignment", "is_current"): "التعيين الحالي",
    ("assignment", "notes"): "ملاحظات",
    ("note", "entity_type"): "نوع الهدف", ("note", "target_id"): "رقم الهدف",
    ("note", "note_text"): "نص الملاحظة", ("note", "author"): "الكاتب",
    ("note", "note_at"): "تاريخ الملاحظة",
}


def field_labels(entity: str, field: dict[str, Any]) -> dict[str, Any]:
    """One field spec with bilingual labels attached (registry convention)."""
    out = dict(field)
    out["label_en"] = field["label"]
    out["label_ar"] = FIELD_LABELS_AR.get((entity, field["name"]), field["label"])
    return out


def entity_labels(entity: str) -> dict[str, str]:
    label = ENTITY_SPECS[entity]["label"]
    return {"label": label, "label_en": label,
            "label_ar": ENTITY_LABELS_AR.get(entity, label)}


# ---------------------------------------------------------------------------
# field specs — the single source of truth for validation AND the UI forms
# ---------------------------------------------------------------------------
def _f(name: str, type_: str, label: str, **kw: Any) -> dict[str, Any]:
    spec = {"name": name, "type": type_, "label": label}
    spec.update(kw)
    return spec


ENTITY_SPECS: dict[str, dict[str, Any]] = {
    "region": {
        "table": "region", "label": "Region", "tree": True, "naming_entity": "region",
        "fields": [
            _f("name", "text", "Region Name", required=True),
            _f("region_type", "choice", "Type", options=REGION_TYPES, default="Region"),
            _f("parent_id", "ref", "Parent Region", entity="region"),
            _f("country", "text", "Country"),
            _f("description", "textarea", "Description"),
        ],
    },
    "division": {
        "table": "division", "label": "Division", "naming_entity": "division",
        "fields": [
            _f("name", "text", "Division Name", required=True),
            _f("region_id", "ref", "Region", entity="region", required=True),
            _f("division_type", "choice", "Type", options=DIVISION_TYPES),
            _f("formation_date", "date", "Formation Date"),
            _f("headquarters", "text", "Headquarters"),
            _f("description", "textarea", "Description"),
        ],
    },
    "classification": {
        "table": "classification", "label": "Classification", "naming_entity": "classification",
        "fields": [
            _f("name", "text", "Classification Name", required=True),
            _f("category", "choice", "Category", options=CLASS_CATEGORIES),
            _f("readiness_tier", "choice", "Readiness Tier", options=READINESS_TIERS),
            _f("description", "textarea", "Description"),
        ],
    },
    "commander": {
        "table": "commander", "label": "Commander", "naming_entity": "commander",
        "fields": [
            _f("full_name", "text", "Full Name", required=True),
            _f("rank_title", "choice", "Rank", options=[
                "General", "Brigadier General", "Colonel", "Lieutenant Colonel",
                "Major", "Captain", "Lieutenant"]),
            _f("branch", "choice", "Branch", options=["Army", "Air Force", "Navy", "Joint"]),
            _f("commission_date", "date", "Commission Date"),
            _f("status", "choice", "Status", options=COMMANDER_STATUSES, default="Active"),
            _f("biography", "textarea", "Biography"),
        ],
    },
    "unit": {
        "table": "military_unit", "label": "Military Unit", "tree": True, "naming_entity": "unit",
        "fields": [
            _f("name", "text", "Unit Name", required=True),
            _f("code", "text", "Business Code"),
            _f("echelon", "choice", "Echelon", options=UNIT_ECHELONS, default="Brigade"),
            _f("parent_id", "ref", "Parent Unit", entity="unit"),
            _f("classification_id", "ref", "Classification", entity="classification"),
            _f("division_id", "ref", "Division", entity="division"),
            _f("region_id", "ref", "Region", entity="region"),
            _f("commander_id", "ref", "Commander", entity="commander"),
            _f("role", "text", "Role"),
            _f("status", "choice", "Status", options=UNIT_STATUSES, default="Active"),
            _f("direct_personnel", "int", "Direct Personnel", min=0, default=0),
            _f("formation_date", "date", "Formation Date"),
            _f("headquarters", "text", "Headquarters"),
            _f("notes", "textarea", "Notes"),
        ],
    },
    "deployment": {
        "table": "operational_deployment", "label": "Operational Deployment",
        "naming_entity": "deployment", "sync": "deployment",
        "fields": [
            _f("name", "text", "Deployment Name", required=True),
            _f("unit_id", "ref", "Unit", entity="unit", required=True),
            _f("deployment_type", "choice", "Type", options=DEPLOYMENT_TYPES),
            _f("start_date", "date", "Start Date", required=True),
            _f("end_date", "date", "End Date"),
            _f("status", "choice", "Status", options=DEPLOYMENT_STATUSES, default="Planned"),
            _f("is_current", "bool", "Current Deployment", default=False),
            _f("location", "text", "Location"),
            _f("area_of_operations", "text", "Area of Operations"),
            _f("notes", "textarea", "Notes"),
        ],
    },
    "mission": {
        "table": "mission", "label": "Mission", "naming_entity": "mission",
        "fields": [
            _f("name", "text", "Mission Name", required=True),
            _f("unit_id", "ref", "Unit", entity="unit", required=True),
            _f("mission_type", "choice", "Type", options=MISSION_TYPES),
            _f("deployment_id", "ref", "Deployment", entity="deployment"),
            _f("start_date", "date", "Start Date", required=True),
            _f("end_date", "date", "End Date"),
            _f("status", "choice", "Status", options=MISSION_STATUSES, default="Planned"),
            _f("area", "text", "Area"),
            _f("description", "textarea", "Description"),
            _f("notes", "textarea", "Notes"),
        ],
    },
    "armament": {
        "table": "armament", "label": "Armament", "naming_entity": "armament",
        "fields": [
            _f("name", "text", "Armament Name", required=True),
            _f("category", "choice", "Category", options=ARMAMENT_CATEGORIES),
            _f("specification", "textarea", "Specification"),
            _f("origin_country", "text", "Origin Country"),
            _f("description", "textarea", "Description"),
        ],
    },
    "holding": {
        "table": "unit_armament", "label": "Unit Armament", "naming_entity": "holding",
        "unique": ["unit_id", "armament_id"],
        "fields": [
            _f("unit_id", "ref", "Unit", entity="unit", required=True),
            _f("armament_id", "ref", "Armament", entity="armament", required=True),
            _f("quantity", "int", "Quantity", min=1, required=True),
            _f("condition", "choice", "Condition", options=HOLDING_CONDITIONS,
               default="Serviceable"),
            _f("acquisition_year", "int", "Acquisition Year"),
            _f("notes", "textarea", "Notes"),
        ],
    },
    "training": {
        "table": "training", "label": "Training", "naming_entity": "training",
        "fields": [
            _f("exercise_name", "text", "Exercise Name", required=True),
            _f("unit_id", "ref", "Unit", entity="unit", required=True),
            _f("training_type", "choice", "Type", options=TRAINING_TYPES),
            _f("start_date", "date", "Start Date", required=True),
            _f("end_date", "date", "End Date", required=True),
            _f("duration_days", "int", "Duration (days)", min=1, required=True),
            _f("participant_count", "int", "Participants", min=0, required=True),
            _f("lead_trainer", "text", "Lead Trainer"),
            _f("assessment", "choice", "Assessment", options=TRAINING_ASSESSMENTS),
            _f("location", "text", "Location"),
            _f("notes", "textarea", "Notes"),
        ],
    },
    "assignment": {
        "table": "command_assignment", "label": "Command Assignment",
        "naming_entity": "assignment", "sync": "assignment",
        "fields": [
            _f("unit_id", "ref", "Unit", entity="unit", required=True),
            _f("commander_id", "ref", "Commander", entity="commander", required=True),
            _f("role", "choice", "Role", options=ASSIGNMENT_ROLES,
               default="Commanding Officer"),
            _f("assigned_date", "date", "Assigned Date", required=True),
            _f("relieved_date", "date", "Relieved Date"),
            _f("is_current", "bool", "Current Appointment", default=True),
            _f("notes", "textarea", "Notes"),
        ],
    },
    "note": {
        "table": "note", "label": "Note", "naming_entity": "note",
        "fields": [
            _f("entity_type", "choice", "Target Type", options=NOTE_TARGET_TYPES,
               required=True),
            _f("target_id", "int", "Target Id", required=True),
            _f("note_text", "textarea", "Note Text", required=True),
            _f("author", "text", "Author", required=True),
            _f("note_at", "date", "Note Date"),
        ],
    },
}

_AUDIT_HIDDEN = {"path", "depth", "modified_at", "modified_by"}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 field: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field:
            out["field"] = self.field
        return out


# ---------------------------------------------------------------------------
# field validation
# ---------------------------------------------------------------------------
def _validate_fields(entity: str, payload: dict[str, Any], creating: bool) -> dict[str, Any]:
    spec = ENTITY_SPECS[entity]
    known = {f["name"]: f for f in spec["fields"]}
    out: dict[str, Any] = {}
    for name, value in payload.items():
        if name in ("id", "docname", "created_at", "created_by", "modified_at",
                    "modified_by", "path", "depth"):
            raise ServiceError(422, "field_not_editable",
                               f"{name} is system-maintained and cannot be set", name)
        if name not in known:
            raise ServiceError(422, "unknown_field", f"unknown field {name!r}", name)
        fspec = known[name]
        if value is None or value == "":
            out[name] = None
            continue
        ftype = fspec["type"]
        if ftype == "int":
            try:
                ivalue = int(value)
            except (TypeError, ValueError):
                raise ServiceError(422, "invalid_type", f"{name} must be an integer", name)
            if "min" in fspec and ivalue < fspec["min"]:
                raise ServiceError(422, "out_of_range",
                                   f"{name} must be >= {fspec['min']}", name)
            out[name] = ivalue
        elif ftype == "bool":
            out[name] = 1 if value in (True, 1, "1", "true", "on") else 0
        elif ftype == "choice":
            if value not in fspec["options"]:
                raise ServiceError(422, "invalid_choice",
                                   f"{name} must be one of {fspec['options']}", name)
            out[name] = value
        elif ftype == "date":
            try:
                from datetime import date as _date
                _date.fromisoformat(str(value))
            except ValueError:
                raise ServiceError(422, "invalid_date",
                                   f"{name} must be ISO YYYY-MM-DD", name)
            out[name] = str(value)
        elif ftype == "ref":
            try:
                out[name] = int(value)
            except (TypeError, ValueError):
                raise ServiceError(422, "invalid_type", f"{name} must be an id", name)
        else:
            out[name] = str(value)
    if creating:
        for fspec in spec["fields"]:
            if fspec.get("required") and out.get(fspec["name"]) in (None, ""):
                raise ServiceError(422, "required", f"{fspec['label']} is required",
                                   fspec["name"])
    return out


def _defaults(entity: str) -> dict[str, Any]:
    return {f["name"]: f.get("default") for f in ENTITY_SPECS[entity]["fields"]
            if "default" in f}


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def _audit(conn, actor: str, action: str, entity: str, record_id: int | None,
           docname: str | None, old: dict[str, Any] | None, new: dict[str, Any] | None) -> None:
    def scrub(d: dict[str, Any] | None) -> str | None:
        if d is None:
            return None
        return json.dumps({k: v for k, v in d.items() if k not in _AUDIT_HIDDEN},
                          sort_keys=True, default=str)
    summary = None
    if old and new:
        changed = [k for k in new if old.get(k) != new.get(k) and k not in _AUDIT_HIDDEN]
        summary = f"changed: {', '.join(sorted(changed))}" if changed else "no field changes"
    conn.execute(
        "INSERT INTO audit_log (actor, action, entity, record_id, docname, summary, "
        "old_json, new_json, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (actor, action, entity, record_id, docname, summary, scrub(old), scrub(new),
         now_iso()),
    )


# ---------------------------------------------------------------------------
# pointer synchronisation (§8.3, §8.4)
# ---------------------------------------------------------------------------
def _sync_deployment_pointer(conn, unit_id: int) -> None:
    row = conn.execute(
        "SELECT id FROM operational_deployment WHERE unit_id = ? AND is_current = 1 "
        "ORDER BY id DESC LIMIT 1", (unit_id,)).fetchone()
    conn.execute("UPDATE military_unit SET current_deployment_id = ? WHERE id = ?",
                 (row["id"] if row else None, unit_id))


def _sync_commander_pointer(conn, unit_id: int) -> None:
    row = conn.execute(
        "SELECT commander_id FROM command_assignment WHERE unit_id = ? AND is_current = 1 "
        "AND role = 'Commanding Officer' ORDER BY id DESC LIMIT 1", (unit_id,)).fetchone()
    conn.execute("UPDATE military_unit SET commander_id = ? WHERE id = ?",
                 (row["commander_id"] if row else None, unit_id))


# ---------------------------------------------------------------------------
# entity hooks
# ---------------------------------------------------------------------------
def _hook_deployment(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    rules.check_deployment(conn, merged, exclude_id)


def _hook_mission(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    rules.check_mission(conn, merged)


def _hook_training(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    rules.check_training(conn, merged)


def _hook_holding(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    rules.check_holding(merged)
    # UNIQUE(unit_id, armament_id) surfaced as a clean rule violation
    sql = "SELECT id, docname FROM unit_armament WHERE unit_id = ? AND armament_id = ?"
    args: list[Any] = [merged.get("unit_id"), merged.get("armament_id")]
    if exclude_id is not None:
        sql += " AND id != ?"
        args.append(exclude_id)
    clash = conn.execute(sql, args).fetchone()
    if clash:
        raise RuleViolation(
            "duplicate_holding",
            f"this armament is already held by this unit ({clash['docname']}); "
            "edit that record instead",
            "armament_id",
        )


def _hook_note(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    rules.check_note(conn, merged)


def _hook_assignment(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    rules.check_assignment(conn, merged, exclude_id)
    # one current appointment per (unit, role) (§8.4)
    if merged.get("is_current"):
        sql = ("SELECT id, docname FROM command_assignment "
               "WHERE unit_id = ? AND role = ? AND is_current = 1")
        args: list[Any] = [merged.get("unit_id"), merged.get("role") or "Commanding Officer"]
        if exclude_id is not None:
            sql += " AND id != ?"
            args.append(exclude_id)
        clash = conn.execute(sql, args).fetchone()
        if clash:
            raise RuleViolation(
                "one_current_appointment",
                f"a current appointment already exists for this unit and role "
                f"({clash['docname']})", "is_current")


def _hook_commander(conn, merged: dict[str, Any], exclude_id: int | None) -> None:
    old = conn.execute("SELECT status FROM commander WHERE id = ?", (exclude_id,)).fetchone() \
        if exclude_id else None
    if merged.get("status") == "Retired" and (not old or old["status"] != "Retired"):
        if exclude_id:
            rules.check_commander_retire(conn, exclude_id)


_HOOKS: dict[str, Callable[[sqlite3.Connection, dict[str, Any], int | None], None]] = {
    "deployment": _hook_deployment,
    "mission": _hook_mission,
    "training": _hook_training,
    "holding": _hook_holding,
    "note": _hook_note,
    "assignment": _hook_assignment,
    "commander": _hook_commander,
}


# ---------------------------------------------------------------------------
# record helpers
# ---------------------------------------------------------------------------
def _row_to_dict(entity: str, row: sqlite3.Row | None,
                 conn: sqlite3.Connection | None = None,
                 with_rollup: bool = True) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    spec = ENTITY_SPECS[entity]
    if spec.get("tree"):
        data["subtree_personnel"] = None
        if entity == "unit" and conn is not None and with_rollup:
            data["subtree_personnel"] = rules.descendant_personnel(conn, row["id"])
    return data


def _subtree_personnel_map(conn: sqlite3.Connection) -> dict[int, int]:
    """Σ direct personnel per unit in ONE pass (parents precede descendants in
    path order, and every ancestor id appears in the path)."""
    rows = conn.execute(
        "SELECT id, path, direct_personnel FROM military_unit ORDER BY path").fetchall()
    sums: dict[int, int] = {}
    for r in rows:
        sums[r["id"]] = r["direct_personnel"]
    for r in rows:
        for ancestor in [p for p in r["path"].split("/") if p][:-1]:
            sums[int(ancestor)] = sums.get(int(ancestor), 0) + r["direct_personnel"]
    return sums


def get_record(conn, entity: str, record_id: int) -> dict[str, Any] | None:
    spec = ENTITY_SPECS[entity]
    row = conn.execute(f"SELECT * FROM {spec['table']} WHERE id = ?", (record_id,)).fetchone()
    return _row_to_dict(entity, row, conn)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create(conn, entity: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
    spec = ENTITY_SPECS[entity]
    fields = _validate_fields(entity, payload, creating=True)
    merged = {**_defaults(entity), **fields}
    if spec.get("tree"):
        rules.check_tree_parent(conn, spec["table"], None, merged.get("parent_id"))
    hook = _HOOKS.get(entity)
    if hook:
        hook(conn, merged, None)
    context = {"year": now_iso()[:4]}
    for f in spec["fields"]:
        if f["type"] == "choice" and f.get("options"):
            context[f["name"]] = merged.get(f["name"])
    docname = naming.next_name(conn, spec["naming_entity"], context)

    now = now_iso()
    columns = ["docname", *merged.keys(), "created_at", "created_by"]
    values = [docname, *merged.values(), now, actor]
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO {spec['table']} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    record_id = cur.lastrowid

    if spec.get("tree"):
        path, depth = rules.compute_path(conn, spec["table"], record_id,
                                         merged.get("parent_id"))
        conn.execute(f"UPDATE {spec['table']} SET path = ?, depth = ? WHERE id = ?",
                     (path, depth, record_id))
    _after_write(conn, entity, record_id, merged, actor, is_new=True)
    _audit(conn, actor, "create", entity, record_id, docname, None, dict(merged))
    row = conn.execute(f"SELECT * FROM {spec['table']} WHERE id = ?", (record_id,)).fetchone()
    return _row_to_dict(entity, row, conn)  # type: ignore[return-value]


def update(conn, entity: str, record_id: int, payload: dict[str, Any],
           actor: str) -> dict[str, Any]:
    spec = ENTITY_SPECS[entity]
    old = conn.execute(f"SELECT * FROM {spec['table']} WHERE id = ?", (record_id,)).fetchone()
    if not old:
        raise ServiceError(404, "not_found", f"{spec['label']} {record_id} not found")
    old_d = dict(old)
    fields = _validate_fields(entity, payload, creating=False)
    merged = {**old_d, **fields}

    if spec.get("tree"):
        rules.check_tree_parent(conn, spec["table"], record_id, merged.get("parent_id"))
    # lifecycle transition checks against the current stored state
    if entity == "deployment":
        rules.check_deployment_transition(old_d.get("status"), merged.get("status"))
    elif entity == "mission":
        rules.check_mission_transition(old_d.get("status"), merged.get("status"))
    elif entity == "commander":
        rules.check_commander_transition(old_d.get("status"), merged.get("status"))
    hook = _HOOKS.get(entity)
    if hook:
        hook(conn, merged, record_id)

    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE {spec['table']} SET {sets}, modified_at = ?, modified_by = ? "
            f"WHERE id = ?",
            [*fields.values(), now_iso(), actor, record_id],
        )
    if spec.get("tree") and "parent_id" in fields:
        _rebuild_subtree_paths(conn, spec["table"], record_id, merged.get("parent_id"))
    _after_write(conn, entity, record_id, merged, actor, is_new=False)
    _audit(conn, actor, "update", entity, record_id, old_d.get("docname"), old_d, merged)
    row = conn.execute(f"SELECT * FROM {spec['table']} WHERE id = ?", (record_id,)).fetchone()
    return _row_to_dict(entity, row, conn)  # type: ignore[return-value]


def _rebuild_subtree_paths(conn, table: str, node_id: int, parent_id: int | None) -> None:
    """Re-root a subtree: node path/depth change, descendants keep their suffixes."""
    node = conn.execute(f"SELECT path FROM {table} WHERE id = ?", (node_id,)).fetchone()
    old_path = node["path"]
    new_path, new_depth = rules.compute_path(conn, table, node_id, parent_id)
    conn.execute(f"UPDATE {table} SET path = ?, depth = ? WHERE id = ?",
                 (new_path, new_depth, node_id))
    rows = conn.execute(
        f"SELECT id, path FROM {table} WHERE path LIKE ? AND id != ?",
        (old_path + "%", node_id)).fetchall()
    for r in rows:
        suffix = r["path"][len(old_path):]
        conn.execute(f"UPDATE {table} SET path = ?, depth = ? WHERE id = ?",
                     (new_path + suffix, new_depth + suffix.count("/"), r["id"]))


def _after_write(conn, entity: str, record_id: int, merged: dict[str, Any],
                 actor: str, is_new: bool) -> None:
    if entity == "deployment" and merged.get("unit_id") is not None:
        _sync_deployment_pointer(conn, merged["unit_id"])
    elif entity == "assignment" and merged.get("unit_id") is not None:
        _sync_commander_pointer(conn, merged["unit_id"])


def delete(conn, entity: str, record_id: int, actor: str) -> None:
    spec = ENTITY_SPECS[entity]
    old = conn.execute(f"SELECT * FROM {spec['table']} WHERE id = ?", (record_id,)).fetchone()
    if not old:
        raise ServiceError(404, "not_found", f"{spec['label']} {record_id} not found")
    old_d = dict(old)
    rules.check_delete(conn, entity, record_id)
    if entity == "deployment":
        # a current deployment must never leave a dangling pointer
        unit_id = old_d.get("unit_id")
        conn.execute(f"DELETE FROM {spec['table']} WHERE id = ?", (record_id,))
        if unit_id is not None:
            _sync_deployment_pointer(conn, unit_id)
    elif entity == "assignment":
        unit_id = old_d.get("unit_id")
        conn.execute(f"DELETE FROM {spec['table']} WHERE id = ?", (record_id,))
        if unit_id is not None:
            _sync_commander_pointer(conn, unit_id)
    else:
        try:
            conn.execute(f"DELETE FROM {spec['table']} WHERE id = ?", (record_id,))
        except sqlite3.IntegrityError as exc:
            raise ServiceError(409, "delete_blocked",
                               f"cannot delete: {exc}") from exc
    _audit(conn, actor, "delete", entity, record_id, old_d.get("docname"), old_d, None)


def list_records(conn, entity: str, q: str | None = None, filters: dict[str, Any] | None = None,
                 sort: str = "id", direction: str = "asc",
                 limit: int = 50, offset: int = 0) -> dict[str, Any]:
    spec = ENTITY_SPECS[entity]
    where: list[str] = []
    args: list[Any] = []
    if q:
        text_cols = [f["name"] for f in spec["fields"] if f["type"] in ("text", "textarea")]
        like = " OR ".join(f"{c} LIKE ?" for c in text_cols)
        where.append(f"({like} OR docname LIKE ?)")
        args.extend([f"%{q}%"] * (len(text_cols) + 1))
    for key, value in (filters or {}).items():
        if value in (None, ""):
            continue
        where.append(f"{key} = ?")
        args.append(value)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    allowed_sort = {f["name"] for f in spec["fields"]} | {"id", "docname", "created_at"}
    if sort not in allowed_sort:
        sort = "id"
    direction = "DESC" if direction.lower() == "desc" else "ASC"
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM {spec['table']}{where_sql}", args).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM {spec['table']}{where_sql} ORDER BY {sort} {direction} "
        f"LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    # list rows skip the per-row rollup (N+1); use force-summary for that
    return {"records": [_row_to_dict(entity, r, conn, with_rollup=False) for r in rows],
            "total": total}


# ---------------------------------------------------------------------------
# read models
# ---------------------------------------------------------------------------
def tree(conn, entity: str) -> list[dict[str, Any]]:
    spec = ENTITY_SPECS[entity]
    rows = conn.execute(
        f"SELECT * FROM {spec['table']} ORDER BY path, id").fetchall()
    rollup = _subtree_personnel_map(conn) if entity == "unit" else None
    nodes = []
    for r in rows:
        d = _row_to_dict(entity, r, conn, with_rollup=False)
        if rollup is not None:
            d["subtree_personnel"] = rollup.get(r["id"], 0)
        d["children"] = []
        nodes.append(d)
    by_id = {n["id"]: n for n in nodes}
    roots: list[dict[str, Any]] = []
    for n in nodes:
        parent_id = n.get("parent_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(n)
        else:
            roots.append(n)
    return roots


def force_summary(conn, unit_id: int) -> dict[str, Any] | None:
    unit = conn.execute("SELECT * FROM military_unit WHERE id = ?", (unit_id,)).fetchone()
    if not unit:
        return None
    node = dict(unit)
    subtree = rules.descendant_personnel(conn, unit_id)
    dep = conn.execute(
        "SELECT * FROM operational_deployment WHERE unit_id = ? AND is_current = 1 "
        "ORDER BY id DESC LIMIT 1", (unit_id,)).fetchone()
    siblings = conn.execute(
        "SELECT id, docname, name, status FROM military_unit "
        "WHERE parent_id IS ? AND id != ?",
        (unit["parent_id"], unit_id)).fetchall()
    missons = conn.execute(
        "SELECT id, docname, name, status FROM mission WHERE unit_id = ? "
        "ORDER BY start_date DESC LIMIT 20", (unit_id,)).fetchall()
    top = conn.execute(
        """SELECT a.name, a.category, h.quantity, h.condition
           FROM unit_armament h JOIN armament a ON a.id = h.armament_id
           WHERE h.unit_id = ? ORDER BY h.quantity DESC LIMIT 20""", (unit_id,)).fetchall()
    children = conn.execute(
        "SELECT id, docname, name, echelon, status, direct_personnel FROM military_unit "
        "WHERE parent_id = ? ORDER BY name", (unit_id,)).fetchall()
    return {
        "unit": node,
        "subtree_personnel": subtree,
        "current_deployment": dict(dep) if dep else None,
        "siblings": [dict(r) for r in siblings],
        "missions": [dict(r) for r in missons],
        "armament_top": [dict(r) for r in top],
        "children": [dict(r) for r in children],
    }


def armament_holdings(conn, armament_id: int) -> dict[str, Any] | None:
    arm = conn.execute("SELECT * FROM armament WHERE id = ?", (armament_id,)).fetchone()
    if not arm:
        return None
    rows = conn.execute(
        """SELECT h.*, u.docname AS unit_docname, u.name AS unit_name
           FROM unit_armament h JOIN military_unit u ON u.id = h.unit_id
           WHERE h.armament_id = ? ORDER BY h.quantity DESC""", (armament_id,)).fetchall()
    total = sum(r["quantity"] for r in rows)
    return {"armament": dict(arm), "holdings": [dict(r) for r in rows],
            "total_quantity": total}


# ---------------------------------------------------------------------------
# dashboard (workspace cards, status charts, action lists)
# ---------------------------------------------------------------------------
def _count(conn, sql: str, args: list[Any] | tuple = ()) -> int:
    return int(conn.execute(sql, args).fetchone()["n"])


def summary(conn) -> dict[str, Any]:
    cards = {
        "active_units": _count(conn, "SELECT COUNT(*) AS n FROM military_unit "
                               "WHERE status = 'Active'"),
        "current_deployments": _count(conn, "SELECT COUNT(*) AS n FROM "
                                      "operational_deployment WHERE is_current = 1"),
        "open_missions": _count(conn, "SELECT COUNT(*) AS n FROM mission "
                                "WHERE status IN ('Planned', 'Ongoing')"),
        "training_this_year": _count(conn, "SELECT COUNT(*) AS n FROM training "
                                     "WHERE substr(start_date, 1, 4) = ?",
                                     (now_iso()[:4],)),
        "active_commanders": _count(conn, "SELECT COUNT(*) AS n FROM commander "
                                    "WHERE status = 'Active'"),
    }

    def dist(sql: str) -> list[dict[str, Any]]:
        return [{"key": r["key"] or "(unset)", "count": r["n"]}
                for r in conn.execute(sql).fetchall()]

    charts = {
        "unit_status": dist("SELECT status AS key, COUNT(*) AS n FROM military_unit "
                            "GROUP BY status ORDER BY n DESC"),
        "unit_type": dist("SELECT echelon AS key, COUNT(*) AS n FROM military_unit "
                          "GROUP BY echelon ORDER BY n DESC"),
        "region_distribution": dist(
            "SELECT COALESCE(r.name, '(unassigned)') AS key, COUNT(*) AS n "
            "FROM military_unit u LEFT JOIN region r ON r.id = u.region_id "
            "GROUP BY r.name ORDER BY n DESC LIMIT 12"),
    }

    def rows(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    lists = {
        "upcoming_deployments": rows(
            "SELECT d.id, d.docname, d.name, d.start_date, d.status, u.name AS unit_name "
            "FROM operational_deployment d JOIN military_unit u ON u.id = d.unit_id "
            "WHERE d.end_date IS NULL AND d.status IN ('Planned', 'Active') "
            "ORDER BY d.start_date LIMIT 10"),
        "upcoming_trainings": rows(
            "SELECT t.id, t.docname, t.exercise_name, t.start_date, t.end_date, "
            "t.participant_count, u.name AS unit_name "
            "FROM training t JOIN military_unit u ON u.id = t.unit_id "
            "WHERE t.start_date >= ? ORDER BY t.start_date LIMIT 10", (now_iso()[:10],)),
        "low_readiness_units": rows(
            "SELECT u.id, u.docname, u.name, u.status, c.readiness_tier "
            "FROM military_unit u LEFT JOIN classification c "
            "ON c.id = u.classification_id "
            "WHERE c.readiness_tier = 'Low' OR u.status IN ('Stand-down', 'Reorganizing') "
            "ORDER BY u.name LIMIT 10"),
        "recent_activity": rows(
            "SELECT actor, action, entity, record_id, docname, summary, at "
            "FROM audit_log ORDER BY id DESC LIMIT 12"),
        "unit_readiness": rows(
            "SELECT u.id, u.docname, u.name, u.status, u.direct_personnel, "
            "c.readiness_tier, c.name AS classification_name "
            "FROM military_unit u LEFT JOIN classification c "
            "ON c.id = u.classification_id ORDER BY u.name LIMIT 12"),
    }
    return {"cards": cards, "charts": charts, "lists": lists}


# ---------------------------------------------------------------------------
# transaction wrapper
# ---------------------------------------------------------------------------
@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """One connection + one transaction per request; commits on success.

    ``BEGIN IMMEDIATE`` serialises writers from the first statement so that
    check-then-act rules (one current deployment per unit, one current
    appointment per unit+role, unique holdings, naming counters) cannot race
    between concurrent requests — the transaction sees a stable world and the
    next writer waits (busy_timeout) instead of interleaving.
    """
    ensure()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

"""Registry-engine EntitySpecs for the twelve military entities.

The SIRAJ list engine (``repo.list_records`` / ``kpi_summary`` /
``transfer.export_bytes`` / ``schemas.fields_meta`` / the whole browser list,
filter-builder and export stack) is schema-driven: one ``EntitySpec`` per entity
describes the table, its fields and how a record is titled.  This module gives
the twelve Military Organization entities those specs, so every military table
is browsed, filtered, laid out and exported through the *same* engine that
serves People, Places and Organizations — one query/export contract for the
whole application.

The write path is different on purpose: military create/update/delete must run
through ``app.military.service`` (business rules, automatic numbering, audit),
so the generic-API dispatch in ``app/server/api.py`` routes reads through the
shared engine and writes through the military service.
"""
from __future__ import annotations

from typing import Any

from ..schemas import (
    REF_TABLES,  # noqa: F401 - single map, shared with resolve_ref
    EntitySpec,
    Field,
)

ENTITY_AR = {
    "unit": ("الوحدة", "الوحدات"),
    "region": ("المنطقة", "المناطق"),
    "division": ("الفرع", "الفروع"),
    "classification": ("التصنيف", "التصنيفات"),
    "armament": ("التسليح", "التسليحات"),
    "holding": ("حيازة", "الحيازات"),
    "deployment": ("النشر", "عمليات النشر"),
    "mission": ("المهمة", "المهام"),
    "training": ("التدريب", "التدريبات"),
    "commander": ("القائد", "القادة"),
    "assignment": ("التعيين", "التعيينات"),
    "note": ("ملاحظة", "ملاحظات"),
}

FIELD_AR = {
    "docname": "اسم المستند", "code": "الرمز", "name": "الاسم",
    "echelon": "الإطار", "parent_id": "الوحدة الأعلى", "role": "الدور",
    "classification_id": "التصنيف", "status": "الحالة",
    "commander_id": "القائد", "current_deployment_id": "النشر الحالي",
    "direct_personnel": "القوة المباشرة", "division_id": "الفرع",
    "region_id": "المنطقة", "formation_date": "تاريخ التشكيل",
    "headquarters": "المقر", "notes": "ملاحظات",
    "region_type": "نوع المنطقة", "country": "البلد", "description": "الوصف",
    "division_type": "نوع الفرع",
    "category": "الفئة", "readiness_tier": "درجة الجاهزية",
    "specification": "المواصفات", "origin_country": "بلد المنشأ",
    "unit_id": "الوحدة", "armament_id": "التسليح", "quantity": "الكمية",
    "condition": "الحالة", "acquisition_year": "سنة التزويد",
    "deployment_type": "نوع النشر", "start_date": "تاريخ البدء",
    "end_date": "تاريخ الانتهاء", "is_current": "حالي",
    "location": "الموقع", "area_of_operations": "منطقة العمليات",
    "mission_type": "نوع المهمة", "deployment_id": "النشر",
    "area": "المنطقة", "exercise_name": "اسم التمرين",
    "training_type": "نوع التدريب", "duration_days": "المدة (أيام)",
    "participant_count": "عدد المشاركين", "lead_trainer": "المدرب الرئيسي",
    "assessment": "التقييم", "full_name": "الاسم الكامل",
    "rank_title": "الرتبة", "branch": "السلاح", "commission_date": "تاريخ الالتحاق",
    "biography": "السيرة", "assigned_date": "تاريخ التعيين",
    "relieved_date": "تاريخ الإعفاء", "entity_type": "نوع الكيان",
    "target_id": "السجل المستهدف", "note_text": "نص الملاحظة", "author": "الكاتب",
    "note_at": "تاريخ الملاحظة", "path": "المسار", "depth": "العمق",
    "created_at": "تاريخ الإنشاء", "created_by": "أنشأه",
    "modified_at": "آخر تحديث", "modified_by": "حدّثه",
}


def _label(key: str) -> tuple[str, str]:
    en = key.replace("_", " ").replace(" id", " ").strip().title()
    en = en.replace(" Id", " ").strip()
    return en, FIELD_AR.get(key, en)


def F(key: str, type_: str, **kw: Any) -> Field:  # noqa: N802 - mirrors schemas.F
    en, ar = _label(key)
    return Field(key=key, type=type_, label_en=en, label_ar=ar, **kw)


def _ref(key: str, ref: str, **kw: Any) -> Field:
    en, ar = _label(key)
    return Field(key=key, type="fk", label_en=en, label_ar=ar, ref=ref, **kw)


def _sel(key: str, **kw: Any) -> Field:
    """A vocabulary select that stores its code (free choice text)."""
    en, ar = _label(key)
    return Field(key=key, type="select", label_en=en, label_ar=ar, store="code",
                 **kw)


def _audit_fields() -> list[Field]:
    return [
        F("created_at", "text", group="system", read_only=True, in_list=False,
          filterable=True, system=True),
        F("created_by", "text", group="system", read_only=True, in_list=False,
          system=True),
        F("modified_at", "text", group="system", read_only=True, in_list=False,
          filterable=True, system=True),
        F("modified_by", "text", group="system", read_only=True, in_list=False,
          system=True),
    ]


def _docname(in_list: bool = False) -> Field:
    return F("docname", "text", group="identity", read_only=True, max_len=64,
             in_list=in_list, sortable=True)


TITLE_FIELDS = {
    "unit": ("name", "docname"),
    "region": ("name", "docname"),
    "division": ("name", "docname"),
    "classification": ("name", "docname"),
    "armament": ("name", "docname"),
    "holding": ("docname",),
    "deployment": ("name", "docname"),
    "mission": ("name", "docname"),
    "training": ("exercise_name", "docname"),
    "commander": ("full_name", "docname"),
    "assignment": ("docname",),
    "note": ("docname",),
}

_DESCRIPTIONS = {
    "unit": ("Military units and their hierarchy", "الوحدات العسكرية وتسلسلها"),
    "region": ("Command regions and areas", "المناطق القيادية"),
    "division": ("Divisions and formations", "الفروع والتشكيلات"),
    "classification": ("Unit classifications", "تصنيفات الوحدات"),
    "armament": ("Armament catalogue", "فهرس التسليح"),
    "holding": ("Unit armament holdings", "حيازات التسليح للوحدات"),
    "deployment": ("Operational deployments", "عمليات النشر"),
    "mission": ("Missions", "المهام"),
    "training": ("Training and exercises", "التدريبات والتمارين"),
    "commander": ("Commanders", "القادة"),
    "assignment": ("Command appointments", "التعيينات القيادية"),
    "note": ("Notes on military records", "ملاحظات على السجلات العسكرية"),
}


def _spec(key: str, table: str, fields: list[Field], icon: str) -> EntitySpec:
    en, ar = ENTITY_AR[key]
    den, dar = _DESCRIPTIONS[key]
    title_field = TITLE_FIELDS[key][0]
    return EntitySpec(
        key=key, table=table,
        label_en=key.title() if key != "note" else "Note", label_ar=en,
        plural_en=key.title() + "s" if key != "note" else "Notes", plural_ar=ar,
        icon=icon, code_prefix="MIL-" + key[:3].upper(),
        fields=fields,
        title_fields=[title_field],
        name_fields=TITLE_FIELDS[key],
        default_sort="id", default_order="desc",
        description_en=den, description_ar=dar,
        soft_delete=False,            # military rows are deleted outright
        freshness_col="modified_at",  # audit stamp on these tables
        full_text_index=False,        # not in search_doc; LIKE fallback in queries
    )


def _build_specs() -> dict[str, EntitySpec]:
    s: dict[str, EntitySpec] = {}

    s["unit"] = _spec("unit", "military_unit", [
        _docname(),
        F("code", "text", group="identity", in_list=True, max_len=32),
        F("name", "text", group="identity", required=True, in_list=True),
        _sel("echelon", in_list=True),
        _ref("parent_id", "unit", group="structure"),
        _ref("classification_id", "classification", group="structure", in_list=True),
        _sel("role", in_list=True),
        _sel("status", in_list=True),
        _ref("commander_id", "commander", group="structure"),
        _ref("current_deployment_id", "deployment", group="structure"),
        F("direct_personnel", "int", group="structure", in_list=True),
        _ref("division_id", "division", group="structure", in_list=True),
        _ref("region_id", "region", group="structure", in_list=True),
        F("formation_date", "date", group="structure"),
        F("headquarters", "text", group="structure"),
        F("notes", "textarea", group="main"),
        *_audit_fields(),
    ], "shield")

    s["region"] = _spec("region", "region", [
        _docname(),
        F("name", "text", group="identity", required=True, in_list=True),
        _sel("region_type", in_list=True),
        _ref("parent_id", "region", group="structure"),
        F("country", "text", group="structure", in_list=True),
        F("description", "textarea", group="main"),
        F("path", "text", group="system", read_only=True, in_list=False, system=True),
        F("depth", "int", group="system", read_only=True, in_list=False, system=True),
        *_audit_fields(),
    ], "map-pin")

    s["division"] = _spec("division", "division", [
        _docname(),
        F("name", "text", group="identity", required=True, in_list=True),
        _ref("region_id", "region", group="structure", in_list=True),
        _sel("division_type", in_list=True),
        F("formation_date", "date", group="structure", in_list=True),
        F("headquarters", "text", group="structure", in_list=True),
        F("description", "textarea", group="main"),
        *_audit_fields(),
    ], "layers")

    s["classification"] = _spec("classification", "classification", [
        _docname(),
        F("name", "text", group="identity", required=True, unique=True, in_list=True),
        _sel("category", in_list=True),
        _sel("readiness_tier", in_list=True),
        F("description", "textarea", group="main"),
        *_audit_fields(),
    ], "tag")

    s["armament"] = _spec("armament", "armament", [
        _docname(),
        F("name", "text", group="identity", required=True, unique=True, in_list=True),
        _sel("category", in_list=True),
        F("specification", "textarea", group="main"),
        F("origin_country", "text", group="main", in_list=True),
        F("description", "textarea", group="main"),
        *_audit_fields(),
    ], "target")

    s["holding"] = _spec("holding", "unit_armament", [
        _docname(in_list=True),
        _ref("unit_id", "unit", group="structure", required=True, in_list=True),
        _ref("armament_id", "armament", group="structure", required=True, in_list=True),
        F("quantity", "int", group="main", in_list=True),
        _sel("condition", in_list=True),
        F("acquisition_year", "int", group="main"),
        F("notes", "textarea", group="main"),
        *_audit_fields(),
    ], "package")

    s["deployment"] = _spec("deployment", "operational_deployment", [
        _docname(),
        _ref("unit_id", "unit", group="structure", required=True, in_list=True),
        F("name", "text", group="identity", required=True, in_list=True),
        _sel("deployment_type", in_list=True),
        F("start_date", "date", group="main", required=True, in_list=True),
        F("end_date", "date", group="main", in_list=True),
        _sel("status", in_list=True),
        F("is_current", "bool", group="main", in_list=True),
        F("location", "text", group="main"),
        F("area_of_operations", "textarea", group="main"),
        F("notes", "textarea", group="main"),
        *_audit_fields(),
    ], "send")

    s["mission"] = _spec("mission", "mission", [
        _docname(),
        _ref("unit_id", "unit", group="structure", required=True, in_list=True),
        F("name", "text", group="identity", required=True, in_list=True),
        _sel("mission_type", in_list=True),
        _ref("deployment_id", "deployment", group="structure", in_list=True),
        F("start_date", "date", group="main", in_list=True),
        F("end_date", "date", group="main"),
        _sel("status", in_list=True),
        F("area", "text", group="main"),
        F("description", "textarea", group="main"),
        F("notes", "textarea", group="main"),
        *_audit_fields(),
    ], "crosshair")

    s["training"] = _spec("training", "training", [
        _docname(),
        _ref("unit_id", "unit", group="structure", required=True, in_list=True),
        F("exercise_name", "text", group="identity", required=True, in_list=True),
        _sel("training_type", in_list=True),
        F("start_date", "date", group="main", required=True, in_list=True),
        F("end_date", "date", group="main", in_list=True),
        F("duration_days", "int", group="main"),
        F("participant_count", "int", group="main", in_list=True),
        F("lead_trainer", "text", group="main"),
        _sel("assessment", in_list=True),
        F("location", "text", group="main"),
        F("notes", "textarea", group="main"),
        *_audit_fields(),
    ], "award")

    s["commander"] = _spec("commander", "commander", [
        _docname(),
        F("full_name", "text", group="identity", required=True, in_list=True),
        F("rank_title", "text", group="identity", in_list=True),
        _sel("branch", in_list=True),
        F("commission_date", "date", group="main"),
        _sel("status", in_list=True),
        F("biography", "textarea", group="main"),
        *_audit_fields(),
    ], "user")

    s["assignment"] = _spec("assignment", "command_assignment", [
        _docname(in_list=True),
        _ref("unit_id", "unit", group="structure", required=True, in_list=True),
        _ref("commander_id", "commander", group="structure", required=True, in_list=True),
        F("role", "text", group="main", in_list=True),
        F("assigned_date", "date", group="main", in_list=True),
        F("relieved_date", "date", group="main"),
        F("is_current", "bool", group="main", in_list=True),
        F("notes", "textarea", group="main"),
        *_audit_fields(),
    ], "briefcase")

    s["note"] = _spec("note", "note", [
        _docname(in_list=True),
        _sel("entity_type", in_list=True),
        F("target_id", "int", group="main", in_list=True),
        F("note_text", "textarea", group="main", in_list=True),
        F("author", "text", group="main", in_list=True),
        F("note_at", "date", group="main", in_list=True),
        *_audit_fields(),
    ], "file-text")

    return s


MIL_SPECS: dict[str, EntitySpec] = _build_specs()


def is_mil(entity: str) -> bool:
    return entity in MIL_SPECS


def mil_entity_meta() -> list[dict]:
    """``meta.entities`` entries in the registry shape, for the twelve entities."""
    out = []
    for e in MIL_SPECS.values():
        den, dar = _DESCRIPTIONS[e.key]
        out.append({
            "key": e.key, "label": e.label_ar, "label_en": e.label_en,
            "label_ar": e.label_ar, "plural_en": e.plural_en,
            "plural_ar": e.plural_ar, "icon": e.icon,
            "code_prefix": e.code_prefix, "description_en": den,
            "description_ar": dar, "tags": [], "has_positions": False,
            "children": list(("unit", "region") if e.key in ("unit", "region") else ()),
        })
    return out


def mil_query_shim(item: dict, spec: EntitySpec) -> dict:
    """Give military rows the display-title keys the shared views read.

    The registry list/cards/gallery renderers title a record from ``name_ar`` /
    ``name_en``; military tables spell that column ``name`` (``full_name``,
    ``exercise_name`` …).  One shim keeps the renderer generic.
    """
    title = spec.title(item)
    item.setdefault("_title", title)
    item["name_en"] = item.get("name_en") or title
    item["name_ar"] = item.get("name_ar") or title
    return item


def mil_options(conn, spec: EntitySpec, q: str | None, limit: int,
                ids: list[int] | None = None) -> list[dict]:
    """Picker options for a military entity (searchable, paged)."""
    title_col = spec.name_fields[0]
    extra = [k for k in spec.name_fields[1:]]
    cols = f"id, docname, {title_col}" + "".join(f", {k}" for k in extra)
    if ids:
        rows = conn.execute(
            f"SELECT {cols} FROM {spec.table} WHERE id IN ({','.join('?' * len(ids))})",
            ids).fetchall()
    else:
        like = f"%{(q or '').strip()}%"
        rows = conn.execute(
            f"SELECT {cols} FROM {spec.table} "
            f"WHERE (? = '' OR {title_col} LIKE ? OR docname LIKE ?) "
            f"ORDER BY {title_col} LIMIT ?",
            [(q or "").strip(), like, like, max(1, min(int(limit or 50), 200))],
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        title = spec.title(d)
        hint = d.get("docname") or ""
        out.append({"id": d["id"], "code": d.get("docname"), "label": title,
                    "label_ar": title, "hint": hint, "image": None,
                    "type": spec.key})
    return out

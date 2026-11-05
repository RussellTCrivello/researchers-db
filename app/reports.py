"""
Reporting engine.

Every report returns the same JSON envelope so the frontend can render, print
and export any report with a single generic component:

    {
      key, title_en, title_ar, description_en, description_ar, generated_at,
      params, summary: [{label_en, label_ar, value, unit}],
      sections: [{id, title_en, title_ar, type, columns:[{key,label_en,label_ar}],
                  rows:[{...}], note}],
      notes: [...]
    }

`type` is one of: table | bar | pie | timeline | matrix | cards.
"""
from __future__ import annotations

import io
import json

from . import db, repo
from .schemas import ENTITIES, derived_map


# ---------------------------------------------------------------------------
def _labels(conn, domain: str, ids_counts: list[tuple[int, int]], lang_field="label_en"):
    out = []
    for lid, cnt in ids_counts:
        row = conn.execute("SELECT code, label_en, label_ar, color FROM lookup WHERE id=?",
                           (lid,)).fetchone()
        out.append({
            "label_en": row["label_en"] if row else "(unset)",
            "label_ar": row["label_ar"] if row else "(غير محدد)",
            "code": row["code"] if row else None,
            "color": row["color"] if row else "gray",
            "value": cnt,
        })
    return out


def _dist(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def envelope(key: str, title_en: str, title_ar: str, *, desc_en="", desc_ar="",
             summary=None, sections=None, notes=None, params=None) -> dict:
    return {
        "key": key, "title_en": title_en, "title_ar": title_ar,
        "description_en": desc_en, "description_ar": desc_ar,
        "generated_at": db.now(), "params": params or {},
        "summary": summary or [], "sections": sections or [], "notes": notes or [],
    }


# ---------------------------------------------------------------------------
# 1. Registry overview
# ---------------------------------------------------------------------------
def report_overview(conn, params: dict | None = None) -> dict:
    counts = {}
    for key, spec in ENTITIES.items():
        counts[key] = conn.execute(
            f"SELECT COUNT(*) c FROM {spec.table} WHERE deleted_at IS NULL").fetchone()["c"]
    by_status = _labels(conn, "record_status", [
        (int(r["record_status_id"]), r["c"]) for r in conn.execute(
            """SELECT record_status_id, COUNT(*) c FROM (
                 SELECT record_status_id FROM person WHERE deleted_at IS NULL
                 UNION ALL SELECT record_status_id FROM institution WHERE deleted_at IS NULL
                 UNION ALL SELECT record_status_id FROM place WHERE deleted_at IS NULL
                 UNION ALL SELECT record_status_id FROM event WHERE deleted_at IS NULL
                 UNION ALL SELECT record_status_id FROM relationship WHERE deleted_at IS NULL
                 UNION ALL SELECT record_status_id FROM source WHERE deleted_at IS NULL
               ) WHERE record_status_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""")])
    by_auth = _labels(conn, "authentication_level", [
        (int(r["authentication_id"]), r["c"]) for r in conn.execute(
            """SELECT authentication_id, COUNT(*) c FROM person
               WHERE deleted_at IS NULL AND authentication_id IS NOT NULL
               GROUP BY 1 ORDER BY 2 DESC""")])
    summary = [
        {"label_en": "Persons", "label_ar": "الأشخاص", "value": counts["person"]},
        {"label_en": "Institutions", "label_ar": "المؤسسات", "value": counts["institution"]},
        {"label_en": "Places", "label_ar": "الأماكن", "value": counts["place"]},
        {"label_en": "Relationships", "label_ar": "العلاقات", "value": counts["relationship"]},
        {"label_en": "Sources", "label_ar": "المصادر", "value": counts["source"]},
        {"label_en": "Events", "label_ar": "الأحداث", "value": counts["event"]},
        {"label_en": "Change-log entries", "label_ar": "قيود سجل التغييرات",
         "value": conn.execute("SELECT COUNT(*) c FROM change_log").fetchone()["c"]},
        {"label_en": "Countries covered", "label_ar": "الدول المغطاة",
         "value": conn.execute(
             "SELECT COUNT(DISTINCT country_id) c FROM place WHERE country_id IS NOT NULL").fetchone()["c"]},
    ]
    sections = [
        {"id": "counts", "type": "bar", "title_en": "Records by entity type",
         "title_ar": "السجلات حسب نوع الكيان",
         "columns": [{"key": "label_en", "label_en": "Entity", "label_ar": "الكيان"},
                     {"key": "value", "label_en": "Records", "label_ar": "عدد السجلات"}],
         "rows": [{"label_en": ENTITIES[k].plural_en, "label_ar": ENTITIES[k].plural_ar,
                   "value": v} for k, v in counts.items()]},
        {"id": "status", "type": "pie", "title_en": "Records by status",
         "title_ar": "السجلات حسب الحالة", "rows": by_status,
         "columns": [{"key": "label_en", "label_en": "Status", "label_ar": "الحالة"},
                     {"key": "value", "label_en": "Records", "label_ar": "العدد"}]},
        {"id": "auth", "type": "pie", "title_en": "Persons by authentication level",
         "title_ar": "الأشخاص حسب مستوى التحقق", "rows": by_auth,
         "columns": [{"key": "label_en", "label_en": "Level", "label_ar": "المستوى"},
                     {"key": "value", "label_en": "Persons", "label_ar": "العدد"}]},
    ]
    return envelope("overview", "Registry overview", "نظرة عامة على السجل",
                    desc_en="Headline counts and distribution of the whole registry.",
                    desc_ar="أرقام رئيسية وتوزيعات على مستوى السجل بأكمله.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 2. Data quality / completeness audit
# ---------------------------------------------------------------------------
CRITICAL_FIELDS = {
    "person": ["name_ar", "classification_id", "nationality_id", "record_status_id",
               "authentication_id", "primary_source_id"],
    "institution": ["name_ar", "institution_type_id", "country_id", "record_status_id",
                    "primary_source_id"],
    "place": ["name_ar", "place_type_id", "country_id", "latitude", "record_status_id"],
    "source": ["title", "source_type_id", "reliability_id", "record_status_id"],
    "relationship": ["entity1_id", "entity2_id", "relationship_type_id", "source_id"],
    "event": ["title_ar", "event_type_id", "start_date", "record_status_id"],
}


def report_quality(conn, params: dict | None = None) -> dict:
    sections = []
    summary = []
    for key, fields in CRITICAL_FIELDS.items():
        spec = ENTITIES[key]
        total = conn.execute(
            f"SELECT COUNT(*) c FROM {spec.table} WHERE deleted_at IS NULL").fetchone()["c"]
        rows = []
        for fk in fields:
            filled = conn.execute(
                f"SELECT COUNT(*) c FROM {spec.table} WHERE deleted_at IS NULL "
                f"AND {fk} IS NOT NULL AND TRIM(CAST({fk} AS TEXT)) <> ''").fetchone()["c"]
            pct = round(100.0 * filled / total, 1) if total else 0.0
            rows.append({
                "field": fk,
                "label_en": (spec.field(fk).label_en if spec.field(fk) else fk),
                "label_ar": (spec.field(fk).label_ar if spec.field(fk) else fk),
                "filled": filled, "missing": total - filled,
                "completeness_pct": pct,
                "status": "good" if pct >= 90 else ("fair" if pct >= 60 else "poor"),
            })
        avg = round(sum(r["completeness_pct"] for r in rows) / len(rows), 1) if rows else 0
        summary.append({"label_en": f"{spec.plural_en} completeness",
                        "label_ar": f"اكتمال {spec.plural_ar}", "value": f"{avg}%",
                        "unit": "%"})
        sections.append({
            "id": f"quality_{key}", "type": "table",
            "title_en": f"{spec.plural_en} — critical field completeness ({total} records)",
            "title_ar": f"{spec.plural_ar} — اكتمال الحقول الحرجة ({total} سجل)",
            "columns": [
                {"key": "label_en", "label_en": "Field", "label_ar": "الحقل"},
                {"key": "filled", "label_en": "Filled", "label_ar": "مكتمل"},
                {"key": "missing", "label_en": "Missing", "label_ar": "ناقص"},
                {"key": "completeness_pct", "label_en": "Completeness %", "label_ar": "نسبة الاكتمال"},
                {"key": "status", "label_en": "Rating", "label_ar": "التقييم"},
            ],
            "rows": rows,
        })
    # integrity checks
    integrity = []
    checks = [
        ("Persons without any relationship", """SELECT COUNT(*) c FROM person p
            WHERE p.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM relationship r
            WHERE (r.entity1_type='person' AND r.entity1_id=p.id)
               OR (r.entity2_type='person' AND r.entity2_id=p.id))"""),
        ("Persons without a source", """SELECT COUNT(*) c FROM person
            WHERE deleted_at IS NULL AND primary_source_id IS NULL"""),
        ("Relationships without a source", """SELECT COUNT(*) c FROM relationship
            WHERE deleted_at IS NULL AND source_id IS NULL"""),
        ("Sources never cited", """SELECT COUNT(*) c FROM source s WHERE s.deleted_at IS NULL
            AND NOT EXISTS (SELECT 1 FROM source_link sl WHERE sl.source_id=s.id)
            AND NOT EXISTS (SELECT 1 FROM person p WHERE p.primary_source_id=s.id)
            AND NOT EXISTS (SELECT 1 FROM relationship r WHERE r.source_id=s.id)"""),
        ("Places without coordinates", """SELECT COUNT(*) c FROM place
            WHERE deleted_at IS NULL AND (latitude IS NULL OR longitude IS NULL)"""),
        ("Possible duplicate person names", """SELECT COUNT(*) c FROM (
            SELECT norm(name_ar) n FROM person WHERE deleted_at IS NULL AND name_ar IS NOT NULL
            GROUP BY n HAVING COUNT(*)>1)"""),
        ("Records untouched for 2+ years", """SELECT COUNT(*) c FROM person
            WHERE deleted_at IS NULL AND updated_at < date('now','-2 years')"""),
        ("Records marked disputed", """SELECT COUNT(*) c FROM person p JOIN lookup l
            ON l.id=p.record_status_id WHERE p.deleted_at IS NULL AND l.code='disputed'"""),
    ]
    for label, sql in checks:
        integrity.append({"check": label, "value": conn.execute(sql).fetchone()["c"]})
    sections.append({
        "id": "integrity", "type": "table",
        "title_en": "Integrity checks", "title_ar": "فحوص التكامل",
        "columns": [{"key": "check", "label_en": "Check", "label_ar": "الفحص"},
                    {"key": "value", "label_en": "Records", "label_ar": "عدد السجلات"}],
        "rows": integrity,
    })
    return envelope("quality", "Data quality & completeness audit", "تقرير جودة البيانات والاكتمال",
                    desc_en="Field-level completeness and graph integrity checks.",
                    desc_ar="اكتمال الحقول وفحوص تكامل الشبكة المعرفية.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 3. Institutional network
# ---------------------------------------------------------------------------
def report_institutions(conn, params: dict | None = None) -> dict:
    rows = [dict(r) for r in conn.execute("""
        SELECT i.id, i.code, i.name_en, i.name_ar, i.abbreviation,
               l.label_en AS type_en, l.label_ar AS type_ar,
               c.label_en AS country_en, c.label_ar AS country_ar,
               (SELECT COUNT(*) FROM person p WHERE p.affiliated_institution_id=i.id
                  AND p.deleted_at IS NULL) AS persons,
               (SELECT COUNT(*) FROM person_position pp WHERE pp.institution_id=i.id) AS positions,
               (SELECT COUNT(*) FROM relationship r WHERE r.deleted_at IS NULL AND
                  ((r.entity1_type='institution' AND r.entity1_id=i.id) OR
                   (r.entity2_type='institution' AND r.entity2_id=i.id))) AS relations
        FROM institution i
        LEFT JOIN lookup l ON l.id = i.institution_type_id
        LEFT JOIN lookup c ON c.id = i.country_id
        WHERE i.deleted_at IS NULL
        ORDER BY persons DESC, i.id""")]
    by_type = _labels(conn, "institution_type", [
        (int(r["institution_type_id"]), r["c"]) for r in conn.execute(
            "SELECT institution_type_id, COUNT(*) c FROM institution WHERE deleted_at IS NULL "
            "AND institution_type_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")])
    summary = [
        {"label_en": "Institutions", "label_ar": "المؤسسات", "value": len(rows)},
        {"label_en": "Affiliated persons", "label_ar": "الأشخاص المنتسبون",
         "value": sum(r["persons"] for r in rows)},
        {"label_en": "Recorded positions", "label_ar": "المناصب المسجلة",
         "value": sum(r["positions"] for r in rows)},
        {"label_en": "Institutional links", "label_ar": "الروابط المؤسسية",
         "value": sum(r["relations"] for r in rows)},
    ]
    sections = [
        {"id": "by_type", "type": "pie", "title_en": "Institutions by type",
         "title_ar": "المؤسسات حسب النوع", "rows": by_type,
         "columns": [{"key": "label_en", "label_en": "Type", "label_ar": "النوع"},
                     {"key": "value", "label_en": "Count", "label_ar": "العدد"}]},
        {"id": "table", "type": "table", "title_en": "Institution profile table",
         "title_ar": "جدول بيانات المؤسسات",
         "columns": [
             {"key": "code", "label_en": "ID", "label_ar": "الرقم"},
             {"key": "name_en", "label_en": "Name (EN)", "label_ar": "الاسم (EN)"},
             {"key": "name_ar", "label_en": "Name (AR)", "label_ar": "الاسم (AR)"},
             {"key": "type_en", "label_en": "Type", "label_ar": "النوع"},
             {"key": "country_ar", "label_en": "Country", "label_ar": "البلد"},
             {"key": "persons", "label_en": "Affiliated persons", "label_ar": "الأشخاص"},
             {"key": "positions", "label_en": "Positions", "label_ar": "المناصب"},
             {"key": "relations", "label_en": "Links", "label_ar": "الروابط"},
         ], "rows": rows},
    ]
    return envelope("institutions", "Institutional network report", "تقرير الشبكة المؤسسية",
                    desc_en="Affiliation density and connectivity of each institution.",
                    desc_ar="كثافة الانتساب ودرجة الترابط لكل مؤسسة.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 4. Geographic distribution
# ---------------------------------------------------------------------------
def report_geography(conn, params: dict | None = None) -> dict:
    by_country = [dict(r) for r in conn.execute("""
        SELECT c.code AS code, c.label_en, c.label_ar,
               COUNT(p.id) AS places,
               SUM(CASE WHEN p.latitude IS NOT NULL THEN 1 ELSE 0 END) AS with_coords
        FROM place p JOIN lookup c ON c.id = p.country_id
        WHERE p.deleted_at IS NULL GROUP BY c.id ORDER BY places DESC""")]
    by_region = [dict(r) for r in conn.execute("""
        SELECT COALESCE(g.label_en, p.region, '—') AS region,
               c.label_en AS country_en, c.label_ar AS country_ar, COUNT(*) AS places
        FROM place p
        LEFT JOIN lookup c ON c.id = p.country_id
        LEFT JOIN lookup g ON g.id = p.governorate_id
        WHERE p.deleted_at IS NULL
        GROUP BY c.id, COALESCE(g.label_en, p.region, '—')
        ORDER BY places DESC LIMIT 100""")]
    by_type = _labels(conn, "place_type", [
        (int(r["place_type_id"]), r["c"]) for r in conn.execute(
            "SELECT place_type_id, COUNT(*) c FROM place WHERE deleted_at IS NULL "
            "AND place_type_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")])
    persons_by_country = [dict(r) for r in conn.execute("""
        SELECT c.label_en, c.label_ar, COUNT(*) AS persons
        FROM person p JOIN lookup c ON c.id=p.nationality_id
        WHERE p.deleted_at IS NULL GROUP BY c.id ORDER BY persons DESC LIMIT 50""")]
    summary = [
        {"label_en": "Places", "label_ar": "الأماكن",
         "value": conn.execute("SELECT COUNT(*) c FROM place WHERE deleted_at IS NULL").fetchone()["c"]},
        {"label_en": "Countries with places", "label_ar": "دول ذات أماكن", "value": len(by_country)},
        {"label_en": "Places with coordinates", "label_ar": "أماكن بإحداثيات",
         "value": sum(r["with_coords"] for r in by_country)},
        {"label_en": "Nationalities represented", "label_ar": "جنسيات ممثلة",
         "value": len(persons_by_country)},
    ]
    sections = [
        {"id": "countries", "type": "bar", "title_en": "Places per country",
         "title_ar": "الأماكن حسب البلد",
         "columns": [{"key": "label_en", "label_en": "Country", "label_ar": "البلد"},
                     {"key": "places", "label_en": "Places", "label_ar": "الأماكن"},
                     {"key": "with_coords", "label_en": "With coordinates", "label_ar": "بإحداثيات"}],
         "rows": by_country},
        {"id": "regions", "type": "table", "title_en": "Regional breakdown",
         "title_ar": "التوزيع الإقليمي",
         "columns": [{"key": "region", "label_en": "Region / governorate", "label_ar": "المنطقة/المحافظة"},
                     {"key": "country_ar", "label_en": "Country", "label_ar": "البلد"},
                     {"key": "places", "label_en": "Places", "label_ar": "الأماكن"}],
         "rows": by_region},
        {"id": "types", "type": "pie", "title_en": "Places by type", "title_ar": "الأماكن حسب النوع",
         "columns": [{"key": "label_en", "label_en": "Type", "label_ar": "النوع"},
                     {"key": "value", "label_en": "Count", "label_ar": "العدد"}], "rows": by_type},
        {"id": "persons", "type": "bar", "title_en": "Persons per nationality",
         "title_ar": "الأشخاص حسب الجنسية",
         "columns": [{"key": "label_en", "label_en": "Nationality", "label_ar": "الجنسية"},
                     {"key": "persons", "label_en": "Persons", "label_ar": "الأشخاص"}],
         "rows": persons_by_country},
    ]
    return envelope("geography", "Geographic distribution report", "تقرير التوزيع الجغرافي",
                    desc_en="Where the records are located and how well they are geocoded.",
                    desc_ar="التوزيع المكاني للسجلات ومدى دقة الإحداثيات.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 5. Relationship network
# ---------------------------------------------------------------------------
def report_network(conn, params: dict | None = None) -> dict:
    by_type = [dict(r) for r in conn.execute("""
        SELECT l.label_en, l.label_ar, l.code, COUNT(*) AS links
        FROM relationship r LEFT JOIN lookup l ON l.id=r.relationship_type_id
        WHERE r.deleted_at IS NULL GROUP BY l.id ORDER BY links DESC""")]
    pairs = [dict(r) for r in conn.execute("""
        SELECT entity1_type || ' → ' || entity2_type AS pair, COUNT(*) AS links
        FROM relationship WHERE deleted_at IS NULL GROUP BY pair ORDER BY links DESC""")]
    top = [dict(r) for r in conn.execute("""
        WITH ends AS (
          SELECT entity1_type AS t, entity1_id AS i, entity1_name AS n FROM relationship WHERE deleted_at IS NULL
          UNION ALL
          SELECT entity2_type AS t, entity2_id AS i, entity2_name AS n FROM relationship WHERE deleted_at IS NULL)
        SELECT t AS entity_type, i AS entity_id, MAX(n) AS name, COUNT(*) AS degree
        FROM ends GROUP BY t, i ORDER BY degree DESC LIMIT 25""")]
    summary = [
        {"label_en": "Relationships", "label_ar": "العلاقات",
         "value": conn.execute("SELECT COUNT(*) c FROM relationship WHERE deleted_at IS NULL").fetchone()["c"]},
        {"label_en": "Distinct relationship types", "label_ar": "أنواع العلاقات المستخدمة",
         "value": len(by_type)},
        {"label_en": "Average degree (top 25 nodes)", "label_ar": "متوسط الترابط (أعلى 25 عقدة)",
         "value": round(sum(r["degree"] for r in top) / len(top), 1) if top else 0},
        {"label_en": "Unverified relationships", "label_ar": "علاقات غير موثقة",
         "value": conn.execute("""SELECT COUNT(*) c FROM relationship WHERE deleted_at IS NULL
                                   AND (source_id IS NULL OR authentication_id IS NULL)""").fetchone()["c"]},
    ]
    sections = [
        {"id": "types", "type": "bar", "title_en": "Relationships by type",
         "title_ar": "العلاقات حسب النوع",
         "columns": [{"key": "label_en", "label_en": "Type", "label_ar": "النوع"},
                     {"key": "links", "label_en": "Links", "label_ar": "عدد الروابط"}], "rows": by_type},
        {"id": "pairs", "type": "table", "title_en": "Entity-pair matrix",
         "title_ar": "مصفوفة أزواج الكيانات",
         "columns": [{"key": "pair", "label_en": "Pair", "label_ar": "الزوج"},
                     {"key": "links", "label_en": "Links", "label_ar": "الروابط"}], "rows": pairs},
        {"id": "top", "type": "table", "title_en": "Most connected records",
         "title_ar": "أكثر السجلات ترابطاً",
         "columns": [{"key": "entity_type", "label_en": "Entity", "label_ar": "الكيان"},
                     {"key": "entity_id", "label_en": "ID", "label_ar": "المعرّف"},
                     {"key": "name", "label_en": "Name", "label_ar": "الاسم"},
                     {"key": "degree", "label_en": "Degree", "label_ar": "درجة الترابط"}], "rows": top},
    ]
    return envelope("network", "Relationship network report", "تقرير شبكة العلاقات",
                    desc_en="Typology and connectivity of the knowledge graph.",
                    desc_ar="أنواع الروابط ودرجة الترابط في الشبكة المعرفية.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 6. Timeline
# ---------------------------------------------------------------------------
def report_timeline(conn, params: dict | None = None) -> dict:
    births = [dict(r) for r in conn.execute("""
        SELECT (year_of(birth_date)/10)*10 AS decade, COUNT(*) AS persons
        FROM person WHERE deleted_at IS NULL AND birth_date IS NOT NULL
        GROUP BY decade ORDER BY decade""")]
    deaths = [dict(r) for r in conn.execute("""
        SELECT (year_of(death_date)/10)*10 AS decade, COUNT(*) AS persons
        FROM person WHERE deleted_at IS NULL AND death_date IS NOT NULL
        GROUP BY decade ORDER BY decade""")]
    foundations = [dict(r) for r in conn.execute("""
        SELECT (year_of(founded_date)/10)*10 AS decade, COUNT(*) AS institutions
        FROM institution WHERE deleted_at IS NULL AND founded_date IS NOT NULL
        GROUP BY decade ORDER BY decade""")]
    events = [dict(r) for r in conn.execute("""
        SELECT e.start_date, e.title_en, e.title_ar, l.label_en AS type_en, l.label_ar AS type_ar
        FROM event e LEFT JOIN lookup l ON l.id=e.event_type_id
        WHERE e.deleted_at IS NULL AND e.start_date IS NOT NULL
        ORDER BY year_of(e.start_date)""")]
    summary = [
        {"label_en": "Persons with a birth year", "label_ar": "أشخاص بتاريخ ميلاد",
         "value": sum(r["persons"] for r in births)},
        {"label_en": "Earliest year", "label_ar": "أقدم سنة",
         "value": min([r["decade"] for r in births] or [0])},
        {"label_en": "Institutions dated", "label_ar": "مؤسسات مؤرخة",
         "value": sum(r["institutions"] for r in foundations)},
        {"label_en": "Events", "label_ar": "الأحداث", "value": len(events)},
    ]
    sections = [
        {"id": "births", "type": "timeline", "title_en": "Persons by birth decade",
         "title_ar": "الأشخاص حسب عقد الميلاد",
         "columns": [{"key": "decade", "label_en": "Decade", "label_ar": "العقد"},
                     {"key": "persons", "label_en": "Persons", "label_ar": "العدد"}], "rows": births},
        {"id": "deaths", "type": "timeline", "title_en": "Persons by death decade",
         "title_ar": "الأشخاص حسب عقد الوفاة",
         "columns": [{"key": "decade", "label_en": "Decade", "label_ar": "العقد"},
                     {"key": "persons", "label_en": "Persons", "label_ar": "العدد"}], "rows": deaths},
        {"id": "foundations", "type": "timeline", "title_en": "Institutions founded per decade",
         "title_ar": "المؤسسات المؤسسة حسب العقد",
         "columns": [{"key": "decade", "label_en": "Decade", "label_ar": "العقد"},
                     {"key": "institutions", "label_en": "Institutions", "label_ar": "المؤسسات"}],
         "rows": foundations},
        {"id": "events", "type": "table", "title_en": "Dated events",
         "title_ar": "الأحداث المؤرخة",
         "columns": [{"key": "start_date", "label_en": "Date", "label_ar": "التاريخ"},
                     {"key": "title_en", "label_en": "Event (EN)", "label_ar": "الحدث (EN)"},
                     {"key": "title_ar", "label_en": "Event (AR)", "label_ar": "الحدث (AR)"},
                     {"key": "type_en", "label_en": "Type", "label_ar": "النوع"}], "rows": events},
    ]
    return envelope("timeline", "Chronological report", "التقرير الزمني",
                    desc_en="Decade-level distributions of births, deaths, foundations and events.",
                    desc_ar="توزيعات عشرية للمواليد والوفيات والتأسيس والأحداث.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 7. Sources & evidence
# ---------------------------------------------------------------------------
def report_sources(conn, params: dict | None = None) -> dict:
    usage = [dict(r) for r in conn.execute("""
        SELECT s.code, s.title, s.title_ar, l.label_en AS type_en, l.label_ar AS type_ar,
               rl.label_en AS reliability_en, rl.label_ar AS reliability_ar,
               (SELECT COUNT(*) FROM source_link sl WHERE sl.source_id=s.id) AS citations,
               (SELECT COUNT(*) FROM person p WHERE p.primary_source_id=s.id) AS primary_persons,
               (SELECT COUNT(*) FROM relationship r WHERE r.source_id=s.id) AS relationships
        FROM source s
        LEFT JOIN lookup l ON l.id=s.source_type_id
        LEFT JOIN lookup rl ON rl.id=s.reliability_id
        WHERE s.deleted_at IS NULL ORDER BY citations DESC, s.id""")]
    by_reliability = _labels(conn, "source_reliability", [
        (int(r["reliability_id"]), r["c"]) for r in conn.execute(
            "SELECT reliability_id, COUNT(*) c FROM source WHERE deleted_at IS NULL "
            "AND reliability_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")])
    by_type = _labels(conn, "source_type", [
        (int(r["source_type_id"]), r["c"]) for r in conn.execute(
            "SELECT source_type_id, COUNT(*) c FROM source WHERE deleted_at IS NULL "
            "AND source_type_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")])
    summary = [
        {"label_en": "Sources", "label_ar": "المصادر", "value": len(usage)},
        {"label_en": "Total citations", "label_ar": "مجموع الاستشهادات",
         "value": sum(r["citations"] for r in usage)},
        {"label_en": "Uncited sources", "label_ar": "مصادر غير مستشهد بها",
         "value": sum(1 for r in usage if r["citations"] == 0 and r["primary_persons"] == 0)},
        {"label_en": "Records with a primary source", "label_ar": "سجلات بمصدر أساسي",
         "value": conn.execute("""SELECT COUNT(*) c FROM person WHERE deleted_at IS NULL
                                  AND primary_source_id IS NOT NULL""").fetchone()["c"]},
    ]
    sections = [
        {"id": "reliability", "type": "pie", "title_en": "Sources by reliability",
         "title_ar": "المصادر حسب الموثوقية",
         "columns": [{"key": "label_en", "label_en": "Reliability", "label_ar": "الموثوقية"},
                     {"key": "value", "label_en": "Sources", "label_ar": "العدد"}], "rows": by_reliability},
        {"id": "types", "type": "pie", "title_en": "Sources by type", "title_ar": "المصادر حسب النوع",
         "columns": [{"key": "label_en", "label_en": "Type", "label_ar": "النوع"},
                     {"key": "value", "label_en": "Sources", "label_ar": "العدد"}], "rows": by_type},
        {"id": "usage", "type": "table", "title_en": "Source usage table",
         "title_ar": "جدول استخدام المصادر",
         "columns": [{"key": "code", "label_en": "ID", "label_ar": "الرقم"},
                     {"key": "title", "label_en": "Title", "label_ar": "العنوان"},
                     {"key": "type_en", "label_en": "Type", "label_ar": "النوع"},
                     {"key": "reliability_en", "label_en": "Reliability", "label_ar": "الموثوقية"},
                     {"key": "citations", "label_en": "Citations", "label_ar": "الاستشهادات"},
                     {"key": "primary_persons", "label_en": "Primary for persons", "label_ar": "أساسي لأشخاص"},
                     {"key": "relationships", "label_en": "For relationships", "label_ar": "لعلاقات"}],
         "rows": usage},
    ]
    return envelope("sources", "Sources & evidence report", "تقرير المصادر والأدلة",
                    desc_en="How evidence is distributed and how reliable it is.",
                    desc_ar="توزيع الأدلة ومدى موثوقيتها.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 8. Review workflow / editorial progress
# ---------------------------------------------------------------------------
def report_workflow(conn, params: dict | None = None) -> dict:
    matrix = [dict(r) for r in conn.execute("""
        SELECT p.name_en AS person, p.code,
               COALESCE(rs.label_en,'—') AS status_en, COALESCE(rs.label_ar,'—') AS status_ar,
               COALESCE(al.label_en,'—') AS auth_en, COALESCE(al.label_ar,'—') AS auth_ar,
               p.updated_at
        FROM person p
        LEFT JOIN lookup rs ON rs.id=p.record_status_id
        LEFT JOIN lookup al ON al.id=p.authentication_id
        WHERE p.deleted_at IS NULL ORDER BY p.updated_at DESC LIMIT 200""")]
    by_actor = [dict(r) for r in conn.execute("""
        SELECT COALESCE(actor,'(unknown)') AS actor, COUNT(*) AS actions,
               SUM(CASE WHEN action='create' THEN 1 ELSE 0 END) AS created,
               SUM(CASE WHEN action='update' THEN 1 ELSE 0 END) AS updated,
               SUM(CASE WHEN action='delete' THEN 1 ELSE 0 END) AS deleted
        FROM change_log GROUP BY actor ORDER BY actions DESC""")]
    pending = [dict(r) for r in conn.execute("""
        SELECT 'person' AS entity, COUNT(*) AS c FROM person p JOIN lookup l ON l.id=p.record_status_id
          WHERE p.deleted_at IS NULL AND l.code IN ('draft','in_review','needs_update')
        UNION ALL SELECT 'institution', COUNT(*) FROM institution i JOIN lookup l ON l.id=i.record_status_id
          WHERE i.deleted_at IS NULL AND l.code IN ('draft','in_review','needs_update')
        UNION ALL SELECT 'place', COUNT(*) FROM place pl JOIN lookup l ON l.id=pl.record_status_id
          WHERE pl.deleted_at IS NULL AND l.code IN ('draft','in_review','needs_update')
        UNION ALL SELECT 'relationship', COUNT(*) FROM relationship r JOIN lookup l ON l.id=r.record_status_id
          WHERE r.deleted_at IS NULL AND l.code IN ('draft','in_review','needs_update')""")]
    summary = [
        {"label_en": "Pending review", "label_ar": "بانتظار المراجعة",
         "value": sum(r["c"] for r in pending)},
        {"label_en": "Change-log entries", "label_ar": "قيود سجل التغييرات",
         "value": conn.execute("SELECT COUNT(*) c FROM change_log").fetchone()["c"]},
        {"label_en": "Active contributors", "label_ar": "المساهمون النشطون",
         "value": conn.execute("SELECT COUNT(DISTINCT actor) c FROM change_log").fetchone()["c"]},
        {"label_en": "Import batches", "label_ar": "دفعات الاستيراد",
         "value": conn.execute("SELECT COUNT(*) c FROM import_job").fetchone()["c"]},
    ]
    sections = [
        {"id": "pending", "type": "bar", "title_en": "Records awaiting work",
         "title_ar": "سجلات بحاجة إلى عمل",
         "columns": [{"key": "entity", "label_en": "Entity", "label_ar": "الكيان"},
                     {"key": "c", "label_en": "Records", "label_ar": "العدد"}], "rows": pending},
        {"id": "actors", "type": "table", "title_en": "Activity by contributor",
         "title_ar": "النشاط حسب المساهم",
         "columns": [{"key": "actor", "label_en": "Contributor", "label_ar": "المساهم"},
                     {"key": "actions", "label_en": "Actions", "label_ar": "الإجراءات"},
                     {"key": "created", "label_en": "Created", "label_ar": "إنشاء"},
                     {"key": "updated", "label_en": "Updated", "label_ar": "تحديث"},
                     {"key": "deleted", "label_en": "Deleted", "label_ar": "حذف"}], "rows": by_actor},
        {"id": "recent", "type": "table", "title_en": "Recently updated persons",
         "title_ar": "أحدث الأشخاص تحديثاً",
         "columns": [{"key": "code", "label_en": "ID", "label_ar": "الرقم"},
                     {"key": "person", "label_en": "Name", "label_ar": "الاسم"},
                     {"key": "status_ar", "label_en": "Status", "label_ar": "الحالة"},
                     {"key": "auth_ar", "label_en": "Authentication", "label_ar": "التحقق"},
                     {"key": "updated_at", "label_en": "Updated", "label_ar": "آخر تحديث"}],
         "rows": matrix},
    ]
    return envelope("workflow", "Review & editorial progress", "تقرير سير المراجعة والتحرير",
                    desc_en="Backlog, contributor activity and the latest reviewed records.",
                    desc_ar="المتأخرات ونشاط المساهمين وأحدث السجلات المراجعة.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 9. Indicators (research indicator areas)
# ---------------------------------------------------------------------------
def report_indicators(conn, params: dict | None = None) -> dict:
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()["c"] or 0)

    persons = one("SELECT COUNT(*) c FROM person WHERE deleted_at IS NULL")
    with_rel = one("""SELECT COUNT(*) c FROM person p WHERE p.deleted_at IS NULL AND EXISTS
        (SELECT 1 FROM relationship r WHERE r.deleted_at IS NULL AND
          ((r.entity1_type='person' AND r.entity1_id=p.id) OR (r.entity2_type='person' AND r.entity2_id=p.id)))""")
    sourced = one("SELECT COUNT(*) c FROM person WHERE deleted_at IS NULL AND primary_source_id IS NOT NULL")
    corroborated = one("""SELECT COUNT(*) c FROM person p JOIN lookup l ON l.id=p.authentication_id
        WHERE p.deleted_at IS NULL AND l.code IN ('corroborated','primary_document','institutionally_confirmed')""")
    geocoded = one("SELECT COUNT(*) c FROM place WHERE deleted_at IS NULL AND latitude IS NOT NULL")
    places = one("SELECT COUNT(*) c FROM place WHERE deleted_at IS NULL") or 1
    countries = one("SELECT COUNT(DISTINCT country_id) c FROM place WHERE country_id IS NOT NULL")
    institutions = one("SELECT COUNT(*) c FROM institution WHERE deleted_at IS NULL") or 1
    inst_linked = one("""SELECT COUNT(DISTINCT i.id) c FROM institution i WHERE i.deleted_at IS NULL AND EXISTS
        (SELECT 1 FROM person p WHERE p.affiliated_institution_id=i.id AND p.deleted_at IS NULL)""")
    indicators = [
        {"area": "documentation_quality", "area_en": "Documentation quality",
         "area_ar": "جودة التوثيق",
         "metric_en": "Persons with a primary source", "metric_ar": "أشخاص بمصدر أساسي",
         "value": round(100 * sourced / persons, 1) if persons else 0, "unit": "%"},
        {"area": "documentation_quality", "area_en": "Documentation quality",
         "area_ar": "جودة التوثيق",
         "metric_en": "Persons corroborated by 2+ sources", "metric_ar": "أشخاص معززون بمصدرين",
         "value": round(100 * corroborated / persons, 1) if persons else 0, "unit": "%"},
        {"area": "geographic_coverage", "area_en": "Geographic coverage",
         "area_ar": "التغطية الجغرافية",
         "metric_en": "Places with coordinates", "metric_ar": "أماكن بإحداثيات",
         "value": round(100 * geocoded / places, 1), "unit": "%"},
        {"area": "geographic_coverage", "area_en": "Geographic coverage",
         "area_ar": "التغطية الجغرافية",
         "metric_en": "Countries represented", "metric_ar": "دول ممثلة", "value": countries, "unit": "count"},
        {"area": "partnerships", "area_en": "Partnerships", "area_ar": "الشراكات",
         "metric_en": "Persons with at least one link", "metric_ar": "أشخاص لهم رابط واحد على الأقل",
         "value": round(100 * with_rel / persons, 1) if persons else 0, "unit": "%"},
        {"area": "partnerships", "area_en": "Partnerships", "area_ar": "الشراكات",
         "metric_en": "Institutions with affiliated persons", "metric_ar": "مؤسسات لديها منتسبون",
         "value": round(100 * inst_linked / institutions, 1), "unit": "%"},
        {"area": "archival_coverage", "area_en": "Archival coverage", "area_ar": "التغطية الأرشيفية",
         "metric_en": "Archival sources", "metric_ar": "مصادر أرشيفية",
         "value": one("""SELECT COUNT(*) c FROM source s JOIN lookup l ON l.id=s.source_type_id
                         WHERE s.deleted_at IS NULL AND l.code IN ('archive_document','manuscript','official_register')"""),
         "unit": "count"},
        {"area": "research_output", "area_en": "Research output", "area_ar": "المخرجات البحثية",
         "metric_en": "Total records", "metric_ar": "مجموع السجلات",
         "value": sum(one(f"SELECT COUNT(*) c FROM {s.table} WHERE deleted_at IS NULL")
                      for s in ENTITIES.values()), "unit": "count"},
    ]
    areas = _labels(conn, "indicator_area", [
        (int(r["id"]), 0) for r in conn.execute(
            "SELECT id FROM lookup WHERE domain='indicator_area' ORDER BY sort_order")])
    summary = [{"label_en": i["metric_en"], "label_ar": i["metric_ar"],
                "value": i["value"], "unit": i["unit"]} for i in indicators[:4]]
    sections = [
        {"id": "indicators", "type": "table", "title_en": "Indicator table",
         "title_ar": "جدول المؤشرات",
         "columns": [{"key": "area_en", "label_en": "Indicator area", "label_ar": "مجال المؤشر"},
                     {"key": "metric_en", "label_en": "Metric", "label_ar": "المؤشر"},
                     {"key": "value", "label_en": "Value", "label_ar": "القيمة"},
                     {"key": "unit", "label_en": "Unit", "label_ar": "الوحدة"}], "rows": indicators},
        {"id": "areas", "type": "table", "title_en": "Indicator areas in use",
         "title_ar": "مجالات المؤشرات المستخدمة",
         "columns": [{"key": "label_en", "label_en": "Area", "label_ar": "المجال"},
                     {"key": "label_ar", "label_en": "Arabic label", "label_ar": "التسمية العربية"}],
         "rows": areas},
    ]
    return envelope("indicators", "Indicator report", "تقرير المؤشرات",
                    desc_en="Coverage and quality indicators mapped to research indicator areas.",
                    desc_ar="مؤشرات التغطية والجودة مرتبطة بمجالات المؤشرات البحثية.",
                    summary=summary, sections=sections, params=params)


# ---------------------------------------------------------------------------
# 10. Generic pivot / custom report
# ---------------------------------------------------------------------------
def report_custom(conn, params: dict) -> dict:
    entity = params.get("entity", "person")
    spec = ENTITIES.get(entity)
    if spec is None:
        raise repo.ValidationError(f"Unknown entity '{entity}'")
    group_by = params.get("group_by") or "record_status_id"
    dmap = derived_map(spec.key)
    if group_by not in {f.key for f in spec.fields} and group_by not in dmap:
        raise repo.ValidationError(f"Cannot group by '{group_by}'")
    metric = params.get("metric", "count")
    field = spec.field(group_by)
    derived_field = dmap.get(group_by)
    group_expr = repo.column_expr(spec, group_by)[0] if derived_field else group_by
    if metric == "count":
        agg = "COUNT(*)"
    elif metric in ("sum", "avg", "min", "max") and field and field.type in ("int", "float"):
        agg = f"{metric.upper()}({group_by})"
    else:
        agg = "COUNT(*)"
    payload = params.get("filters") or {}
    payload["page_size"] = 100000
    where, sql_params, _ = repo.build_where(spec, payload, conn)
    rows = [dict(r) for r in conn.execute(
        f"SELECT ({group_expr}) AS k, {agg} AS v FROM {spec.table} t WHERE {where} "
        f"GROUP BY ({group_expr}) ORDER BY v DESC LIMIT 200", sql_params)]
    lookups = {}
    if derived_field:
        for r in rows:
            r["label_en"] = r["label_ar"] = r["k"] if r["k"] is not None else "(blank)"
    elif field and field.type == "select" and field.domain:
        lookups = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, label_en, label_ar, color FROM lookup WHERE domain=?", (field.domain,))}
        for r in rows:
            lk = lookups.get(r["k"])
            r["label_en"] = lk["label_en"] if lk else "(unset)"
            r["label_ar"] = lk["label_ar"] if lk else "(غير محدد)"
            r["color"] = lk["color"] if lk else "gray"
    else:
        for r in rows:
            r["label_en"] = r["label_ar"] = r["k"] if r["k"] is not None else "(blank)"
    summary = [{"label_en": "Records analysed", "label_ar": "السجلات المحللة",
                "value": conn.execute(f"SELECT COUNT(*) c FROM {spec.table} t WHERE {where}",
                                      sql_params).fetchone()["c"]},
               {"label_en": "Groups", "label_ar": "المجموعات", "value": len(rows)}]
    sections = [{
        "id": "pivot", "type": params.get("chart", "bar"),
        "title_en": f"{spec.plural_en} grouped by "
                   f"{(derived_field.label_en if derived_field else (field.label_en if field else group_by))}",
        "title_ar": f"{spec.plural_ar} حسب "
                   f"{(derived_field.label_ar if derived_field else (field.label_ar if field else group_by))}",
        "columns": [{"key": "label_en", "label_en": "Group", "label_ar": "المجموعة"},
                    {"key": "v", "label_en": metric.title(), "label_ar": "القيمة"}],
        "rows": rows,
    }]
    return envelope("custom", "Custom pivot report", "تقرير محوري مخصص",
                    desc_en="Ad-hoc grouping of any entity by any field.",
                    desc_ar="تجميع حر لأي كيان حسب أي حقل.",
                    summary=summary, sections=sections, params=params)


REPORTS = {
    "overview": report_overview,
    "quality": report_quality,
    "institutions": report_institutions,
    "geography": report_geography,
    "network": report_network,
    "timeline": report_timeline,
    "sources": report_sources,
    "workflow": report_workflow,
    "indicators": report_indicators,
}


def build(conn, key: str, params: dict | None = None) -> dict:
    params = params or {}
    if key == "custom":
        return report_custom(conn, params)
    fn = REPORTS.get(key)
    if fn is None:
        raise repo.NotFound(f"Unknown report '{key}'")
    return fn(conn, params)


def safe_title(text: str) -> str:
    import re as _re
    clean = _re.sub(r"[\\/*?\[\]:]", "-", str(text)).strip()
    return (clean or "Sheet")[:31]


def report_xlsx(report: dict) -> tuple[bytes, str]:
    """Flatten any report into a multi-sheet workbook (one sheet per section)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    info = wb.active
    info.title = safe_title("Report — التقرير")
    info.append([report["title_en"]])
    info.append([report["title_ar"]])
    info.append([])
    info.append(["Generated at (UTC)", report["generated_at"]])
    for s in report["summary"]:
        info.append([s["label_en"], s["label_ar"], s["value"], s.get("unit") or ""])
    info.append([])
    info.append(["Parameters", json.dumps(report.get("params") or {}, ensure_ascii=False)])
    for r in info.iter_rows(min_row=1, max_row=1):
        for c in r:
            c.font = Font(bold=True, size=14)
    info.column_dimensions["A"].width = 32
    info.column_dimensions["B"].width = 32

    for idx, section in enumerate(report["sections"], start=1):
        ws = wb.create_sheet(safe_title(section["title_en"] or f"Section {idx}"))
        ws.append([c["label_en"] + " / " + c["label_ar"] for c in section.get("columns", [])])
        for row in section.get("rows", []):
            ws.append([row.get(c["key"], "") if isinstance(row.get(c["key"], ""), (int, float, str))
                       else str(row.get(c["key"], "")) for c in section.get("columns", [])])
        fill = PatternFill("solid", fgColor="1E3A5F")
        for c in range(1, max(1, len(section.get("columns", []))) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = fill
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(c)].width = 22
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), f"report-{report['key']}.xlsx"


def report_csv(report: dict) -> tuple[bytes, str]:
    import csv as _csv

    buf = io.StringIO()
    w = _csv.writer(buf, lineterminator="\r\n")
    w.writerow([report["title_en"]])
    w.writerow(["generated_at", report["generated_at"]])
    for section in report["sections"]:
        w.writerow([])
        w.writerow([section["title_en"], section["title_ar"]])
        cols = section.get("columns", [])
        w.writerow([c["label_en"] for c in cols])
        for row in section.get("rows", []):
            w.writerow([row.get(c["key"], "") for c in cols])
    return buf.getvalue().encode("utf-8-sig"), f"report-{report['key']}.csv"


# ---------------------------------------------------------------------------
# 10 · relationship map (graph payload for the visual network view)
# ---------------------------------------------------------------------------
ENTITY_TYPES = ("person", "institution", "place", "event", "source", "relationship")


def _type_names(conn) -> dict[str, tuple[str, str]]:
    from .schemas import ENTITIES
    return {k: (v.plural_en, v.plural_ar) for k, v in ENTITIES.items()}


def relationship_map(conn, params: dict | None = None) -> dict:
    """Graph payload backing the *Relationship map* view.

    Two levels, deliberately kept in one endpoint so the browser can switch
    without a round-trip dance:

    ``mode="types"`` (default)
        The schema-level picture: one node per entity type, one edge per
        (source type → target type) pair — including the structural links that
        are not stored in ``relationship`` (affiliation, place hierarchy,
        citations, positions) when ``include_structural`` is true.  Edge weight
        is the number of stored links, so the diagram is a picture of *this*
        database, not of the data model.

    ``mode="focus"``
        A record-centred neighbourhood: ``entity_type`` + ``record_id`` and a
        ``depth`` of 1–2, returned as real records (id, type, label, degree) and
        the edges between them, ready for a force/radial layout.
    """
    params = params or {}
    mode = str(params.get("mode") or "types").lower()
    include_structural = bool(params.get("include_structural", True))
    names = _type_names(conn)

    def node(key: str, **extra) -> dict:
        en, ar = names.get(key, (key, key))
        return {"id": key, "type": key, "label_en": en, "label_ar": ar, **extra}

    if mode == "network":
        return _network_map(conn, params)
    if mode == "focus":
        return _focus_map(conn, params, node)

    # ---- type-level graph ------------------------------------------------
    counts = {k: int(conn.execute(
        f"SELECT COUNT(*) c FROM {k} WHERE deleted_at IS NULL").fetchone()["c"])
        for k in ENTITY_TYPES}
    nodes = [node(k, count=counts[k]) for k in ENTITY_TYPES]

    edges: list[dict] = []
    rows = conn.execute("""
        SELECT r.entity1_type AS a, r.entity2_type AS b,
               COALESCE(l.code,'other') AS code,
               COALESCE(l.label_en, r.entity1_type || '→' || r.entity2_type) AS label_en,
               COALESCE(l.label_ar, l.label_en, r.entity1_type || '→' || r.entity2_type) AS label_ar,
               COUNT(*) AS n
        FROM relationship r LEFT JOIN lookup l ON l.id = r.relationship_type_id
        WHERE r.deleted_at IS NULL
        GROUP BY r.entity1_type, r.entity2_type, l.code
        ORDER BY n DESC""").fetchall()
    for r in rows:
        edges.append({"source": r["a"], "target": r["b"], "type": r["code"],
                      "label_en": r["label_en"], "label_ar": r["label_ar"],
                      "count": int(r["n"]), "kind": "relationship"})

    structural: list[dict] = []
    if include_structural:
        def add(src, dst, code, en, ar, n):
            if n:
                structural.append({"source": src, "target": dst, "type": code,
                                   "label_en": en, "label_ar": ar, "count": int(n),
                                   "kind": "structural"})

        add("person", "institution", "affiliation",
            "declared affiliation", "الانتساب المعلن",
            conn.execute("""SELECT COUNT(*) c FROM person WHERE deleted_at IS NULL
                            AND affiliated_institution_id IS NOT NULL""").fetchone()["c"])
        add("person", "institution", "position",
            "positions held", "المناصب",
            conn.execute("""SELECT COUNT(*) c FROM person_position pp
                            JOIN person p ON p.id=pp.person_id AND p.deleted_at IS NULL
                            WHERE pp.institution_id IS NOT NULL""").fetchone()["c"])
        add("person", "place", "birthplace", "born in", "مكان الميلاد",
            conn.execute("""SELECT COUNT(*) c FROM person WHERE deleted_at IS NULL
                            AND birthplace_id IS NOT NULL""").fetchone()["c"])
        add("institution", "place", "sited", "located in", "الموقع",
            conn.execute("""SELECT COUNT(*) c FROM institution WHERE deleted_at IS NULL
                            AND place_id IS NOT NULL""").fetchone()["c"])
        add("place", "place", "hierarchy", "parent place", "المكان الأعلى",
            conn.execute("""SELECT COUNT(*) c FROM place WHERE deleted_at IS NULL
                            AND parent_place_id IS NOT NULL""").fetchone()["c"])
        add("event", "place", "venue", "held at", "مكان الانعقاد",
            conn.execute("""SELECT COUNT(*) c FROM event WHERE deleted_at IS NULL
                            AND place_id IS NOT NULL""").fetchone()["c"])
        add("source", "source", "citations", "cited by records", "الاستشهادات",
            conn.execute("SELECT COUNT(*) c FROM source_link").fetchone()["c"])
        add("person", "source", "primary_source", "primary source", "المصدر الأساسي",
            conn.execute("""SELECT COUNT(*) c FROM person WHERE deleted_at IS NULL
                            AND primary_source_id IS NOT NULL""").fetchone()["c"])
        edges += structural

    # Adjacency matrix for the heat-map table (relationship rows only).
    # Relationships are stored with a direction (who is teacher, who is student)
    # but they are *read* as an undirected connection — the detail page shows the
    # link on both records — so the matrix is filled symmetrically.  A directed
    # matrix would report "institutions → persons: 0" next to
    # "persons → institutions: 18 139", which reads as "nothing connects them".
    matrix = {a: {b: 0 for b in ENTITY_TYPES} for a in ENTITY_TYPES}
    for e in edges:
        matrix[e["source"]][e["target"]] += e["count"]
        if e["target"] != e["source"]:
            matrix[e["target"]][e["source"]] += e["count"]

    type_rows = conn.execute("""
        SELECT COALESCE(l.code,'other') AS code, l.label_en, l.label_ar, l.color,
               COUNT(*) AS n
        FROM relationship r LEFT JOIN lookup l ON l.id = r.relationship_type_id
        WHERE r.deleted_at IS NULL GROUP BY l.id ORDER BY n DESC""").fetchall()

    return {
        "mode": "types",
        "nodes": nodes,
        "edges": edges,
        "matrix": matrix,
        "matrix_order": list(ENTITY_TYPES),
        "matrix_undirected": True,
        "relationship_types": [dict(r) for r in type_rows],
        "totals": {
            "records": sum(counts.values()),
            "relationships": int(conn.execute(
                "SELECT COUNT(*) c FROM relationship WHERE deleted_at IS NULL").fetchone()["c"]),
            "structural_links": sum(e["count"] for e in structural),
            "distinct_types": len(type_rows),
        },
    }


def _focus_map(conn, params: dict, node) -> dict:
    """Neighbourhood graph around one record (depth 1 or 2)."""
    etype = str(params.get("entity_type") or "person")
    rid = int(params.get("record_id") or 0)
    depth = max(1, min(2, int(params.get("depth") or 1)))
    limit = max(5, min(120, int(params.get("limit") or 40)))
    from .schemas import ENTITIES, REF_TITLE_SQL

    if etype not in ENTITIES or not rid:
        return {"mode": "focus", "nodes": [], "edges": [],
                "error": "entity_type and record_id are required"}

    def title_of(t: str, i: int) -> str | None:
        table = ENTITIES[t].table
        expr = REF_TITLE_SQL.get(t, "code")
        row = conn.execute(f"SELECT {expr} AS t FROM {table} WHERE id=?", (i,)).fetchone()
        return row["t"] if row else None

    seen: dict[tuple[str, int], dict] = {}
    edges: list[dict] = []
    frontier = [(etype, rid)]

    def touch(t: str, i: int) -> dict:
        key = (t, i)
        if key not in seen:
            en, ar = ENTITIES[t].plural_en, ENTITIES[t].plural_ar
            seen[key] = {"id": f"{t}:{i}", "type": t, "record_id": i,
                         "label": title_of(t, i) or f"{t} #{i}",
                         "label_en": en, "label_ar": ar, "degree": 0}
        return seen[key]

    touch(etype, rid)
    for _ in range(depth):
        nxt: list[tuple[str, int]] = []
        for t, i in frontier:
            rows = conn.execute("""
                SELECT r.id, r.entity1_type, r.entity1_id, r.entity2_type, r.entity2_id,
                       r.direction, r.start_date, r.end_date,
                       COALESCE(l.code,'other') AS code, l.label_en, l.label_ar, l.id AS type_id,
                       COALESCE(la.code,'unverified') AS auth_code,
                       COALESCE(la.label_en,'Unverified') AS auth_en,
                       COALESCE(la.label_ar, la.label_en, 'غير موثق') AS auth_ar,
                       s.title AS source_name,
                       (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id) AS evidence_count,
                       (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id
                          AND e.support_type = 'contradicts') AS contradicts
                FROM relationship r
                LEFT JOIN lookup l ON l.id = r.relationship_type_id
                LEFT JOIN lookup la ON la.id = r.authentication_id
                LEFT JOIN source s ON s.id = r.source_id
                WHERE r.deleted_at IS NULL
                  AND ((r.entity1_type=? AND r.entity1_id=?) OR
                       (r.entity2_type=? AND r.entity2_id=?))
                LIMIT ?""", (t, i, t, i, limit)).fetchall()
            for r in rows:
                a = (r["entity1_type"], r["entity1_id"])
                b = (r["entity2_type"], r["entity2_id"])
                na, nb = touch(*a), touch(*b)
                na["degree"] += 1
                nb["degree"] += 1
                edges.append({
                    "id": r["id"], "record_id": r["id"],
                    "source": na["id"], "target": nb["id"],
                    "type": r["code"], "label_en": r["label_en"],
                    "label_ar": r["label_ar"], "count": 1,
                    "kind": "relationship",
                    # the visual grammar: direction, verification, and whether the
                    # relationship has ended are properties of the *row*, not of
                    # how the drawing happens to place it
                    "directed": (r["direction"] or "directed") != "symmetric",
                    "verification": r["auth_code"] or "unverified",
                    "verification_en": r["auth_en"] or "Unverified",
                    "verification_ar": r["auth_ar"] or "غير موثق",
                    "ended": bool(r["end_date"]),
                    "start_date": r["start_date"], "end_date": r["end_date"],
                    "source_name": r["source_name"],
                    "evidence_count": int(r["evidence_count"] or 0),
                    "contradicted": bool(r["contradicts"]),
                })
                for cand in (a, b):
                    if cand not in ((t, i),):
                        nxt.append(cand)
        frontier = nxt[:limit]
        if not frontier:
            break

    if len(seen) > limit + 1:                      # keep the picture readable
        keep = {f"{etype}:{rid}"}
        ranked = sorted(seen.values(), key=lambda n: -n["degree"])
        for n in ranked:
            if len(keep) >= limit + 1:
                break
            keep.add(n["id"])
        edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
        seen = {k: v for k, v in seen.items() if f"{k[0]}:{k[1]}" in keep}

    return {"mode": "focus", "nodes": list(seen.values()), "edges": edges,
            "focus": f"{etype}:{rid}", "depth": depth}


# People and organizations (and any other chosen types) as one graph.
# A node is a record. An edge is a stored relationship, or a structural
# affiliation/position when no relationship row already joins that pair.
_NETWORK_TYPES = ("person", "institution", "place", "event", "source")
_NETWORK_SQL = {
    "person": "SELECT id, code, name_en, name_ar FROM person WHERE deleted_at IS NULL",
    "institution": "SELECT id, code, name_en, name_ar FROM institution WHERE deleted_at IS NULL",
    "place": "SELECT id, code, name_en, name_ar FROM place WHERE deleted_at IS NULL",
    "event": """SELECT id, code, title_en AS name_en, title_ar AS name_ar
                FROM event WHERE deleted_at IS NULL""",
    "source": """SELECT id, code, title AS name_en, COALESCE(title_ar, title) AS name_ar
                 FROM source WHERE deleted_at IS NULL""",
}


def _net_match(blob: str, query: str) -> bool:
    """Every token of the query must occur in the folded name."""
    folded_q = db.normalize(query)
    if not folded_q:
        return True
    folded = db.normalize(blob)
    return all(tok in folded for tok in folded_q.split())


def _network_map(conn, params: dict) -> dict:
    """Every record of the chosen types, and the links between them.

    With no search and no pins this is the whole set (capped by degree so a
    large registry stays drawable). A search keeps the matches of that type
    and pulls in the records of the *other* chosen types that they actually
    connect to. Pins are explicit choices: they stay even when the text does
    not match them, and their connections come with them.
    """
    raw = params.get("types")
    if raw is None or raw == "":
        raw = ["person", "institution"]
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.split(",") if p.strip()]
    types = [t for t in raw if t in _NETWORK_TYPES]
    if not types:
        return {"mode": "network", "types": [], "nodes": [], "edges": [],
                "focus": None, "truncated": False, "total_in_types": 0,
                "shown": 0, "narrowed": False}
    limit = max(20, min(400, int(params.get("limit") or 320)))
    neighbor_cap = max(0, min(220, int(params.get("neighbor_cap") or 180)))

    pins: set[tuple[str, int]] = set()
    for item in params.get("pins") or []:
        t, i = "", ""
        if isinstance(item, str) and ":" in item:
            t, _, i = item.partition(":")
        elif isinstance(item, dict):
            t, i = str(item.get("type") or ""), str(item.get("id") or "")
        if t in types and str(i).isdigit():
            pins.add((t, int(i)))

    queries = {
        "person": str(params.get("q_person") or "").strip(),
        "institution": str(params.get("q_institution") or "").strip(),
    }
    other_q = str(params.get("q") or "").strip()

    def type_query(t: str) -> str:
        if t in ("person", "institution"):
            return queries.get(t) or ""
        return other_q

    catalog: dict[tuple[str, int], dict] = {}
    for t in types:
        for row in conn.execute(_NETWORK_SQL[t]):
            name_en = (row["name_en"] or "").strip()
            name_ar = (row["name_ar"] or "").strip()
            code = (row["code"] or "").strip()
            en = name_en or name_ar or code
            ar = name_ar or name_en or code
            catalog[(t, int(row["id"]))] = {
                "id": f"{t}:{row['id']}",
                "type": t,
                "record_id": int(row["id"]),
                "name_en": en,
                "name_ar": ar,
                "label": en or ar or f"{t} #{row['id']}",
                "label_en": en,
                "label_ar": ar,
                "code": code,
                "degree": 0,
                "pinned": (t, int(row["id"])) in pins,
            }
    by_id = {n["id"]: n for n in catalog.values()}

    narrowing = bool(pins) or any(type_query(t) for t in types)
    primary: list[dict] = []
    pool_ids: set[str] = set()
    for n in catalog.values():
        q = type_query(n["type"])
        if n["pinned"] or not narrowing:
            primary.append(n)
            continue
        if q:
            blob = f"{n['name_en']} {n['name_ar']} {n['code']}"
            if _net_match(blob, q):
                primary.append(n)
            continue
        pool_ids.add(n["id"])

    ph = ",".join("?" * len(types))
    edge_rows = conn.execute(f"""
        SELECT r.id, r.entity1_type, r.entity1_id, r.entity2_type, r.entity2_id,
               r.direction, r.start_date, r.end_date,
               COALESCE(l.code,'other') AS code, l.label_en, l.label_ar,
               COALESCE(la.code,'unverified') AS auth_code,
               COALESCE(la.label_en,'Unverified') AS auth_en,
               COALESCE(la.label_ar, la.label_en, 'غير موثق') AS auth_ar,
               s.title AS source_name,
               (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id) AS evidence_count,
               (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id
                  AND e.support_type = 'contradicts') AS contradicts
        FROM relationship r
        LEFT JOIN lookup l ON l.id = r.relationship_type_id
        LEFT JOIN lookup la ON la.id = r.authentication_id
        LEFT JOIN source s ON s.id = r.source_id
        WHERE r.deleted_at IS NULL
          AND r.entity1_type IN ({ph})
          AND r.entity2_type IN ({ph})
    """, (*types, *types)).fetchall()

    edges: list[dict] = []
    linked: set[frozenset] = set()
    for r in edge_rows:
        a = catalog.get((r["entity1_type"], r["entity1_id"]))
        b = catalog.get((r["entity2_type"], r["entity2_id"]))
        if not a or not b or a["id"] == b["id"]:
            continue
        linked.add(frozenset((a["id"], b["id"])))
        edges.append({
            "id": r["id"], "record_id": r["id"],
            "source": a["id"], "target": b["id"],
            "type": r["code"], "label_en": r["label_en"], "label_ar": r["label_ar"],
            "count": 1, "kind": "relationship",
            "directed": (r["direction"] or "directed") != "symmetric",
            "verification": r["auth_code"] or "unverified",
            "verification_en": r["auth_en"] or "Unverified",
            "verification_ar": r["auth_ar"] or "غير موثق",
            "ended": bool(r["end_date"]),
            "start_date": r["start_date"], "end_date": r["end_date"],
            "source_name": r["source_name"],
            "evidence_count": int(r["evidence_count"] or 0),
            "contradicted": bool(r["contradicts"]),
        })

    if "person" in types and "institution" in types:
        def add_struct(pid: int, iid: int, eid: str, code: str, en: str, ar: str, ended: bool):
            a, b = f"person:{pid}", f"institution:{iid}"
            if a not in by_id or b not in by_id:
                return
            if frozenset((a, b)) in linked:
                return
            linked.add(frozenset((a, b)))
            edges.append({
                "id": eid, "record_id": None,
                "source": a, "target": b,
                "type": code, "label_en": en, "label_ar": ar,
                "count": 1, "kind": "structural",
                "directed": True,
                "verification": "institutionally_confirmed",
                "verification_en": "Institutionally confirmed",
                "verification_ar": "مؤكد مؤسسياً",
                "ended": ended, "evidence_count": 0, "contradicted": False,
            })

        for row in conn.execute("""
            SELECT id, affiliated_institution_id AS iid FROM person
            WHERE deleted_at IS NULL AND affiliated_institution_id IS NOT NULL"""):
            add_struct(row["id"], row["iid"], f"struct:affil:{row['id']}",
                       "affiliation", "Declared affiliation", "الانتساب المعلن", False)
        for row in conn.execute("""
            SELECT pp.person_id, pp.institution_id, pp.title_en, pp.title_ar, pp.end_date
            FROM person_position pp
            JOIN person p ON p.id = pp.person_id AND p.deleted_at IS NULL
            JOIN institution i ON i.id = pp.institution_id AND i.deleted_at IS NULL
            WHERE pp.institution_id IS NOT NULL"""):
            add_struct(row["person_id"], row["institution_id"],
                       f"struct:post:{row['person_id']}:{row['institution_id']}",
                       "position",
                       (row["title_en"] or "Position"),
                       (row["title_ar"] or "منصب"),
                       bool(row["end_date"]))

    for e in edges:
        by_id[e["source"]]["degree"] += 1
        by_id[e["target"]]["degree"] += 1

    primary_ids = {n["id"] for n in primary}
    visible = list(primary)
    if narrowing and pool_ids and primary_ids:
        extra: dict[str, dict] = {}
        for e in edges:
            s_in, t_in = e["source"] in primary_ids, e["target"] in primary_ids
            other = e["target"] if s_in and not t_in else (e["source"] if t_in and not s_in else None)
            if other and other in pool_ids and other not in extra:
                extra[other] = by_id[other]
        ranked = sorted(extra.values(), key=lambda n: -n["degree"])
        visible.extend(ranked[:neighbor_cap])

    total = len(catalog)
    truncated = len(visible) > limit
    if truncated:
        pinned_nodes = [n for n in visible if n["pinned"]]
        rest = sorted((n for n in visible if not n["pinned"]), key=lambda n: -n["degree"])
        visible = pinned_nodes + rest[:max(0, limit - len(pinned_nodes))]

    vis = {n["id"] for n in visible}
    edges = [e for e in edges if e["source"] in vis and e["target"] in vis]
    for n in visible:
        n["degree"] = 0
    for e in edges:
        by_id[e["source"]]["degree"] += 1
        by_id[e["target"]]["degree"] += 1

    return {
        "mode": "network",
        "types": types,
        "nodes": visible,
        "edges": edges,
        "focus": None,
        "truncated": truncated,
        "total_in_types": total,
        "shown": len(visible),
        "narrowed": narrowing,
    }

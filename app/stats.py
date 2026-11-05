"""Control-panel statistics (dashboard payload)."""
from __future__ import annotations

import sqlite3

from . import db
from .schemas import ENTITIES


def dashboard(conn: sqlite3.Connection) -> dict:
    def one(sql: str, params: tuple = ()) -> int:
        return int(conn.execute(sql, params).fetchone()["c"] or 0)

    cards = []
    for key, spec in ENTITIES.items():
        total = one(f"SELECT COUNT(*) c FROM {spec.table} WHERE deleted_at IS NULL")
        new_30 = one(f"""SELECT COUNT(*) c FROM {spec.table}
                         WHERE deleted_at IS NULL AND created_at >= datetime('now','-30 days')""")
        updated_30 = one(f"""SELECT COUNT(*) c FROM {spec.table}
                             WHERE deleted_at IS NULL AND updated_at >= datetime('now','-30 days')""")
        cards.append({"key": key, "label_en": spec.plural_en, "label_ar": spec.plural_ar,
                      "icon": spec.icon, "total": total, "new_30d": new_30,
                      "updated_30d": updated_30,
                      "deleted": one(f"SELECT COUNT(*) c FROM {spec.table} WHERE deleted_at IS NOT NULL")})

    status = [dict(r) for r in conn.execute("""
        SELECT l.id, l.code, l.label_en, l.label_ar, l.color,
               COUNT(x.id) AS n
        FROM lookup l
        LEFT JOIN (
            SELECT id, record_status_id FROM person
            UNION ALL SELECT id, record_status_id FROM institution
            UNION ALL SELECT id, record_status_id FROM place
            UNION ALL SELECT id, record_status_id FROM event
            UNION ALL SELECT id, record_status_id FROM relationship
            UNION ALL SELECT id, record_status_id FROM source
        ) x ON x.record_status_id = l.id
        WHERE l.domain='record_status'
        GROUP BY l.id ORDER BY l.sort_order""")]

    auth = [dict(r) for r in conn.execute("""
        SELECT l.code, l.label_en, l.label_ar, l.color, COUNT(p.id) AS n
        FROM lookup l LEFT JOIN person p ON p.authentication_id=l.id AND p.deleted_at IS NULL
        WHERE l.domain='authentication_level' GROUP BY l.id ORDER BY l.sort_order""")]

    monthly = [dict(r) for r in conn.execute("""
        SELECT substr(changed_at,1,7) AS month,
               SUM(CASE WHEN action='create' THEN 1 ELSE 0 END) AS created,
               SUM(CASE WHEN action='update' THEN 1 ELSE 0 END) AS updated,
               SUM(CASE WHEN action='delete' THEN 1 ELSE 0 END) AS deleted
        FROM change_log GROUP BY month ORDER BY month DESC LIMIT 12""")][::-1]

    top_countries = [dict(r) for r in conn.execute("""
        SELECT c.label_en, c.label_ar, c.code, COUNT(p.id) AS n
        FROM lookup c LEFT JOIN place p ON p.country_id=c.id AND p.deleted_at IS NULL
        WHERE c.domain='country' GROUP BY c.id HAVING n>0 ORDER BY n DESC LIMIT 8""")]

    recent = [dict(r) for r in conn.execute("""
        SELECT cl.id, cl.entity_type, cl.entity_id, cl.entity_code, cl.action,
               cl.field_label, cl.old_value, cl.new_value, cl.actor, cl.changed_at
        FROM change_log cl ORDER BY cl.id DESC LIMIT 15""")]

    relations_by_type = [dict(r) for r in conn.execute("""
        SELECT l.label_en, l.label_ar, l.color, COUNT(r.id) AS n
        FROM lookup l LEFT JOIN relationship r ON r.relationship_type_id=l.id AND r.deleted_at IS NULL
        WHERE l.domain='relationship_type' GROUP BY l.id HAVING n>0 ORDER BY n DESC LIMIT 10""")]

    coverage = {k: one(f"""SELECT COUNT(*) c FROM {ENTITIES[k].table}
                           WHERE deleted_at IS NULL AND primary_source_id IS NOT NULL""")
                for k in ("person", "place", "institution", "event")}
    totals = {c["key"]: c["total"] for c in cards}
    completeness = {k: (round(100 * coverage[k] / totals[k], 1) if totals.get(k) else 0)
                    for k in coverage}

    return {
        "generated_at": db.now(),
        "cards": cards,
        "status_distribution": status,
        "authentication_distribution": auth,
        "monthly_activity": monthly,
        "top_countries": top_countries,
        "relationship_types": relations_by_type,
        "recent_changes": recent,
        "coverage": completeness,
        "totals": {
            "records": sum(totals.values()),
            "change_log": one("SELECT COUNT(*) c FROM change_log"),
            "open_imports": one("SELECT COUNT(*) c FROM import_job"),
            "saved_views": one("SELECT COUNT(*) c FROM saved_view"),
            "active_users": one("SELECT COUNT(*) c FROM app_user WHERE is_active=1"),
            "duplicates_watch": one("""SELECT COUNT(*) c FROM (
                SELECT norm(name_ar) n FROM person WHERE deleted_at IS NULL AND name_ar IS NOT NULL
                GROUP BY n HAVING COUNT(*)>1)"""),
        },
    }

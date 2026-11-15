"""
Reference data (vocabularies, locales, users, numbering rules) and an optional
demo dataset.  Everything here is idempotent: re-running is safe.

The demo records are SYNTHETIC examples created to exercise the interface.
They are not a source of historical fact.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import db, geo_chain, settings

_RESOURCES = Path(__file__).resolve().parent / "resources"


def _load_json(name: str):
    path = _RESOURCES / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run: python scripts/build_geo_ref.py")
    return json.loads(path.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# vocabulary domains
# ---------------------------------------------------------------------------
DOMAINS: list[tuple[str, str, str, str]] = [
    # domain, label_en, label_ar, sort
    ("record_status", "Record status", "حالة السجل", 10),
    ("authentication_level", "Authentication level", "مستوى التحقق", 20),
    ("documentation_level", "Documentation level", "مستوى التوثيق", 30),
    ("entity_type", "Entity type", "نوع الكيان", 40),
    ("country", "Country", "البلد", 50),
    ("governorate", "Governorates / provinces", "المحافظات / الأقاليم", 52),
    ("district", "Districts / regions", "الأقضية / المناطق", 54),
    ("municipality", "Municipalities", "البلديات", 56),
    ("village", "Neighborhoods & villages", "الأحياء والقرى", 58),
    ("community", "Communities / clusters", "التجمعات السكانية", 61),
    ("person_classification", "Person classification", "تصنيف الأشخاص", 60),
    ("person_status", "Person status", "حالة الشخص", 65),
    ("place_type", "Place types", "أنواع الأماكن", 70),
    ("institution_type", "Institutional types", "أنواع المؤسسات", 80),
    ("institution_subcategory", "Institutional subcategories", "التصنيفات الفرعية للمؤسسات", 85),
    ("relationship_type", "Relationship types", "أنواع العلاقات", 90),
    ("relation_direction", "Relationship direction", "اتجاه العلاقة", 95),
    ("source_type", "Source types", "أنواع المصادر", 100),
    ("source_reliability", "Source reliability", "موثوقية المصادر", 110),
    ("external_party_type", "External party types", "أنواع الأطراف الخارجية", 120),
    ("event_type", "Event types", "أنواع الأحداث", 130),
    ("governance_system", "Governance systems", "أنظمة الحوكمة", 140),
    ("indicator_area", "Indicator areas", "مجالات المؤشرات", 150),
    ("date_precision", "Date precision", "دقة التواريخ", 160),
    ("geo_precision", "Coordinate precision", "دقة الإحداثيات", 170),
    ("geocoding_method", "Geocoding method", "طريقة تحديد الإحداثيات", 175),
    ("language", "Languages", "اللغات", 180),
]

# domain, code, label_en, label_ar, sort, (meta dict | None), color
V: dict[str, list[tuple]] = {
    "record_status": [
        ("draft", "Draft", "مسودة", 10, None, "gray"),
        ("in_review", "In review", "قيد المراجعة", 20, None, "amber"),
        ("verified", "Verified", "موثّق", 30, None, "blue"),
        ("published", "Published", "منشور", 40, None, "green"),
        ("needs_update", "Needs update", "بحاجة إلى تحديث", 50, None, "orange"),
        ("disputed", "Disputed", "محل خلاف", 60, None, "red"),
        ("archived", "Archived", "مؤرشف", 70, None, "slate"),
        ("rejected", "Rejected", "مرفوض", 80, None, "rose"),
    ],
    "authentication_level": [
        ("unverified", "Unverified", "غير موثّق", 10, None, "gray"),
        ("self_declared", "Self-declared", "إقرار ذاتي", 20, None, "amber"),
        ("single_source", "Single source", "مصدر واحد", 30, None, "blue"),
        ("corroborated", "Corroborated (2+ sources)", "مُعزَّز بمصدرين أو أكثر", 40, None, "green"),
        ("primary_document", "Primary document verified", "موثّق بوثيقة أولية", 50, None, "teal"),
        ("institutionally_confirmed", "Institutionally confirmed", "مؤكد مؤسسياً", 60, None, "indigo"),
    ],
    "documentation_level": [
        ("none", "Not documented", "غير موثّق", 10, None, "gray"),
        ("minimal", "Minimal", "حد أدنى", 20, None, "amber"),
        ("partial", "Partial", "جزئي", 30, None, "blue"),
        ("substantial", "Substantial", "وافٍ", 40, None, "green"),
        ("exhaustive", "Exhaustive", "شامل", 50, None, "teal"),
    ],
    "entity_type": [
        ("person", "Person", "شخص", 10, None, "indigo"),
        ("institution", "Institution", "مؤسسة", 20, None, "teal"),
        ("place", "Place", "مكان", 30, None, "green"),
        ("event", "Event", "حدث", 40, None, "amber"),
        ("relationship", "Relationship", "علاقة", 50, None, "violet"),
        ("source", "Source", "مصدر", 60, None, "slate"),
    ],
    "person_status": [
        ("active", "Active", "نشط", 10, None, "green"),
        ("retired", "Retired", "متقاعد", 20, None, "amber"),
        ("deceased", "Deceased", "متوفى", 30, None, "slate"),
        ("missing", "Whereabouts unknown", "مجهول المصير", 40, None, "orange"),
        ("unknown", "Unknown", "غير معروف", 50, None, "gray"),
    ],
    "person_classification": [
        ("researcher", "Researcher", "باحث", 10, None, "indigo"),
        ("professor", "Professor", "أستاذ جامعي", 20, None, "indigo"),
        ("historian", "Historian", "مؤرخ", 30, None, "indigo"),
        ("religious_scholar", "Religious scholar", "عالم ديني", 40, None, "teal"),
        ("writer", "Writer / author", "كاتب", 50, None, "teal"),
        ("translator", "Translator", "مترجم", 60, None, "teal"),
        ("journalist", "Journalist", "صحفي", 70, None, "amber"),
        ("official", "Government official", "مسؤول حكومي", 80, None, "amber"),
        ("politician", "Politician", "سياسي", 90, None, "amber"),
        ("librarian", "Librarian", "أمين مكتبة", 100, None, "blue"),
        ("archivist", "Archivist", "أرشيفي", 110, None, "blue"),
        ("administrator", "Institutional administrator", "إداري مؤسسي", 120, None, "blue"),
        ("student", "Student", "طالب", 130, None, "gray"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "place_type": [
        ("country", "Country", "بلد", 10, None, "slate"),
        ("region", "Region / governorate", "منطقة / محافظة", 20, None, "green"),
        ("city", "City", "مدينة", 30, None, "green"),
        ("town", "Town", "بلدة", 40, None, "green"),
        ("village", "Village", "قرية", 50, None, "green"),
        ("district", "District", "قضاء", 60, None, "green"),
        ("neighbourhood", "Neighbourhood", "حي", 70, None, "green"),
        ("street", "Street", "شارع", 80, None, "gray"),
        ("square", "Square", "ساحة", 90, None, "gray"),
        ("mosque", "Mosque", "مسجد", 100, None, "teal"),
        ("shrine", "Shrine", "مزار", 110, None, "teal"),
        ("church", "Church", "كنيسة", 120, None, "teal"),
        ("school", "School", "مدرسة", 130, None, "blue"),
        ("library", "Library", "مكتبة", 140, None, "blue"),
        ("archive", "Archive", "أرشيف", 150, None, "blue"),
        ("museum", "Museum", "متحف", 160, None, "blue"),
        ("cemetery", "Cemetery", "مقبرة", 170, None, "slate"),
        ("archaeological_site", "Archaeological site", "موقع أثري", 180, None, "amber"),
        ("building", "Building / institution site", "مبنى / موقع مؤسسة", 190, None, "amber"),
        ("natural_site", "Natural site", "موقع طبيعي", 200, None, "green"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "institution_type": [
        ("university", "University", "جامعة", 10, None, "indigo"),
        ("college", "College / faculty", "كلية", 20, None, "indigo"),
        ("research_center", "Research centre", "مركز بحثي", 30, None, "teal"),
        ("institute", "Institute", "معهد", 40, None, "teal"),
        ("ministry", "Ministry", "وزارة", 50, None, "amber"),
        ("government_body", "Government body", "جهة حكومية", 60, None, "amber"),
        ("library", "Library", "مكتبة", 70, None, "blue"),
        ("archive", "Archive", "أرشيف", 80, None, "blue"),
        ("museum", "Museum", "متحف", 90, None, "blue"),
        ("association", "Association / society", "جمعية", 100, None, "green"),
        ("foundation", "Foundation / endowment", "مؤسسة / وقف", 110, None, "green"),
        ("school", "School", "مدرسة", 120, None, "gray"),
        ("media", "Media organisation", "مؤسسة إعلامية", 130, None, "rose"),
        ("hospital", "Hospital", "مستشفى", 140, None, "rose"),
        ("international_body", "International body", "منظمة دولية", 150, None, "violet"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "institution_subcategory": [
        ("public", "Public / state", "حكومية", 10, None, "amber"),
        ("private", "Private", "خاصة", 20, None, "teal"),
        ("religious", "Religious", "دينية", 30, None, "indigo"),
        ("secular", "Secular", "مدنية", 40, None, "blue"),
        ("ngo", "Non-governmental", "غير حكومية", 50, None, "green"),
        ("international", "International", "دولية", 60, None, "violet"),
        ("military", "Military", "عسكرية", 70, None, "slate"),
        ("mixed", "Mixed", "مختلطة", 80, None, "gray"),
    ],
    "relationship_type": [
        ("student_of", "Student of", "تلميذ لـ", 10, {"inverse": "teacher_of"}, "indigo"),
        ("teacher_of", "Teacher of", "أستاذ لـ", 20, {"inverse": "student_of"}, "indigo"),
        ("supervised_by", "Supervised by", "أشرف عليه", 30, {"inverse": "supervised"}, "indigo"),
        ("supervised", "Supervised", "أشرف على", 40, {"inverse": "supervised_by"}, "indigo"),
        ("colleague_of", "Colleague of", "زميل لـ", 50, {"symmetric": True}, "teal"),
        ("collaborator_of", "Collaborator of", "متعاون مع", 60, {"symmetric": True}, "teal"),
        ("co_author_of", "Co-author with", "مؤلف مشارك مع", 70, {"symmetric": True}, "teal"),
        ("member_of", "Member of", "عضو في", 80, {"inverse": "has_member"}, "green"),
        ("has_member", "Has member", "يضم عضواً", 90, {"inverse": "member_of"}, "green"),
        ("board_member_of", "Board member of", "عضو مجلس إدارة", 100, None, "green"),
        ("director_of", "Director of", "مدير لـ", 110, {"inverse": "directed_by"}, "green"),
        ("directed_by", "Directed by", "يديره", 120, {"inverse": "director_of"}, "green"),
        ("employed_by", "Employed by", "يعمل لدى", 130, {"inverse": "employs"}, "green"),
        ("employs", "Employs", "يوظّف", 140, {"inverse": "employed_by"}, "green"),
        ("affiliated_with", "Affiliated with", "منتسب إلى", 150, None, "green"),
        ("founder_of", "Founder of", "مؤسس لـ", 160, {"inverse": "founded_by"}, "amber"),
        ("founded_by", "Founded by", "أسسه", 170, {"inverse": "founder_of"}, "amber"),
        ("partner_of", "Partner of", "شريك لـ", 180, {"symmetric": True}, "violet"),
        ("succeeded_by", "Succeeded by", "خلفه", 190, {"inverse": "succeeded"}, "slate"),
        ("succeeded", "Succeeded", "خَلَفَ", 200, {"inverse": "succeeded_by"}, "slate"),
        ("located_in", "Located in", "يقع في", 210, {"inverse": "contains"}, "green"),
        ("contains", "Contains", "يضم", 220, {"inverse": "located_in"}, "green"),
        ("graduated_from", "Graduated from", "تخرج في", 230, None, "indigo"),
        ("endowed", "Endowed / funded", "أوقف / مول", 240, None, "amber"),
        ("corresponded_with", "Corresponded with", "راسل", 250, {"symmetric": True}, "teal"),
        ("relative_of", "Relative of", "قريب لـ", 260, {"symmetric": True}, "slate"),
        ("father_of", "Father of", "والد", 270, {"inverse": "child_of"}, "slate"),
        ("child_of", "Child of", "ابن/ابنة لـ", 280, {"inverse": "father_of"}, "slate"),
        ("rival_of", "Rival of", "منافس لـ", 290, {"symmetric": True}, "rose"),
        ("participated_in", "Participated in", "شارك في", 300, {"inverse": "had_participant"}, "violet"),
        ("had_participant", "Had participant", "شارك فيه", 310, {"inverse": "participated_in"}, "violet"),
        ("cites", "Cites / references", "يستشهد بـ", 320, {"inverse": "cited_by"}, "slate"),
        ("cited_by", "Cited by", "مستشهد به من", 330, {"inverse": "cites"}, "slate"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "relation_direction": [
        ("directed", "Directed", "موجهة", 10, None, "slate"),
        ("symmetric", "Symmetric", "متناظرة", 20, None, "slate"),
    ],
    "source_type": [
        ("book", "Book", "كتاب", 10, None, "indigo"),
        ("journal_article", "Journal article", "مقالة دورية", 20, None, "indigo"),
        ("thesis", "Thesis / dissertation", "أطروحة", 30, None, "indigo"),
        ("archive_document", "Archival document", "وثيقة أرشيفية", 40, None, "amber"),
        ("manuscript", "Manuscript", "مخطوطة", 50, None, "amber"),
        ("official_register", "Official register / record", "سجل رسمي", 60, None, "amber"),
        ("interview", "Interview", "مقابلة", 70, None, "teal"),
        ("oral_history", "Oral history", "تاريخ شفوي", 80, None, "teal"),
        ("website", "Website", "موقع إلكتروني", 90, None, "blue"),
        ("social_media", "Social media post", "منشور على منصات التواصل", 100, None, "blue"),
        ("newspaper", "Newspaper article", "مقالة صحفية", 110, None, "rose"),
        ("report", "Report", "تقرير", 120, None, "slate"),
        ("photograph", "Photograph", "صورة", 130, None, "green"),
        ("map", "Map", "خريطة", 140, None, "green"),
        ("database", "Database / dataset", "قاعدة بيانات", 150, None, "violet"),
        ("encyclopedia", "Encyclopaedia entry", "مدخل موسوعي", 160, None, "violet"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "source_reliability": [
        ("high", "High", "عالية", 10, None, "green"),
        ("medium", "Medium", "متوسطة", 20, None, "amber"),
        ("low", "Low", "منخفضة", 30, None, "orange"),
        ("unverified", "Unverified", "لم يتم التحقق", 40, None, "gray"),
        ("primary_contemporary", "Primary contemporary", "أولية معاصرة", 50, None, "teal"),
        ("secondary", "Secondary", "ثانوية", 60, None, "blue"),
    ],
    "external_party_type": [
        ("government", "Government", "حكومة", 10, None, "amber"),
        ("university", "University", "جامعة", 20, None, "indigo"),
        ("foreign_institution", "Foreign institution", "مؤسسة أجنبية", 30, None, "violet"),
        ("ngo", "Non-governmental organisation", "منظمة غير حكومية", 40, None, "green"),
        ("funder", "Funder", "جهة ممولة", 50, None, "teal"),
        ("media", "Media", "إعلام", 60, None, "rose"),
        ("individual", "Individual", "فرد", 70, None, "slate"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "event_type": [
        ("birth", "Birth", "ولادة", 10, None, "green"),
        ("death", "Death", "وفاة", 20, None, "slate"),
        ("founding", "Founding", "تأسيس", 30, None, "amber"),
        ("merger", "Merger", "دمج", 40, None, "amber"),
        ("closure", "Closure", "إغلاق", 50, None, "rose"),
        ("reopening", "Reopening", "إعادة افتتاح", 60, None, "green"),
        ("conference", "Conference", "مؤتمر", 70, None, "violet"),
        ("appointment", "Appointment", "تعيين", 80, None, "blue"),
        ("publication", "Publication", "نشر", 90, None, "indigo"),
        ("migration", "Migration", "هجرة", 100, None, "teal"),
        ("dispute", "Dispute", "نزاع", 110, None, "red"),
        ("celebration", "Celebration", "احتفال", 120, None, "green"),
        ("destruction", "Destruction", "تدمير", 130, None, "red"),
        ("reform", "Reform", "إصلاح", 140, None, "blue"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "governance_system": [
        ("centralized", "Centralised", "مركزية", 10, None, "amber"),
        ("decentralized", "Decentralised", "لامركزية", 20, None, "teal"),
        ("federal", "Federal", "فدرالية", 30, None, "blue"),
        ("waqf_endowment", "Waqf endowment", "وقف", 40, None, "green"),
        ("board_of_trustees", "Board of trustees", "مجلس أمناء", 50, None, "indigo"),
        ("collegial", "Collegial", "جماعية", 60, None, "violet"),
        ("religious_authority", "Religious authority", "مرجعية دينية", 70, None, "teal"),
        ("military", "Military", "عسكرية", 80, None, "slate"),
        ("other", "Other", "أخرى", 999, None, "gray"),
    ],
    "indicator_area": [
        ("research_output", "Research output", "المخرجات البحثية", 10, None, "indigo"),
        ("publications", "Publications", "المنشورات", 20, None, "indigo"),
        ("funding", "Funding", "التمويل", 30, None, "green"),
        ("staffing", "Staffing", "الكوادر", 40, None, "blue"),
        ("infrastructure", "Infrastructure", "البنية التحتية", 50, None, "slate"),
        ("partnerships", "Partnerships", "الشراكات", 60, None, "violet"),
        ("archival_coverage", "Archival coverage", "التغطية الأرشيفية", 70, None, "amber"),
        ("documentation_quality", "Documentation quality", "جودة التوثيق", 80, None, "teal"),
        ("geographic_coverage", "Geographic coverage", "التغطية الجغرافية", 90, None, "green"),
        ("diversity", "Diversity", "التنوع", 100, None, "rose"),
    ],
    "date_precision": [
        ("exact", "Exact (full date)", "دقيق (تاريخ كامل)", 10, None, "green"),
        ("day", "Day", "يوم", 20, None, "green"),
        ("month", "Month", "شهر", 30, None, "blue"),
        ("year", "Year only", "سنة فقط", 40, None, "amber"),
        ("approximate", "Approximate", "تقريبي", 50, None, "orange"),
        ("uncertain", "Uncertain", "غير مؤكد", 60, None, "rose"),
        ("range", "Range", "نطاق زمني", 70, None, "slate"),
        ("unknown", "Unknown", "غير معروف", 80, None, "gray"),
    ],
    "geo_precision": [
        ("exact", "Exact point", "نقطة دقيقة", 10, None, "green"),
        ("approximate", "Approximate", "تقريبية", 20, None, "amber"),
        ("centroid", "Centroid of area", "مركز المنطقة", 30, None, "blue"),
        ("uncertain", "Uncertain", "غير مؤكدة", 40, None, "rose"),
    ],
    "geocoding_method": [
        ("manual", "Point read off a map", "نقطة مقروءة من خريطة", 10, None, "green"),
        ("map_pick", "Point picked on the map", "نقطة محددة على الخريطة", 12, None, "green"),
        ("coordinate_entry", "Coordinates typed in", "إحداثيات مدخلة رقمياً", 14, None, "green"),
        ("gazetteer", "Matched to a gazetteer entry", "مطابقة مع مدخل معجمي", 20, None, "green"),
        ("administrative", "Administrative centroid", "مركز إداري", 30, None, "blue"),
        ("city_centroid", "City point only", "نقطة المدينة فقط", 40, None, "amber"),
        ("geocoder", "Automatic geocoder", "محدِّد إحداثيات آلي", 50, None, "amber"),
        ("historical_map", "Historical map", "خريطة تاريخية", 60, None, "blue"),
        ("inherited", "Inherited from parent place", "موروثة من المكان الأعلى", 70, None, "gray"),
    ],
    "language": [
        ("ar", "Arabic", "العربية", 10, {"dir": "rtl"}, "green"),
        ("en", "English", "الإنجليزية", 20, {"dir": "ltr"}, "blue"),
        ("fr", "French", "الفرنسية", 30, {"dir": "ltr"}, "blue"),
        ("tr", "Turkish", "التركية", 40, {"dir": "ltr"}, "teal"),
        ("fa", "Persian", "الفارسية", 50, {"dir": "rtl"}, "teal"),
        ("ota", "Ottoman Turkish", "التركية العثمانية", 60, {"dir": "rtl"}, "amber"),
        ("de", "German", "الألمانية", 70, {"dir": "ltr"}, "slate"),
        ("ru", "Russian", "الروسية", 80, {"dir": "ltr"}, "slate"),
        ("es", "Spanish", "الإسبانية", 90, {"dir": "ltr"}, "slate"),
        ("it", "Italian", "الإيطالية", 100, {"dir": "ltr"}, "slate"),
        ("he", "Hebrew", "العبرية", 110, {"dir": "rtl"}, "slate"),
        ("ku", "Kurdish", "الكردية", 120, {"dir": "ltr"}, "slate"),
    ],
}

# ---------------------------------------------------------------------------
# countries + governorates/provinces (ISO 3166-1 / 3166-2)
# Built by scripts/build_geo_ref.py → app/resources/{countries,governorates}.json
# ---------------------------------------------------------------------------
def _countries() -> list[dict]:
    return _load_json("countries.json")


def _governorates() -> list[dict]:
    return _load_json("governorates.json")


def _districts() -> list[dict]:
    return _load_json("districts.json")


def _admin_units() -> list[dict]:
    """municipality / village / community rows (resources/admin_units.json)."""
    return _load_json("admin_units.json")


# Stable centre rows from earlier releases: referenced by _OBSOLETE_DIST and
# live place backfills. The full Arab-world set lives in resources/districts.json.
LEGACY_DISTRICTS: list[tuple[str, str, str, str, int]] = [
    # code, governorate_code (ISO 3166-2), label_en, label_ar, sort
    ("IQ-NI-DW", "IQ-NI", "al-Dawwasa", "الدوّاسة", 10),
    ("IQ-BG-RS", "IQ-BG", "Rusafa", "الرصافة", 10),
    ("IQ-BG-KR", "IQ-BG", "Karkh", "الكرخ", 20),
    ("IQ-BA-CT", "IQ-BA", "Basra Centre", "مركز البصرة", 10),
    ("EG-C-CT", "EG-C", "Cairo Centre", "وسط القاهرة", 10),
    ("SY-DI-CT", "SY-DI", "Damascus Centre", "وسط دمشق", 10),
]

LOCALES = [
    ("en", "English", "English", "ltr", 1, 0, 10),
    ("ar", "Arabic", "العربية", "rtl", 1, 1, 20),
    ("fr", "French", "Français", "ltr", 0, 0, 30),
    ("tr", "Turkish", "Türkçe", "ltr", 0, 0, 40),
]

USERS = [
    ("admin", "Registry administrator", "admin@example.org", "admin"),
    ("reviewer", "Lead reviewer", "reviewer@example.org", "reviewer"),
    ("researcher", "Field researcher", "researcher@example.org", "researcher"),
    ("viewer", "Read-only guest", "viewer@example.org", "viewer"),
]

SEQUENCES = [
    ("person", "PER"),
    ("place", "PLC"),
    ("institution", "INS"),
    ("event", "EVT"),
    ("relationship", "REL"),
    ("source", "SRC"),
]

# The settings a fresh database is seeded with.  This is *derived* from the
# registry rather than restated: a second hand-written list would eventually
# disagree with `app/settings.py`, and the disagreement would be invisible
# (the screen would show one default, a new install would store another).
DEFAULT_SETTINGS = settings.defaults()


# Pre-ISO demo codes → current ISO 3166-2 codes (same place, old shorthand).
_OBSOLETE_GOV = {
    "IQ-NJ": "IQ-NA",   # Najaf
    "EG-CA": "EG-C",    # Cairo
    "EG-AX": "EG-ALX",  # Alexandria
    "TR-IS": "TR-34",   # Istanbul
    "TR-AN": "TR-06",   # Ankara
    "LB-BE": "LB-BA",   # Beirut
    "PS-JE": "PS-JEM",  # Jerusalem
    "SA-MK": "SA-02",   # Makkah
    "SA-MD": "SA-03",   # Madinah
    "TN-TU": "TN-11",   # Tunis
    "MA-FM": "MA-03",   # Fès-Meknès
    "SY-AL": "SY-HL",   # Aleppo
}
_OBSOLETE_DIST = {
    "EG-CA-CT": "EG-C-CT",
}


def _retire_obsolete_governorates(conn: sqlite3.Connection) -> None:
    for old, new in _OBSOLETE_GOV.items():
        new_row = conn.execute(
            "SELECT id FROM lookup WHERE domain='governorate' AND code=?", (new,)).fetchone()
        old_row = conn.execute(
            "SELECT id FROM lookup WHERE domain='governorate' AND code=?", (old,)).fetchone()
        if old_row and new_row:
            conn.execute(
                "UPDATE place SET governorate_id=? WHERE governorate_id=?",
                (new_row["id"], old_row["id"]))
            conn.execute(
                "UPDATE lookup SET parent_id=? WHERE domain='district' AND parent_id=?",
                (new_row["id"], old_row["id"]))
        if old_row:
            conn.execute(
                "UPDATE lookup SET is_active=0 WHERE id=?", (old_row["id"],))
    for old, new in _OBSOLETE_DIST.items():
        new_row = conn.execute(
            "SELECT id FROM lookup WHERE domain='district' AND code=?", (new,)).fetchone()
        old_row = conn.execute(
            "SELECT id FROM lookup WHERE domain='district' AND code=?", (old,)).fetchone()
        if old_row and new_row:
            conn.execute(
                "UPDATE place SET district_id=? WHERE district_id=?",
                (new_row["id"], old_row["id"]))
        if old_row:
            conn.execute("UPDATE lookup SET is_active=0 WHERE id=?", (old_row["id"],))


# ---------------------------------------------------------------------------
# Historical dimensions: units that existed, were renamed, merged or dissolved
# stay in the structure with validity bounds and successors (meta), never
# deleted.  Historical names of living units ride as meta.aliases.
# ---------------------------------------------------------------------------
def _flag_emoji(iso2: str) -> str:
    """Regional-indicator flag for a two-letter code — the unit's visual emblem."""
    code = (iso2 or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


# code, label_en, label_ar, meta — rows in the 'country' domain (level 0)
HISTORICAL_UNITS: list[tuple[str, str, str, dict]] = [
    ("SU", "Soviet Union", "الاتحاد السوفيتي",
     {"historical": True, "iso3": "SUN", "valid_from": "1922-12-30", "valid_to": "1991-12-26",
      "successors": ["RU", "UA", "BY", "KZ", "UZ", "TM", "KG", "TJ", "AM", "AZ", "GE", "MD", "LT", "LV", "EE"]}),
    ("YU", "Yugoslavia", "يوغوسلافيا",
     {"historical": True, "iso3": "YUG", "valid_from": "1918-12-01", "valid_to": "2003-02-04",
      "successors": ["SI", "HR", "BA", "RS", "ME", "MK"]}),
    ("CS", "Czechoslovakia", "تشيكوسلوفاكيا",
     {"historical": True, "iso3": "CSK", "valid_from": "1918-10-28", "valid_to": "1992-12-31",
      "successors": ["CZ", "SK"]}),
    ("DD", "German Democratic Republic", "ألمانيا الديمقراطية",
     {"historical": True, "iso3": "DDR", "valid_from": "1949-10-07", "valid_to": "1990-10-03",
      "successors": ["DE"]}),
    ("YD", "People's Democratic Republic of Yemen", "اليمن الديمقراطية",
     {"historical": True, "iso3": "YMD", "valid_from": "1967-11-30", "valid_to": "1990-05-22",
      "successors": ["YE"]}),
    ("NT", "United Arab Republic", "الجمهورية العربية المتحدة",
     {"historical": True, "iso3": "UAR", "valid_from": "1958-02-01", "valid_to": "1971-09-02",
      "successors": ["EG", "SY"]}),
    ("SCG", "Serbia and Montenegro", "صربيا والجبل الأسود",
     {"historical": True, "iso3": "SCG", "valid_from": "2003-02-04", "valid_to": "2006-06-05",
      "successors": ["RS", "ME"]}),
]

# historical names of living units (meta.aliases on the country row)
COUNTRY_ALIASES: dict[str, list[str]] = {
    "IR": ["Persia", "بلاد فارس"],
    "TH": ["Siam", "سيام"],
    "MM": ["Burma", "بورما"],
    "SZ": ["Swaziland", "سوازيلاند"],
    "TL": ["East Timor", "تيمور الشرقية"],
    "CV": ["Cape Verde", "الرأس الأخضر"],
    "CZ": ["Czech Republic", "التشيك"],
    "TR": ["Ottoman Empire successor state", "دولة عثمانية سابقة"],
    "RU": ["Russian Empire", "الإمبراطورية الروسية"],
    "GR": ["Hellas", "اليونان"],
    "NL": ["Holland", "هولندا"],
    "KP": ["Democratic People's Republic of Korea", "كوريا الشعبية"],
    "KR": ["Republic of Korea", "كوريا الجنوبية"],
    "VA": ["Holy See", "الفاتيكان"],
    "BN": ["Brunei Darussalam", "بروناي دار السلام"],
}


def seed_reference_data(conn: sqlite3.Connection) -> None:
    # domains
    for domain, en, ar, order in DOMAINS:
        conn.execute(
            """INSERT OR IGNORE INTO lookup_domain (domain, label_en, label_ar, sort_order, is_system)
               VALUES (?,?,?,?,1)""",
            (domain, en, ar, order),
        )
        conn.execute(
            """UPDATE lookup_domain SET label_en=?, label_ar=?, sort_order=?
               WHERE domain=?""",
            (en, ar, order, domain),
        )
    # values
    for domain, items in V.items():
        for item in items:
            code, label_en, label_ar, order, meta, color = item
            conn.execute(
                """INSERT OR IGNORE INTO lookup (domain, code, label_en, label_ar, sort_order, color, meta, is_system)
                   VALUES (?,?,?,?,?,?,?,1)""",
                (domain, code, label_en, label_ar, order, color,
                 db.json_dump(meta) if meta else None),
            )
    # countries (configurable vocabulary — new rows may be added in Vocabularies)
    for i, c in enumerate(_countries(), start=1):
        meta = {"iso2": c["code"], "iso3": c.get("iso3") or "",
                "region": c.get("region") or "", "flag": _flag_emoji(c["code"])}
        if COUNTRY_ALIASES.get(c["code"]):
            meta["aliases"] = COUNTRY_ALIASES[c["code"]]
        conn.execute(
            """INSERT OR IGNORE INTO lookup (domain, code, label_en, label_ar, sort_order, color, meta, is_system)
               VALUES ('country',?,?,?,?,?,?,0)""",
            (c["code"], c["label_en"], c["label_ar"], i * 10, "green", db.json_dump(meta)))
        conn.execute(
            """UPDATE lookup SET label_en=?, label_ar=?, sort_order=?, meta=?, is_system=0
               WHERE domain='country' AND code=?""",
            (c["label_en"], c["label_ar"], i * 10, db.json_dump(meta), c["code"]))
    conn.execute("UPDATE lookup SET is_system=0 WHERE domain='country'")
    # historical units — dissolved or renamed states keep their place in time
    for i, (hcode, hen, har, hmeta) in enumerate(HISTORICAL_UNITS, start=1):
        conn.execute(
            """INSERT OR IGNORE INTO lookup (domain, code, label_en, label_ar, sort_order, color, meta, is_system)
               VALUES ('country',?,?,?,?,?,?,0)""",
            (hcode, hen, har, 1000 + i * 10, "slate", db.json_dump(hmeta)))
        conn.execute(
            """UPDATE lookup SET label_en=?, label_ar=?, meta=?, is_active=1, is_system=0
               WHERE domain='country' AND code=?""",
            (hen, har, db.json_dump(hmeta), hcode))
    # governorates / provinces → parent country
    for g in _governorates():
        parent = conn.execute(
            "SELECT id FROM lookup WHERE domain='country' AND code=?",
            (g["country"],)).fetchone()
        if not parent:
            continue
        meta = {"type": g.get("type") or "", "aliases": g.get("aliases") or []}
        conn.execute(
            """INSERT OR IGNORE INTO lookup
               (domain, code, label_en, label_ar, parent_id, sort_order, color, meta, is_system)
               VALUES ('governorate',?,?,?,?,?,?,?,0)""",
            (g["code"], g["label_en"], g["label_ar"], parent["id"],
             int(g.get("sort") or 100), "teal", db.json_dump(meta)))
        conn.execute(
            """UPDATE lookup SET parent_id=?, label_en=?, label_ar=?, sort_order=?, meta=?, is_system=0
               WHERE domain='governorate' AND code=?""",
            (parent["id"], g["label_en"], g["label_ar"], int(g.get("sort") or 100),
             db.json_dump(meta), g["code"]))
    # districts → parent governorate (Arab world via resources/districts.json)
    district_rows = LEGACY_DISTRICTS + [
        (d["code"], d["governorate"], d["label_en"], d["label_ar"],
         int(d.get("sort") or 100))
        for d in _districts()
    ]
    for code, gcode, en, ar, order in district_rows:
        parent = conn.execute(
            "SELECT id FROM lookup WHERE domain='governorate' AND code=?", (gcode,)).fetchone()
        if not parent:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO lookup
               (domain, code, label_en, label_ar, parent_id, sort_order, color, is_system)
               VALUES ('district',?,?,?,?,?,?,0)""",
            (code, en, ar, parent["id"], order, "green"))
        conn.execute(
            """UPDATE lookup SET parent_id=?, label_en=?, label_ar=?, sort_order=?, is_system=0
               WHERE domain='district' AND code=?""",
            (parent["id"], en, ar, order, code))
    # municipalities → villages → communities (resources/admin_units.json)
    for u in _admin_units():
        level = u["level"]
        parent_domain = geo_chain.expected_parent(level)
        parent = conn.execute(
            "SELECT id FROM lookup WHERE domain=? AND code=?", (parent_domain, u["parent"])
        ).fetchone()
        if not parent:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO lookup
               (domain, code, label_en, label_ar, parent_id, sort_order, color, is_system)
               VALUES (?,?,?,?,?,?,?,0)""",
            (level, u["code"], u["label_en"], u["label_ar"], parent["id"],
             int(u.get("sort") or 100), "violet"))
        conn.execute(
            """UPDATE lookup SET parent_id=?, label_en=?, label_ar=?, sort_order=?, is_system=0
               WHERE domain=? AND code=?""",
            (parent["id"], u["label_en"], u["label_ar"], int(u.get("sort") or 100),
             level, u["code"]))
    # Retire pre-ISO demo province codes; remount places onto the ISO equivalents.
    _retire_obsolete_governorates(conn)
    # locales / users / sequences / settings
    for code, en, native, direction, active, default, order in LOCALES:
        conn.execute(
            """INSERT OR IGNORE INTO locale (code, name_en, name_native, dir, is_active, is_default, sort_order)
               VALUES (?,?,?,?,?,?,?)""",
            (code, en, native, direction, active, default, order),
        )
    for username, display, email, role in USERS:
        conn.execute(
            """INSERT OR IGNORE INTO app_user (username, display_name, email, role)
               VALUES (?,?,?,?)""", (username, display, email, role))
    for entity_type, prefix in SEQUENCES:
        conn.execute(
            """INSERT OR IGNORE INTO sequence (entity_type, prefix, padding, next_value)
               VALUES (?,?,4,1)""", (entity_type, prefix))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO setting (key, value) VALUES (?,?)", (k, v))
    conn.execute(
        "INSERT OR IGNORE INTO app_meta (key, value) VALUES ('schema_version','1.0.0')")
    conn.execute(
        "INSERT OR IGNORE INTO app_meta (key, value) VALUES ('dataset_title', NULL)")
    conn.commit()


# ---------------------------------------------------------------------------
# demo dataset (synthetic)
# ---------------------------------------------------------------------------
DEMO_SOURCES = [
    ("Biographical register of twentieth-century scholars (demo)", "book",
     "Demo University Press", "1987", "high"),
    ("National archive collection 1940-1975 (demo)", "archive_document",
     "National Archive", "1975", "primary_contemporary"),
    ("University calendar and staff list 1968 (demo)", "official_register",
     "University Press", "1968", "high"),
    ("Interview with a former faculty member (demo)", "interview",
     "Registry team", "2019", "medium"),
    ("Civil society organisations directory (demo)", "report",
     "Development Institute", "2016", "medium"),
    ("Institutional website archive capture (demo)", "website",
     "Web Archive", "2021", "medium"),
    ("Regional history journal, vol. 12 (demo)", "journal_article",
     "Regional History Society", "1998", "high"),
    ("Oral history recording (demo)", "oral_history", "Registry team", "2020", "medium"),
]


def _lid(conn, domain: str, code: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM lookup WHERE domain=? AND code=?", (domain, code)).fetchone()
    return row["id"] if row else None


def _insert(conn, entity: str, data: dict, actor: str = "system") -> int:
    from .schemas import ENTITIES

    data = dict(data)
    code = data.pop("code", None) or db.next_code(conn, entity)
    ts = db.now()
    data.update({"code": code, "created_at": ts, "updated_at": ts,
                 "created_by": actor, "updated_by": actor, "version": 1})
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO {ENTITIES[entity].table} ({cols}) VALUES ({marks})",
                       list(data.values()))
    row_id = int(cur.lastrowid)
    db.log_change(conn, entity_type=entity, entity_id=row_id, action="create",
                  actor=actor, entity_code=code, notes="demo seed")
    return row_id


def seed_demo(conn: sqlite3.Connection) -> None:
    """Create a small synthetic dataset (skipped when records already exist)."""

    if conn.execute("SELECT COUNT(*) c FROM person").fetchone()["c"] > 0:
        return
    L = lambda d, c: _lid(conn, d, c)
    ST = {k: L("record_status", k) for k in
          ("draft", "in_review", "verified", "published", "needs_update")}
    AU = {k: L("authentication_level", k) for k in
          ("unverified", "single_source", "corroborated", "primary_document")}
    DO = {k: L("documentation_level", k) for k in ("minimal", "partial", "substantial", "exhaustive")}
    CN = {k: L("country", k) for k in ("IQ", "EG", "SY", "TR", "JO", "LB", "SA", "TN", "MA", "PS", "KW")}
    NOTE = "Demo record — synthetic data created for interface testing, not a historical claim."

    # ---- sources ---------------------------------------------------------
    src_ids = {}
    for i, (title, stype, publisher, year, rel) in enumerate(DEMO_SOURCES, start=1):
        sid = _insert(conn, "source", {
            "title": title, "source_type_id": L("source_type", stype), "publisher": publisher,
            "publication_date": year, "publication_precision": L("date_precision", "year"),
            "reliability_id": L("source_reliability", rel),
            "record_status_id": ST["verified"], "authentication_id": AU["single_source"],
            "supported_information": "Demo citation supporting the linked record.",
            "researcher_notes": NOTE, "language": "en",
        })
        src_ids[i] = sid
    S1 = src_ids[1]

    # ---- places ----------------------------------------------------------
    places = [
        ("بغداد", "Baghdad", "city", "IQ", "Baghdad", 33.3152, 44.3661),
        ("الموصل", "Mosul", "city", "IQ", "Nineveh", 36.3350, 43.1189),
        ("البصرة", "Basra", "city", "IQ", "Basra", 30.5085, 47.7804),
        ("النجف", "Najaf", "city", "IQ", "Najaf", 32.0000, 44.3333),
        ("كربلاء", "Karbala", "city", "IQ", "Karbala", 32.6167, 44.0333),
        ("أربيل", "Erbil", "city", "IQ", "Erbil", 36.1901, 44.0091),
        ("دمشق", "Damascus", "city", "SY", "Damascus", 33.5138, 36.2765),
        ("حلب", "Aleppo", "city", "SY", "Aleppo", 36.2021, 37.1343),
        ("القاهرة", "Cairo", "city", "EG", "Cairo", 30.0444, 31.2357),
        ("الإسكندرية", "Alexandria", "city", "EG", "Alexandria", 31.2001, 29.9187),
        ("إستنبول", "Istanbul", "city", "TR", "Istanbul", 41.0082, 28.9784),
        ("أنقرة", "Ankara", "city", "TR", "Ankara", 39.9334, 32.8597),
        ("عمّان", "Amman", "city", "JO", "Amman", 31.9454, 35.9284),
        ("بيروت", "Beirut", "city", "LB", "Beirut", 33.8938, 35.5018),
        ("القدس", "Jerusalem", "city", "PS", "Jerusalem", 31.7683, 35.2137),
        ("مكة المكرمة", "Mecca", "city", "SA", "Makkah", 21.4225, 39.8262),
        ("المدينة المنورة", "Medina", "city", "SA", "Madinah", 24.4672, 39.6111),
        ("تونس", "Tunis", "city", "TN", "Tunis", 36.8065, 10.1815),
        ("فاس", "Fez", "city", "MA", "Fez-Meknes", 34.0331, -5.0003),
        ("الموصل - حي الدوّاسة", "Mosul — al-Dawwasa quarter", "neighbourhood", "IQ", "Nineveh",
         36.3400, 43.1300),
    ]
    place_ids = {}
    def _gov(cc, region_en):
        rows = conn.execute(
            """SELECT g.id, g.label_en, g.label_ar, g.meta FROM lookup g
               JOIN lookup c ON c.id = g.parent_id
               WHERE g.domain='governorate' AND c.code=?""",
            (cc,)).fetchall()
        want = (region_en or "").strip().casefold()
        for g in rows:
            names = [g["label_en"] or "", g["label_ar"] or ""]
            meta = db.json_load(g["meta"], {}) or {}
            names.extend(meta.get("aliases") or [])
            if any((n or "").strip().casefold() == want for n in names):
                return g["id"]
            if any(want and want in (n or "").casefold() for n in names):
                return g["id"]
        return None

    for i, (ar, en, ptype, cc, region, lat, lon) in enumerate(places, start=1):
        gid = _gov(cc, region)
        pid = _insert(conn, "place", {
            "name_ar": ar, "name_en": en, "name_original": en, "name_original_lang": "en",
            "place_type_id": L("place_type", ptype), "country_id": CN[cc], "region": region,
            "governorate_id": gid,
            "city": en if ptype in ("city",) else None, "latitude": lat, "longitude": lon,
            "geo_precision": L("geo_precision", "approximate"),
            "geo_description": "Municipal centre used to anchor records in this registry.",
            "research_significance": "Linked to several institutions and scholars in the register.",
            "primary_source_id": S1, "documentation_id": DO["partial"],
            "authentication_id": AU["corroborated"], "record_status_id": ST["verified"],
            "researcher_notes": NOTE,
        })
        place_ids[i] = pid
    P_BAGHDAD, P_MOSUL, P_BASRA, P_NAJAF, P_KARBALA, P_ERBIL = (place_ids[i] for i in range(1, 7))
    conn.execute("UPDATE place SET parent_place_id=? WHERE id=?", (P_MOSUL, place_ids[20]))
    P_DAMASCUS, P_ALEPPO, P_CAIRO, P_ALEX, P_IST, P_ANKARA = (place_ids[i] for i in range(7, 13))
    P_AMMAN, P_BEIRUT, P_QUDUS, P_MAKKAH, P_MADINA, P_TUNIS, P_FEZ, P_MOSUL_Q = (
        place_ids[i] for i in range(13, 21))

    # ---- institutions ----------------------------------------------------
    inst = [
        ("جامعة بغداد", "University of Baghdad", "UoB", "university", "public", "IQ", "Baghdad", 1957, P_BAGHDAD),
        ("كلية الآداب - جامعة بغداد", "College of Arts — University of Baghdad", "CoA", "college",
         "public", "IQ", "Baghdad", 1949, P_BAGHDAD),
        ("المجمع العلمي العراقي", "Iraqi Academy of Sciences", "IAS", "research_center", "public",
         "IQ", "Baghdad", 1947, P_BAGHDAD),
        ("جامعة الموصل", "University of Mosul", "UoM", "university", "public", "IQ", "Mosul", 1967, P_MOSUL),
        ("مكتبة الأوقاف العامة", "Endowments Public Library", "EPL", "library", "religious",
         "IQ", "Baghdad", 1920, P_BAGHDAD),
        ("جامعة دمشق", "University of Damascus", "DU", "university", "public", "SY", "Damascus", 1923, P_DAMASCUS),
        ("جامعة القاهرة", "Cairo University", "CU", "university", "public", "EG", "Cairo", 1908, P_CAIRO),
        ("دار الكتب والوثائق", "National Library and Archives", "NLA", "archive", "public", "EG",
         "Cairo", 1870, P_CAIRO),
        ("جامعة إستنبول", "Istanbul University", "IU", "university", "public", "TR", "Istanbul", 1453, P_IST),
        ("معهد الدراسات الشرقية", "Institute of Oriental Studies", "IOS", "institute", "public",
         "TR", "Istanbul", 1930, P_IST),
        ("الجمعية التاريخية", "Historical Society", "HS", "association", "ngo", "JO", "Amman", 1965, P_AMMAN),
        ("مركز الدراسات الإقليمية", "Centre for Regional Studies", "CRS", "research_center",
         "private", "LB", "Beirut", 1994, P_BEIRUT),
    ]
    inst_ids = {}
    for i, (ar, en, abbr, itype, sub, cc, city, year, pid) in enumerate(inst, start=1):
        iid = _insert(conn, "institution", {
            "name_ar": ar, "name_en": en, "name_original": en, "name_original_lang": "en",
            "abbreviation": abbr, "institution_type_id": L("institution_type", itype),
            "subcategory_id": L("institution_subcategory", sub), "founded_date": str(year),
            "founded_precision": L("date_precision", "year"), "country_id": CN[cc], "city": city,
            "place_id": pid, "address": "Central district (demo address)",
            "objectives": "Teaching, research and documentation (demo statement).",
            "org_structure": "Board / director / departments (demo).",
            "governance_id": L("governance_system",
                               "waqf_endowment" if sub == "religious" else
                               ("board_of_trustees" if sub == "private" else "centralized")),
            "website": "https://example.org/" + abbr.lower(),
            "research_significance": "Recurring node in the institutional network of this register.",
            "primary_source_id": src_ids[3], "documentation_id": DO["substantial"],
            "authentication_id": AU["corroborated"], "record_status_id": ST["published"],
            "researcher_notes": NOTE,
        })
        inst_ids[i] = iid
    I_UOB, I_COA, I_IAS, I_UOM, I_EPL, I_DU, I_CU, I_NLA, I_IU, I_IOS, I_HS, I_CRS = (
        inst_ids[i] for i in range(1, 13))

    # ---- persons ---------------------------------------------------------
    persons = [
        ("أحمد بن سالم الحسيني", "Ahmad b. Salim al-Husayni", "historian", "deceased", "IQ", 1912, 1978, P_MOSUL, I_UOM, 3),
        ("فاطمة عبد الله الراوي", "Fatima Abdallah al-Rawi", "professor", "deceased", "IQ", 1925, 2001, P_BAGHDAD, I_COA, 2),
        ("محمود صالح الجميل", "Mahmud Salih al-Jamil", "researcher", "active", "IQ", 1958, None, P_BAGHDAD, I_IAS, 3),
        ("ليلى حسن العبيدي", "Layla Hasan al-Ubaydi", "librarian", "retired", "IQ", 1950, None, P_BAGHDAD, I_EPL, 2),
        ("يوسف كمال الدين", "Yusuf Kamal al-Din", "archivist", "deceased", "EG", 1908, 1985, P_CAIRO, I_NLA, 4),
        ("سعاد مصطفى فهمي", "Suad Mustafa Fahmi", "professor", "active", "EG", 1962, None, P_CAIRO, I_CU, 3),
        ("عمر بن عبد الرحمن الحلبي", "Umar b. Abd al-Rahman al-Halabi", "religious_scholar",
         "deceased", "SY", 1890, 1964, P_ALEPPO, I_DU, 2),
        ("نور الدين القاسمي", "Nur al-Din al-Qasimi", "writer", "deceased", "SY", 1884, 1954, P_DAMASCUS, I_DU, 9),
        ("إبراهيم توفيق بك", "Ibrahim Tawfiq Bey", "official", "deceased", "TR", 1876, 1949, P_IST, I_IU, 5),
        ("عائشة نور هانم", "Aisha Nur Hanim", "translator", "deceased", "TR", 1901, 1973, P_IST, I_IOS, 6),
        ("خالد سعيد الأعرجي", "Khalid Said al-Araji", "journalist", "active", "IQ", 1971, None, P_NAJAF, None, 7),
        ("هدى ناصر الشمري", "Huda Nasir al-Shammari", "researcher", "active", "IQ", 1980, None, P_BASRA, I_IAS, 8),
        ("سليم بن يوسف المقدسي", "Salim b. Yusuf al-Maqdisi", "historian", "deceased", "PS", 1902, 1971, P_QUDUS, I_HS, 9),
        ("منى سمير الخوري", "Muna Samir al-Khuri", "professor", "active", "LB", 1965, None, P_BEIRUT, I_CRS, 10),
        ("عبد الكريم بن محمد الطنطاوي", "Abd al-Karim b. Muhammad al-Tantawi", "religious_scholar",
         "deceased", "SA", 1889, 1958, P_MAKKAH, None, 11),
        ("زينب علي الوائلي", "Zaynab Ali al-Waili", "student", "active", "IQ", 1995, None, P_KARBALA, I_UOB, 3),
        ("طه حسين البدري", "Taha Husayn al-Badri", "professor", "deceased", "EG", 1899, 1973, P_ALEX, I_CU, 4),
        ("رجاء محمود الغانم", "Raja Mahmud al-Ghanim", "administrator", "retired", "KW", 1955, None, P_BAGHDAD, I_UOB, 2),
        ("حسن بن علي الجبوري", "Hasan b. Ali al-Juburi", "researcher", "active", "IQ", 1977, None, P_ERBIL, I_UOM, 5),
        ("أمينة سعيد الزهراني", "Amina Said al-Zahrani", "writer", "active", "SA", 1983, None, P_MADINA, I_HS, 6),
        ("نبيل فؤاد حداد", "Nabil Fuad Haddad", "translator", "active", "JO", 1969, None, P_AMMAN, I_HS, 2),
        ("سلمى بنت عبد الحميد", "Salma bint Abd al-Hamid", "professor", "deceased", "TN", 1915, 1990, P_TUNIS, None, 7),
        ("محمد العربي العلمي", "Muhammad al-Arabi al-Alami", "historian", "active", "MA", 1952, None, P_FEZ, I_CRS, 8),
        ("جورج يوسف نصر", "George Yusuf Nasr", "researcher", "active", "LB", 1974, None, P_BEIRUT, I_IOS, 9),
    ]
    person_ids = {}
    for i, (ar, en, cls, st, cc, birth, death, pid, iid, src_i) in enumerate(persons, start=1):
        status = "published" if i % 3 else ("verified" if i % 2 else "in_review")
        rec = {
            "name_ar": ar, "name_en": en, "name_original": en, "name_original_lang": "en",
            "category": "civilian",
            "name_transliteration": en.replace("b. ", "bin "),
            "birth_date": str(birth), "birth_precision": L("date_precision", "year"),
            "death_date": str(death) if death else None,
            "death_precision": L("date_precision", "year") if death else None,
            "nationality_id": CN[cc], "birthplace_id": pid, "birthplace_text": None,
            "classification_id": L("person_classification", cls),
            "current_status_id": L("person_status", st),
            "affiliated_institution_id": iid, "affiliated_country_id": CN[cc],
            "current_position": {"professor": "Professor", "researcher": "Senior researcher",
                                 "librarian": "Head librarian", "archivist": "Senior archivist",
                                 "historian": "Historian", "writer": "Author",
                                 "translator": "Translator", "journalist": "Editor",
                                 "official": "Civil servant", "administrator": "Registrar",
                                 "religious_scholar": "Teacher", "student": "PhD candidate"}.get(cls, "—"),
            "declared_affiliation": "Affiliation as declared in the cited source (demo).",
            "affiliation_verified": 1 if status == "published" else 0,
            "affiliation_start": str(birth + 25) if iid else None,
            "public_activity": "Public lectures and publications (demo).",
            "institutional_relations": "See structured relationships.",
            "website": None, "social_accounts": None,
            "primary_source_id": src_ids.get(src_i, S1),
            "documentation_id": DO["partial"], "authentication_id": AU["corroborated"],
            "record_status_id": ST[status], "researcher_notes": NOTE,
        }
        person_ids[i] = _insert(conn, "person", rec)

    # ---- positions (previous positions) ---------------------------------
    pos_rows = [
        (1, "مدرس", "Teacher", I_UOM, "1940", "1955"),
        (1, "عميد كلية الآداب", "Dean of the College of Arts", I_UOM, "1955", "1978"),
        (2, "أستاذ مساعد", "Assistant professor", I_COA, "1958", "1980"),
        (3, "باحث أول", "Senior researcher", I_IAS, "1990", None),
        (4, "أمينة مكتبة", "Librarian", I_EPL, "1975", "1985"),
        (4, "رئيسة قسم الفهرسة", "Head of cataloguing", I_EPL, "1985", "2010"),
        (5, "أرشيفي", "Archivist", I_NLA, "1935", "1960"),
        (5, "مدير الأرشيف", "Director of the archive", I_NLA, "1960", "1975"),
        (6, "أستاذ", "Professor", I_CU, "1990", None),
        (9, "مترجم", "Translator", I_IU, "1910", "1930"),
        (17, "أستاذ الأدب", "Professor of literature", I_CU, "1940", "1973"),
        (23, "أستاذ التاريخ", "Professor of history", I_CRS, "1990", None),
    ]
    for p_id, t_ar, t_en, iid, start, end in pos_rows:
        conn.execute(
            """INSERT INTO person_position (person_id, title_ar, title_en, institution_id,
                   start_date, end_date, start_precision, end_precision, is_current, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (person_ids[p_id], t_ar, t_en, iid, start, end,
             L("date_precision", "year"), L("date_precision", "year") if end else None,
             1 if not end else 0, 10))

    # ---- relationship types helper --------------------------------------
    RT = lambda code: L("relationship_type", code)

    def rel(e1t, e1, e2t, e2, rtype, start=None, end=None, desc=None, src=1):
        db_rel = {
            "entity1_type": e1t, "entity1_id": e1, "entity2_type": e2t, "entity2_id": e2,
            "relationship_type_id": RT(rtype), "description": desc,
            "start_date": start, "end_date": end,
            "source_id": src_ids.get(src, S1),
            "authentication_id": AU["corroborated"], "record_status_id": ST["verified"],
            "direction": "symmetric" if rtype in
                         ("colleague_of", "collaborator_of", "co_author_of", "partner_of",
                          "corresponded_with", "relative_of", "rival_of") else "directed",
            "last_review_date": "2026-03-01", "researcher_notes": NOTE,
        }
        from .schemas import ENTITIES as _E
        name_field = {"person": "name_en", "place": "name_en",
                      "institution": "name_en", "event": "title_en"}[e1t]
        name_field2 = {"person": "name_en", "place": "name_en",
                       "institution": "name_en", "event": "title_en"}[e2t]
        t1 = _E[e1t].table
        t2 = _E[e2t].table
        n1 = conn.execute(f"SELECT {name_field} v FROM {t1} WHERE id=?", (e1,)).fetchone()
        n2 = conn.execute(f"SELECT {name_field2} v FROM {t2} WHERE id=?", (e2,)).fetchone()
        db_rel["entity1_name"] = n1["v"] if n1 else None
        db_rel["entity2_name"] = n2["v"] if n2 else None
        try:
            _insert(conn, "relationship", db_rel)
        except sqlite3.IntegrityError:
            pass

    rel("person", person_ids[1], "person", person_ids[2], "teacher_of", "1948", "1975",
        "Taught at the same college; supervisory role documented in the staff list.")
    rel("person", person_ids[2], "person", person_ids[1], "student_of", "1948", "1975")
    rel("person", person_ids[1], "institution", I_UOM, "employed_by", "1940", "1978")
    rel("person", person_ids[2], "institution", I_COA, "employed_by", "1958", "2001")
    rel("person", person_ids[3], "institution", I_IAS, "member_of", "1990", None)
    rel("person", person_ids[4], "institution", I_EPL, "employed_by", "1975", "2010")
    rel("person", person_ids[5], "institution", I_NLA, "director_of", "1960", "1975")
    rel("person", person_ids[6], "institution", I_CU, "employed_by", "1990", None)
    rel("person", person_ids[7], "institution", I_DU, "member_of", "1925", "1964")
    rel("person", person_ids[8], "institution", I_DU, "graduated_from", "1905", "1910")
    rel("person", person_ids[9], "institution", I_IU, "graduated_from", "1900", "1908")
    rel("person", person_ids[10], "institution", I_IOS, "affiliated_with", "1935", "1973")
    rel("person", person_ids[11], "institution", I_HS, "member_of", "2005", None)
    rel("person", person_ids[13], "institution", I_HS, "founder_of", "1965", None)
    rel("person", person_ids[14], "institution", I_CRS, "board_member_of", "2001", None)
    rel("person", person_ids[16], "institution", I_UOB, "member_of", "2015", None)
    rel("person", person_ids[17], "person", person_ids[6], "colleague_of", "1950", "1973")
    rel("person", person_ids[18], "institution", I_UOB, "employed_by", "1985", "2015")
    rel("person", person_ids[19], "person", person_ids[1], "student_of", "1965", "1978")
    rel("person", person_ids[1], "place", P_MOSUL, "located_in", None, None,
        "Resided and worked in this city.")
    rel("institution", I_UOM, "place", P_MOSUL, "located_in")
    rel("institution", I_UOB, "place", P_BAGHDAD, "located_in")
    rel("institution", I_CRS, "place", P_BEIRUT, "located_in")
    rel("institution", I_IAS, "institution", I_UOB, "partner_of", "1990", None,
        "Joint publication programme.")
    rel("person", person_ids[20], "person", person_ids[21], "corresponded_with", "1935", "1955")
    rel("person", person_ids[15], "person", person_ids[3], "supervised_by", "2018", None)
    rel("person", person_ids[22], "institution", I_CRS, "employed_by", "1990", None)
    rel("person", person_ids[24], "institution", I_IOS, "collaborator_of", "2005", None)
    rel("person", person_ids[12], "place", P_QUDUS, "located_in")
    rel("institution", I_EPL, "place", P_BAGHDAD, "located_in")
    rel("person", person_ids[8], "person", person_ids[7], "rival_of", "1920", "1935",
        "Documented public disagreement.")

    # ---- events ----------------------------------------------------------
    events = [
        ("تأسيس الجامعة", "University founding", "founding", "1957", P_BAGHDAD),
        ("افتتاح المكتبة العامة", "Opening of the public library", "reopening", "1920", P_BAGHDAD),
        ("مؤتمر الدراسات التاريخية", "Conference on historical studies", "conference", "1995", P_AMMAN),
        ("نقل الأرشيف", "Transfer of the archive collection", "reform", "1975", P_CAIRO),
        ("حريق سوق المخطوطات", "Fire in the manuscript market", "destruction", "1947", P_DAMASCUS),
        ("وفاة المؤرخ", "Death of the historian", "death", "1978", P_MOSUL),
    ]
    event_ids = []
    for t_ar, t_en, etype, year, pid in events:
        event_ids.append(_insert(conn, "event", {
            "title_ar": t_ar, "title_en": t_en, "event_type_id": L("event_type", etype),
            "start_date": year, "start_precision": L("date_precision", "year"),
            "place_id": pid,
            "description": "Demo event description.", "significance": "Illustrates the timeline.",
            "primary_source_id": src_ids[2], "documentation_id": DO["partial"],
            "authentication_id": AU["single_source"], "record_status_id": ST["verified"],
            "researcher_notes": NOTE,
        }))
    rel("institution", I_UOB, "event", event_ids[0], "participated_in", "1957", None)
    rel("person", person_ids[1], "event", event_ids[5], "participated_in", "1978", None)

    # ---- tags ------------------------------------------------------------
    tag_defs = {
        "specialization": [("Modern Iraqi history", "التاريخ العراقي الحديث"),
                           ("Archival science", "علم الأرشيف"),
                           ("Arabic literature", "الأدب العربي"),
                           ("Ottoman studies", "الدراسات العثمانية"),
                           ("Islamic law", "الفقه الإسلامي"),
                           ("Translation studies", "دراسات الترجمة")],
        "expertise": [("Manuscript cataloguing", "فهرسة المخطوطات"),
                      ("Oral history", "التاريخ الشفوي"),
                      ("Digital archives", "الأرشيف الرقمي")],
    }
    tag_ids = {}
    for domain, items in tag_defs.items():
        for en, ar in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tag (domain, label_en, label_ar) VALUES (?,?,?)",
                (domain, en, ar))
            tid = cur.lastrowid or conn.execute(
                "SELECT id FROM tag WHERE domain=? AND label_en=?", (domain, en)).fetchone()["id"]
            tag_ids[(domain, en)] = tid
    for p_id, specs in {1: ["Modern Iraqi history"], 2: ["Arabic literature"],
                        5: ["Archival science"], 9: ["Ottoman studies"],
                        15: ["Islamic law"], 21: ["Translation studies"]}.items():
        for s in specs:
            conn.execute("INSERT OR IGNORE INTO entity_tag VALUES ('person',?,?)",
                         (person_ids[p_id], tag_ids[("specialization", s)]))
    for i_id, exps in {I_EPL: ["Manuscript cataloguing"], I_IAS: ["Digital archives"],
                       I_IOS: ["Oral history", "Ottoman studies"]}.items():
        for e in exps:
            tid = tag_ids.get(("expertise", e))
            if tid:
                conn.execute("INSERT OR IGNORE INTO entity_tag VALUES ('institution',?,?)", (i_id, tid))

    # ---- extra citations (many-to-many) ---------------------------------
    for i in range(1, 25):
        conn.execute("""INSERT OR IGNORE INTO evidence
                          (source_id, entity_type, entity_id, support_type, notes)
                        VALUES (?, 'person', ?, 'supports', 'Corroborating citation (demo)')""",
                     (src_ids[(i % 8) + 1], person_ids[i]))

    conn.commit()
    total = db.rebuild_index(conn)
    conn.commit()
    print(f"[siraj] demo dataset created · {total} search documents indexed")


# ---------------------------------------------------------------------------
# demo completeness variation (testing aid — demo rows only, deterministic)
# ---------------------------------------------------------------------------
# Field groups cleared together (semantic pairs stay paired: coordinates with
# their provenance, dates with their precision).  Identity, codes, names and
# system columns are NEVER touched — variation means missing optional
# metadata, not missing identity.
_VARY_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "person": (
        ("image_url", "image_alt"),
        ("birth_date", "birth_precision"),
        ("death_date", "death_precision"),
        ("nationality_id",),
        ("birthplace_id",),
        ("birthplace_text",),
        ("classification_id",),
        ("current_position",),
        ("declared_affiliation",),
        ("affiliated_institution_id",),
        ("affiliated_country_id",),
        ("affiliation_start", "affiliation_end"),
        ("institutional_relations",),
        ("website",),
        ("social_accounts",),
        ("cv_url",),
        ("public_activity",),
        ("researcher_notes",),
        ("latitude", "longitude", "geo_precision", "geocoding_method",
         "geo_uncertainty_m", "geometry_source"),
    ),
    "place": (
        ("image_url", "image_alt"),
        ("region",),
        ("city",),
        ("district",),
        ("parent_place_id",),
        ("geo_description",),
        ("research_significance",),
        ("researcher_notes",),
        ("latitude", "longitude", "geo_precision", "geocoding_method",
         "geo_uncertainty_m", "geometry_source"),
    ),
    "institution": (
        ("image_url", "image_alt"),
        ("abbreviation",),
        ("founded_date", "founded_precision"),
        ("closed_date",),
        ("city",),
        ("place_id",),
        ("address",),
        ("current_leadership",),
        ("founders_text",),
        ("objectives",),
        ("org_structure",),
        ("website",),
        ("official_accounts",),
        ("research_significance",),
        ("researcher_notes",),
        ("latitude", "longitude", "geo_precision", "geocoding_method",
         "geo_uncertainty_m", "geometry_source"),
    ),
    "event": (
        ("image_url", "image_alt"),
        ("start_date", "start_precision"),
        ("end_date",),
        ("place_id",),
        ("description",),
        ("significance",),
        ("researcher_notes",),
        ("latitude", "longitude", "geo_precision", "geocoding_method",
         "geo_uncertainty_m", "geometry_source"),
    ),
    "source": (
        ("publisher",),
        ("url",),
        ("publication_date", "publication_precision"),
        ("access_date",),
        ("supported_information",),
        ("verification_notes",),
        ("language",),
        ("isbn_issn",),
        ("archive_reference",),
        ("researcher_notes",),
    ),
}

_VARY_PROFILES = (("full", 1.0, 0.38), ("partial", 0.5, 0.72), ("minimal", 0.1, 1.0))


def vary_demo(conn: sqlite3.Connection, seed: str = "20261107") -> dict[str, dict[str, int]]:
    """Deterministic completeness variation over DEMO data (testing aid).

    Produces complete, partial and near-empty records across the registry
    entities so interfaces and reports are exercised against every state.
    Idempotent: decisions derive purely from (seed, table, id).  Refuses to
    run unless every row in each target table is demo-created (``created_by =
    'system'``) — real user data is never touched.
    """
    import random as _random

    stats: dict[str, dict[str, int]] = {}
    for table, groups in _VARY_GROUPS.items():
        total = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        foreign = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE created_by IS NOT 'system'"
        ).fetchone()["n"]
        if total and foreign:
            raise RuntimeError(
                f"vary_demo refused: {table} contains {foreign} non-demo row(s) "
                f"— real user data is never modified")
        counts = {"full": 0, "partial": 0, "minimal": 0, "groups_cleared": 0}
        for row in conn.execute(f"SELECT id FROM {table}").fetchall():
            rng = _random.Random(f"{seed}:{table}:{row['id']}")
            r = rng.random()
            profile, keep, _ = next(p for p in _VARY_PROFILES
                                    if r < p[2]) if r < 1.0 else _VARY_PROFILES[-1]
            counts[profile] += 1
            if profile == "full":
                continue
            for group in groups:
                if rng.random() > keep:
                    sets = ", ".join(f"{col} = NULL" for col in group)
                    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (row["id"],))
                    counts["groups_cleared"] += 1
        stats[table] = counts
    conn.commit()
    return stats

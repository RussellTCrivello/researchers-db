"""Load a large synthetic corpus through the registry write path.

Every place used as a location carries an exact coordinate pair. People,
institutions and events point at those places, and events also store
participants as real relationships. Records are marked in the researcher
notes as synthetic interface data, not historical claims.

Re-running skips any record whose English name or title is already present.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db
from app.repo import Conflict, ValidationError, create_record, update_record
from app.schemas import ENTITIES
from app.seed import seed_reference_data

NOTE = (
    "CORPUS · synthetic record created to exercise the registry. "
    "Not a historical claim."
)
ACTOR = "corpus"

# Surveyed city points. The coordinate is the location; the name only labels it.
CITIES = [
    ("IQ", "بغداد", "Baghdad", "Baghdad", 33.31520, 44.36610),
    ("IQ", "الموصل", "Mosul", "Nineveh", 36.33500, 43.11890),
    ("IQ", "البصرة", "Basra", "Basra", 30.50850, 47.78040),
    ("IQ", "أربيل", "Erbil", "Erbil", 36.19110, 44.00920),
    ("IQ", "كركوك", "Kirkuk", "Kirkuk", 35.46810, 44.39220),
    ("IQ", "السليمانية", "Sulaymaniyah", "Sulaymaniyah", 35.55700, 45.43560),
    ("EG", "القاهرة", "Cairo", "Cairo", 30.04440, 31.23570),
    ("EG", "الإسكندرية", "Alexandria", "Alexandria", 31.20010, 29.91870),
    ("SY", "دمشق", "Damascus", "Damascus", 33.51380, 36.27650),
    ("SY", "حلب", "Aleppo", "Aleppo", 36.20210, 37.13430),
    ("TR", "إستنبول", "Istanbul", "Istanbul", 41.00820, 28.97840),
    ("TR", "أنقرة", "Ankara", "Ankara", 39.93340, 32.85970),
    ("JO", "عمّان", "Amman", "Amman", 31.94540, 35.92840),
    ("LB", "بيروت", "Beirut", "Beirut", 33.89380, 35.50180),
    ("PS", "القدس", "Jerusalem", "Jerusalem", 31.76830, 35.21370),
    ("PS", "رام الله", "Ramallah", "Ramallah", 31.90380, 35.20340),
    ("SA", "الرياض", "Riyadh", "Riyadh", 24.71360, 46.67530),
    ("SA", "جدّة", "Jeddah", "Makkah", 21.54330, 39.17280),
    ("KW", "مدينة الكويت", "Kuwait City", "Kuwait", 29.37590, 47.97740),
    ("AE", "أبوظبي", "Abu Dhabi", "Abu Dhabi", 24.45390, 54.37730),
    ("QA", "الدوحة", "Doha", "Doha", 25.28540, 51.53100),
    ("BH", "المنامة", "Manama", "Capital", 26.22350, 50.58760),
    ("OM", "مسقط", "Muscat", "Muscat", 23.58800, 58.38290),
    ("YE", "صنعاء", "Sanaa", "Sanaa", 15.36940, 44.19100),
    ("SD", "الخرطوم", "Khartoum", "Khartoum", 15.50070, 32.55990),
    ("LY", "طرابلس", "Tripoli", "Tripoli", 32.88720, 13.19130),
    ("TN", "تونس", "Tunis", "Tunis", 36.80650, 10.18150),
    ("DZ", "الجزائر", "Algiers", "Algiers", 36.75380, 3.05880),
    ("MA", "الرباط", "Rabat", "Rabat-Salé-Kénitra", 34.02090, -6.84160),
    ("MA", "فاس", "Fez", "Fès-Meknès", 34.03310, -5.00030),
    ("IR", "طهران", "Tehran", "Tehran", 35.68920, 51.38900),
    ("IR", "أصفهان", "Isfahan", "Isfahan", 32.65460, 51.66800),
    ("TR", "قونية", "Konya", "Konya", 37.87460, 32.49320),
    ("GB", "لندن", "London", "Greater London", 51.50740, -0.12780),
    ("FR", "باريس", "Paris", "Île-de-France", 48.85660, 2.35220),
    ("DE", "برلين", "Berlin", "Berlin", 52.52000, 13.40500),
    ("IT", "روما", "Rome", "Lazio", 41.90280, 12.49640),
    ("ES", "مدريد", "Madrid", "Madrid", 40.41680, -3.70380),
    ("US", "نيويورك", "New York", "New York", 40.71280, -74.00600),
    ("CA", "مونتريال", "Montreal", "Quebec", 45.50170, -73.56730),
    ("JP", "طوكيو", "Tokyo", "Tokyo", 35.67620, 139.65030),
    ("IN", "دلهي", "Delhi", "Delhi", 28.61390, 77.20900),
    ("NG", "لاغوس", "Lagos", "Lagos", 6.52440, 3.37920),
    ("KE", "نيروبي", "Nairobi", "Nairobi", -1.29210, 36.82190),
    ("ZA", "كيب تاون", "Cape Town", "Western Cape", -33.92490, 18.42410),
    ("ID", "جاكرتا", "Jakarta", "Jakarta", -6.20880, 106.84560),
    ("RU", "موسكو", "Moscow", "Moscow", 55.75580, 37.61730),
    ("ET", "أديس أبابا", "Addis Ababa", "Addis Ababa", 9.03200, 38.74690),
]

SITE_KINDS = [
    ("library", "قاعة المخطوطات", "manuscript hall"),
    ("archive", "مبنى الأرشيف", "archive building"),
    ("museum", "قاعة المتحف", "museum hall"),
    ("building", "بوابة المقر", "headquarters gate"),
    ("school", "باحة المدرسة", "school court"),
    ("mosque", "صحن الجامع", "mosque court"),
    ("archaeological_site", "نقطة الموقع", "site datum"),
    ("neighbourhood", "تقاطع الحي", "quarter crossing"),
]

INST_KINDS = [
    ("university", "public", "centralized", "جامعة", "University"),
    ("college", "public", "collegial", "كلية", "College"),
    ("research_center", "private", "board_of_trustees", "مركز بحث", "Research centre"),
    ("institute", "public", "centralized", "معهد", "Institute"),
    ("ministry", "public", "centralized", "ديوان", "Ministry office"),
    ("government_body", "public", "federal", "هيئة", "Government body"),
    ("library", "public", "centralized", "مكتبة", "Library"),
    ("archive", "public", "centralized", "أرشيف", "Archive"),
    ("museum", "public", "board_of_trustees", "متحف", "Museum"),
    ("association", "ngo", "collegial", "جمعية", "Association"),
    ("foundation", "religious", "waqf_endowment", "وقف", "Endowment"),
    ("school", "private", "centralized", "مدرسة", "School"),
    ("media", "private", "board_of_trustees", "دار نشر", "Press"),
    ("hospital", "public", "centralized", "مستشفى", "Hospital"),
    ("international_body", "international", "collegial", "مكتب", "International office"),
    ("other", "mixed", "other", "مؤسسة", "Organisation"),
    ("university", "secular", "decentralized", "جامعة", "University"),
    ("library", "religious", "religious_authority", "خزانة", "Library"),
    ("research_center", "ngo", "collegial", "مرصد", "Observatory"),
    ("archive", "military", "military", "سجل", "Record office"),
    ("institute", "international", "federal", "معهد", "Institute"),
    ("museum", "private", "board_of_trustees", "متحف", "Museum"),
    ("association", "secular", "collegial", "رابطة", "Society"),
    ("foundation", "private", "board_of_trustees", "مؤسسة", "Foundation"),
]

GIVEN = [
    ("ليان", "Layan"), ("سارة", "Sara"), ("يوسف", "Yusuf"), ("مريم", "Maryam"),
    ("حسن", "Hasan"), ("نور", "Nour"), ("كريم", "Karim"), ("هديل", "Hadeel"),
    ("سامي", "Sami"), ("رغد", "Raghad"), ("باسل", "Basil"), ("لمى", "Lama"),
    ("فهد", "Fahd"), ("دانيا", "Dania"), ("وليد", "Walid"), ("سلمى", "Salma"),
    ("مازن", "Mazen"), ("هالة", "Hala"), ("طارق", "Tariq"), ("رشا", "Rasha"),
    ("عادل", "Adel"), ("ميساء", "Maysa"), ("نزار", "Nizar"), ("غادة", "Ghada"),
    ("إياد", "Iyad"), ("بتول", "Batul"), ("رامي", "Rami"), ("سهى", "Suha"),
    ("جلال", "Jalal"), ("وفاء", "Wafa"), ("صفاء", "Safa"), ("بدر", "Badr"),
]
FAMILY = {
    "IQ": [("التميمي", "al-Tamimi"), ("الدليمي", "al-Dulaimi"), ("الكربلائي", "al-Karbala'i"), ("البارزاني", "Barzani")],
    "EG": [("المنياوي", "al-Minyawi"), ("الإسكندراني", "al-Iskandarani"), ("السيوطي", "al-Suyuti"), ("النحاس", "al-Nahhas")],
    "SY": [("الحمصي", "al-Himsi"), ("الشامي", "al-Shami"), ("الحلبي", "al-Halabi"), ("الدمشقي", "al-Dimashqi")],
    "TR": [("الأسكداري", "Uskudari"), ("القونوي", "al-Qunawi"), ("الرومي", "al-Rumi"), ("الأناضولي", "al-Anaduli")],
    "JO": [("الكركي", "al-Karki"), ("السلطي", "al-Salti"), ("العجلوني", "al-Ajluni"), ("النابلسي", "al-Nabulsi")],
    "LB": [("البيروتي", "al-Bayruti"), ("الصيداوي", "al-Saydawi"), ("الطرابلسي", "al-Tarabulsi"), ("الجبيلي", "al-Jubayli")],
    "PS": [("المقدسي", "al-Maqdisi"), ("الغزي", "al-Ghazi"), ("الخليلي", "al-Khalili"), ("اليافي", "al-Yafi")],
    "SA": [("النجدي", "al-Najdi"), ("الحجازي", "al-Hijazi"), ("الأحسائي", "al-Ahsa'i"), ("العسيري", "al-Asiri")],
    "KW": [("الكويتي", "al-Kuwayti"), ("القناعي", "al-Qina'i")],
    "AE": [("الظبياني", "al-Dhabyani"), ("الدوسري", "al-Dosari")],
    "QA": [("الخليفي", "al-Khalifi"), ("المري", "al-Murri")],
    "BH": [("البحراني", "al-Bahrani"), ("الستري", "al-Sitri")],
    "OM": [("النزوي", "al-Nizwi"), ("الظفاري", "al-Dhufari")],
    "YE": [("الصنعاني", "al-San'ani"), ("العدني", "al-Adani")],
    "SD": [("الخرطومي", "al-Khartumi"), ("الدنقلاوي", "al-Dunqulawi")],
    "LY": [("الطرابلسي", "al-Tarabulsi"), ("البنغازي", "al-Banghazi")],
    "TN": [("التونسي", "al-Tunisi"), ("القيرواني", "al-Qayrawani")],
    "DZ": [("الجزائري", "al-Jaza'iri"), ("الوهراني", "al-Wahrani")],
    "MA": [("الفاسي", "al-Fasi"), ("المراكشي", "al-Marrakushi")],
    "IR": [("الأصفهاني", "al-Isfahani"), ("الطهراني", "al-Tihrani")],
    "GB": [("لندن", "Lang"), ("هاردي", "Hardi")],
    "FR": [("موريل", "Morel"), ("بلان", "Blanc")],
    "DE": [("فيبر", "Weber"), ("كلاين", "Klein")],
    "IT": [("روسي", "Rossi"), ("بيانكي", "Bianchi")],
    "ES": [("غارسيا", "Garcia"), ("لوبيز", "Lopez")],
    "US": [("هاربر", "Harper"), ("كولينز", "Collins")],
    "CA": [("تريمبلاي", "Tremblay"), ("غانيون", "Gagnon")],
    "JP": [("ساتو", "Sato"), ("تانكا", "Tanaka")],
    "IN": [("خان", "Khan"), ("رحمان", "Rahman")],
    "NG": [("أديبايُو", "Adebayo"), ("أوكافور", "Okafor")],
    "KE": [("وانجاري", "Wangari"), ("أوتينو", "Otieno")],
    "ZA": [("نكوسي", "Nkosi"), ("دلاميني", "Dlamini")],
    "ID": [("حكيم", "Hakim"), ("فتحي", "Fathi")],
    "RU": [("إيفانوف", "Ivanov"), ("بيتروف", "Petrov")],
    "ET": [("تادسي", "Tadesse"), ("بيكيلي", "Bekele")],
}
CLASSES = [
    "researcher", "professor", "historian", "religious_scholar", "writer",
    "translator", "journalist", "official", "politician", "librarian",
    "archivist", "administrator", "student", "other",
]
PERSON_STATES = ["active", "retired", "deceased", "missing", "unknown"]
RECORD_STATES = ["published", "verified", "in_review", "draft", "needs_update", "disputed", "archived"]
DOCS = ["minimal", "partial", "substantial", "exhaustive", "none"]
AUTHS = ["unverified", "self_declared", "single_source", "corroborated", "primary_document", "institutionally_confirmed"]
PRECISIONS = ["year", "exact", "month", "approximate", "uncertain"]
POSITIONS = {
    "professor": ("أستاذ", "Professor"),
    "researcher": ("باحث", "Researcher"),
    "historian": ("مؤرخ", "Historian"),
    "librarian": ("أمين مكتبة", "Librarian"),
    "archivist": ("أرشيفي", "Archivist"),
    "journalist": ("محرر", "Editor"),
    "official": ("موظف", "Officer"),
    "administrator": ("مسجّل", "Registrar"),
    "student": ("طالب دراسات", "Research student"),
    "writer": ("مؤلف", "Author"),
    "translator": ("مترجم", "Translator"),
    "politician": ("عضو هيئة", "Board member"),
    "religious_scholar": ("مدرّس", "Teacher"),
    "other": ("متعاون", "Associate"),
}
SPEC_TAGS = [
    ("Manuscript studies", "دراسة المخطوطات"),
    ("Urban history", "تاريخ المدن"),
    ("Legal documents", "الوثائق القانونية"),
    ("Cartography", "علم الخرائط"),
    ("Biography", "التراجم"),
    ("Education history", "تاريخ التعليم"),
    ("Waqf studies", "دراسات الوقف"),
    ("Press history", "تاريخ الصحافة"),
]
SOURCE_KINDS = [
    ("book", "كتاب السجل", "Registry handbook", "high", "ar"),
    ("journal_article", "مقالة الفهرس", "Index article", "medium", "en"),
    ("thesis", "أطروحة التجريب", "Trial dissertation", "secondary", "ar"),
    ("archive_document", "ملف المراسلات", "Correspondence file", "primary_contemporary", "ar"),
    ("manuscript", "دفتر الملاحظات", "Notebook manuscript", "high", "ar"),
    ("official_register", "سجل القيد", "Enrolment register", "primary_contemporary", "ar"),
    ("interview", "مقابلة مسجّلة", "Recorded interview", "medium", "ar"),
    ("oral_history", "رواية شفوية", "Oral account", "low", "ar"),
    ("website", "صفحة المرجع", "Reference page", "unverified", "en"),
    ("social_media", "منشور محفوظ", "Archived post", "low", "ar"),
    ("newspaper", "قصاصة صحفية", "Press cutting", "secondary", "ar"),
    ("report", "تقرير الجرد", "Inventory report", "medium", "en"),
    ("photograph", "لوحة فوتوغرافية", "Photographic plate", "high", "en"),
    ("map", "لوحة إحداثيات", "Coordinate sheet", "primary_contemporary", "en"),
    ("database", "جدول الجرد", "Inventory table", "medium", "en"),
    ("encyclopedia", "مدخل موسوعي", "Encyclopaedia note", "secondary", "ar"),
    ("other", "ورقة متفرقة", "Loose sheet", "unverified", "ar"),
    ("book", "دليل الأماكن", "Gazette of places", "high", "fr"),
]
EVENT_KINDS = [
    "birth", "death", "founding", "merger", "closure", "reopening",
    "conference", "appointment", "publication", "migration", "dispute",
    "celebration", "destruction", "reform", "other",
    "conference", "founding", "appointment", "publication", "migration",
]
EVENT_LABEL = {
    "birth": ("ولادة مسجّلة", "Recorded birth"),
    "death": ("وفاة مسجّلة", "Recorded death"),
    "founding": ("تأسيس مقر", "Seat founded"),
    "merger": ("دمج إدارتين", "Two offices merged"),
    "closure": ("إغلاق مؤقت", "Temporary closure"),
    "reopening": ("إعادة فتح القاعة", "Hall reopened"),
    "conference": ("ملتقى السجلات", "Records meeting"),
    "appointment": ("تعيين أمين", "Keeper appointed"),
    "publication": ("صدور فهرس", "Catalogue issued"),
    "migration": ("انتقال مجموعة", "Collection moved"),
    "dispute": ("خلاف على النسبة", "Attribution dispute"),
    "celebration": ("ذكرى الافتتاح", "Opening anniversary"),
    "destruction": ("تلف مجموعة", "A collection damaged"),
    "reform": ("إعادة ترتيب الفهرس", "Catalogue reformed"),
    "other": ("واقعة غير مصنّفة", "Unclassified occurrence"),
}
REL_KINDS = [
    ("employed_by", "directed"),
    ("member_of", "directed"),
    ("graduated_from", "directed"),
    ("teacher_of", "directed"),
    ("student_of", "directed"),
    ("colleague_of", "symmetric"),
    ("collaborator_of", "symmetric"),
    ("co_author_of", "symmetric"),
    ("founder_of", "directed"),
    ("director_of", "directed"),
    ("board_member_of", "directed"),
    ("affiliated_with", "directed"),
    ("corresponded_with", "symmetric"),
    ("relative_of", "symmetric"),
    ("father_of", "directed"),
    ("rival_of", "symmetric"),
    ("partner_of", "symmetric"),
    ("located_in", "directed"),
    ("cites", "directed"),
    ("supervised", "directed"),
]


def main() -> None:
    conn = db.connect()
    seed_reference_data(conn)
    conn.commit()
    made = {"source": 0, "place": 0, "institution": 0, "person": 0,
            "event": 0, "relationship": 0, "evidence": 0}
    pending = 0

    def flush(force: bool = False) -> None:
        nonlocal pending
        if force or pending >= 25:
            conn.commit()
            pending = 0

    def find(table: str, column: str, value: str) -> int | None:
        row = conn.execute(
            f"SELECT id FROM {table} WHERE {column}=? AND deleted_at IS NULL",
            (value,)).fetchone()
        return int(row["id"]) if row else None

    def add(entity: str, payload: dict, key: tuple[str, str] | None) -> int:
        nonlocal pending
        payload = dict(payload)
        payload.setdefault("researcher_notes", NOTE)
        if key:
            found = find(ENTITIES[entity].table, key[0], key[1])
            if found:
                return found
        try:
            rec = create_record(conn, ENTITIES[entity], payload, actor=ACTOR,
                                reason="synthetic corpus", commit=False)
        except Conflict:
            if key:
                found = find(ENTITIES[entity].table, key[0], key[1])
                if found:
                    return found
            raise
        made[entity] = made.get(entity, 0) + 1
        pending += 1
        flush()
        return int(rec["id"])

    def name_of(entity: str, rec_id: int) -> str:
        spec = ENTITIES[entity]
        row = conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (rec_id,)).fetchone()
        return spec.title(dict(row)) if row else str(rec_id)

    try:
        sources = []
        for i, (kind, ar, en, rel, lang) in enumerate(SOURCE_KINDS):
            title = f"Siraj corpus · {en}"
            sid = add("source", {
                "title": title,
                "title_ar": f"ذخيرة سِراج · {ar}",
                "source_type_id": kind,
                "publisher": "Siraj corpus desk",
                "publication_date": f"{1980 + (i * 2) % 40}-0{(i % 9) + 1}-15" if i % 3 == 0 else str(1975 + i),
                "publication_precision": "exact" if i % 3 == 0 else "year",
                "language": lang,
                "url": f"https://example.org/siraj/sources/{i + 1}",
                "isbn_issn": f"978-0-0000-{i + 1:04d}-0" if kind == "book" else None,
                "archive_reference": f"CX/{kind[:3].upper()}/{i + 1:03d}",
                "reliability_id": rel,
                "supported_information": "Synthetic citation used to back corpus records.",
                "record_status_id": ("draft", "in_review", "needs_update", "disputed")[i % 4],
                "authentication_id": "corroborated",
                "access_date": "2026-11-03",
            }, ("title", title))
            sources.append(sid)
        flush(True)
        primary = sources[0]

        cities = []
        sites = []
        for i, (cc, ar, en, region, lat, lon) in enumerate(CITIES):
            city_en = f"{en} datum"
            city_id = add("place", {
                "name_ar": f"{ar} — نقطة مثبتة",
                "name_en": city_en,
                "name_original": en,
                "name_original_lang": "en",
                "place_type_id": "city",
                "country_id": cc,
                "region": region,
                "city": en,
                "latitude": lat,
                "longitude": lon,
                "geo_precision": "exact",
                "geocoding_method": "coordinate_entry" if i % 2 == 0 else "map_pick",
                "geometry_source": "typed coordinates" if i % 2 == 0 else "map pick",
                "geo_description": (
                    f"Exact point {lat:.5f}, {lon:.5f}. "
                    "The pair is the location; the city name only labels it."
                ),
                "research_significance": "Anchor used by corpus people and organisations in this city.",
                "primary_source_id": sources[i % len(sources)],
                "documentation_id": "substantial",
                "authentication_id": "primary_document",
                "record_status_id": "verified",
            }, ("name_en", city_en))
            kind, kind_ar, kind_en = SITE_KINDS[i % len(SITE_KINDS)]
            # A second precise point, about a kilometre from the city datum.
            slat = round(lat + 0.008, 5)
            slon = round(lon + 0.006, 5)
            site_en = f"{en} {kind_en}"
            site_id = add("place", {
                "name_ar": f"{ar} — {kind_ar}",
                "name_en": site_en,
                "name_original": site_en,
                "name_original_lang": "en",
                "place_type_id": kind,
                "country_id": cc,
                "region": region,
                "city": en,
                "district": kind_en,
                "parent_place_id": city_id,
                "latitude": slat,
                "longitude": slon,
                "geo_precision": "exact",
                "geocoding_method": "map_pick" if i % 2 == 0 else "coordinate_entry",
                "geometry_source": "map pick" if i % 2 == 0 else "typed coordinates",
                "geo_description": (
                    f"Exact point {slat:.5f}, {slon:.5f}, parented to the {en} datum. "
                    "Entered as a coordinate pair, not as a place name."
                ),
                "research_significance": "The precise seat used by an organisation and by events.",
                "primary_source_id": sources[(i + 3) % len(sources)],
                "documentation_id": "partial",
                "authentication_id": "corroborated",
                "record_status_id": "published",
            }, ("name_en", site_en))
            cities.append({"cc": cc, "ar": ar, "en": en, "id": city_id, "lat": lat, "lon": lon})
            sites.append({"cc": cc, "ar": ar, "en": en, "id": site_id, "city_id": city_id})
        flush(True)

        institutions = []
        for i, (itype, sub, gov, ar_kind, en_kind) in enumerate(INST_KINDS):
            site = sites[i % len(sites)]
            en = f"Siraj {en_kind} · {site['en']}"
            iid = add("institution", {
                "name_ar": f"سِراج — {ar_kind} {site['ar']}",
                "name_en": en,
                "name_original": en,
                "name_original_lang": "en",
                "abbreviation": f"SJ{i + 1:02d}",
                "institution_type_id": itype,
                "subcategory_id": sub,
                "founded_date": str(1860 + (i * 7) % 150),
                "founded_precision": "year",
                "country_id": site["cc"],
                "city": site["en"],
                "place_id": site["id"],
                "address": f"Precise seat recorded at the {site['en']} point.",
                "objectives": "Hold, describe and exchange records for this corpus.",
                "org_structure": "A director, a reading room and a small catalogue desk.",
                "governance_id": gov,
                "website": f"https://example.org/siraj/org/{i + 1}",
                "research_significance": "Organisation node linked to people, events and a precise place.",
                "primary_source_id": sources[i % len(sources)],
                "documentation_id": DOCS[i % len(DOCS)],
                "authentication_id": AUTHS[i % len(AUTHS)],
                "record_status_id": RECORD_STATES[i % 4],
            }, ("name_en", en))
            institutions.append({"id": iid, "cc": site["cc"], "en": en, "site_id": site["id"],
                                 "city_id": site["city_id"], "ar": site["ar"]})
        flush(True)

        people = []
        seen_names = set()
        # Two people for every city, so nationalities, classifications and
        # statuses all appear, and no single branch swallows the leaves.
        for i, city in enumerate(cities):
            for slot in range(2):
                n = i * 2 + slot
                cc = city["cc"]
                given_ar, given_en = GIVEN[n % len(GIVEN)]
                fams = FAMILY.get(cc, FAMILY["IQ"])
                fam_ar, fam_en = fams[(n // len(GIVEN)) % len(fams)]
                ar = f"{given_ar} {fam_ar}"
                en = f"{given_en} {fam_en}"
                if (ar, en) in seen_names:
                    ar = f"{given_ar} عبد الله {fam_ar}"
                    en = f"{given_en} Abdallah {fam_en}"
                seen_names.add((ar, en))
                cls = CLASSES[n % len(CLASSES)]
                state = PERSON_STATES[n % len(PERSON_STATES)]
                birth_year = 1910 + (n * 3) % 85
                if n % 5 == 0:
                    birth = f"{birth_year}-0{(n % 8) + 1}-1{(n % 8)}"
                    bprec = "exact"
                elif n % 5 == 1:
                    birth = f"{birth_year}-0{(n % 8) + 1}"
                    bprec = "month"
                else:
                    birth = str(birth_year)
                    bprec = PRECISIONS[n % len(PRECISIONS)]
                    if bprec == "exact":
                        bprec = "year"
                death = None
                dprec = None
                if state == "deceased":
                    death = str(min(birth_year + 40 + (n % 30), 2020))
                    dprec = "year"
                inst = institutions[n % len(institutions)]
                # Prefer an organisation in the same country when one exists.
                same = [x for x in institutions if x["cc"] == cc]
                if same:
                    inst = same[n % len(same)]
                title_ar, title_en = POSITIONS[cls]
                positions = []
                if n % 3 == 0:
                    other = institutions[(n + 5) % len(institutions)]
                    positions.append({
                        "title_ar": "كاتب",
                        "title_en": "Clerk",
                        "institution_id": other["id"],
                        "start_date": str(birth_year + 22),
                        "end_date": str(birth_year + 30),
                        "is_current": False,
                        "notes": NOTE,
                    })
                positions.append({
                    "title_ar": title_ar,
                    "title_en": title_en,
                    "institution_id": inst["id"],
                    "start_date": str(birth_year + 28),
                    "end_date": death,
                    "is_current": state == "active",
                    "notes": NOTE,
                })
                pid = add("person", {
                    "name_ar": ar,
                    "name_en": en,
                    "name_original": en,
                    "name_original_lang": "en" if cc not in ("FR", "DE", "TR", "RU", "JP") else {
                        "FR": "fr", "DE": "de", "TR": "tr", "RU": "ru", "JP": "ja"}.get(cc, "en"),
                    "name_transliteration": en,
                    "birth_date": birth,
                    "birth_precision": bprec,
                    "death_date": death,
                    "death_precision": dprec,
                    "nationality_id": cc,
                    "birthplace_id": city["id"],
                    "classification_id": cls,
                    "current_status_id": state,
                    "current_position": title_en,
                    "affiliated_institution_id": inst["id"],
                    "affiliated_country_id": cc,
                    "declared_affiliation": inst["en"],
                    "affiliation_verified": 1 if n % 2 == 0 else 0,
                    "affiliation_start": str(birth_year + 28),
                    "affiliation_end": death,
                    "public_activity": "Lectures, catalogues and correspondence in the corpus.",
                    "institutional_relations": "See the linked organisation, events and relationships.",
                    "primary_source_id": sources[n % len(sources)],
                    "documentation_id": DOCS[n % len(DOCS)],
                    "authentication_id": AUTHS[n % len(AUTHS)],
                    "record_status_id": RECORD_STATES[n % len(RECORD_STATES)],
                    "positions": positions,
                }, ("name_en", en))
                people.append({"id": pid, "cc": cc, "en": en, "ar": ar, "inst": inst["id"],
                               "city_id": city["id"], "cls": cls, "state": state})
        flush(True)

        events = []
        for i, kind in enumerate(EVENT_KINDS):
            site = sites[i % len(sites)]
            label_ar, label_en = EVENT_LABEL[kind]
            year = 1925 + (i * 4) % 95
            title_en = f"Siraj · {label_en} · {site['en']} · {year}"
            title_ar = f"سِراج · {label_ar} · {site['ar']} · {year}"
            people_here = [p for p in people if p["cc"] == site["cc"]] or people
            inst_here = [x for x in institutions if x["cc"] == site["cc"]] or institutions
            parts = [
                {"entity_type": "person", "entity_id": people_here[i % len(people_here)]["id"]},
                {"entity_type": "person", "entity_id": people_here[(i + 1) % len(people_here)]["id"]},
                {"entity_type": "institution", "entity_id": inst_here[i % len(inst_here)]["id"]},
            ]
            if i % 4 == 0 and len(people_here) > 2:
                parts.append({"entity_type": "person", "entity_id": people_here[(i + 2) % len(people_here)]["id"]})
            end = None
            if kind in ("conference", "migration", "dispute", "closure"):
                end = str(year + (1 if kind != "conference" else 0))
                if kind == "conference":
                    end = f"{year}-0{(i % 8) + 1}-20"
            start = f"{year}-0{(i % 8) + 1}-12" if i % 2 == 0 else str(year)
            eid = add("event", {
                "title_ar": title_ar,
                "title_en": title_en,
                "event_type_id": kind,
                "start_date": start,
                "start_precision": "exact" if i % 2 == 0 else "year",
                "end_date": end,
                "place_id": site["id"],
                "description": (
                    "Synthetic event. Participants are stored as relationships "
                    "to people and organisations, and the place is a precise coordinate."
                ),
                "significance": "Connects the corpus across people, organisations and a mapped point.",
                "primary_source_id": sources[i % len(sources)],
                "documentation_id": DOCS[i % len(DOCS)],
                "authentication_id": AUTHS[(i + 2) % len(AUTHS)],
                "record_status_id": RECORD_STATES[i % 5],
                "_participants": parts,
            }, ("title_en", title_en))
            events.append({"id": eid, "title": title_en, "site_id": site["id"],
                           "people": [p["entity_id"] for p in parts if p["entity_type"] == "person"],
                           "inst": parts[-1]["entity_id"] if parts[-1]["entity_type"] == "institution" else None})
        flush(True)

        def link(e1t, e1, e2t, e2, rtype, direction, start=None, end=None, desc=None, src=None):
            if e1t == e2t and e1 == e2:
                return None
            payload = {
                "entity1_type": e1t, "entity1_id": e1, "entity1_name": name_of(e1t, e1),
                "relationship_type_id": rtype,
                "entity2_type": e2t, "entity2_id": e2, "entity2_name": name_of(e2t, e2),
                "direction": direction,
                "description": desc or "Synthetic link in the corpus.",
                "start_date": start, "end_date": end,
                "is_current": 0 if end else 1,
                "source_id": src or primary,
                "authentication_id": "corroborated",
                "record_status_id": "in_review",
                "last_review_date": "2026-11-03",
                "researcher_notes": NOTE,
            }
            try:
                return add("relationship", payload, None)
            except (Conflict, ValidationError, sqlite3.Error) as exc:
                print(f"skip link {rtype} {e1t}:{e1} -> {e2t}:{e2}: {exc}")
                return None

        for i, person in enumerate(people):
            inst = next(x for x in institutions if x["id"] == person["inst"])
            rtype, direction = REL_KINDS[i % len(REL_KINDS)]
            if rtype in ("located_in",):
                link("person", person["id"], "place", person["city_id"], "located_in", "directed",
                     desc="The person is tied to this precise city datum.")
            elif rtype == "cites":
                link("person", person["id"], "source", sources[i % len(sources)], "cites", "directed",
                     desc="The record cites this corpus source.")
            elif rtype in ("partner_of",):
                other = institutions[(i + 3) % len(institutions)]
                link("institution", inst["id"], "institution", other["id"], "partner_of", "symmetric",
                     start=str(1990 + (i % 20)), desc="The two organisations share a catalogue programme.")
            elif rtype in ("employed_by", "member_of", "graduated_from", "affiliated_with",
                           "founder_of", "director_of", "board_member_of"):
                link("person", person["id"], "institution", inst["id"], rtype, direction,
                     start=str(1950 + (i % 60)), desc=f"Corpus link ({rtype}) to the person's organisation.")
            elif rtype in ("teacher_of", "student_of", "colleague_of", "collaborator_of",
                           "co_author_of", "corresponded_with", "relative_of", "father_of",
                           "rival_of", "supervised"):
                other = people[(i + 7) % len(people)]
                link("person", person["id"], "person", other["id"], rtype, direction,
                     start=str(1960 + (i % 40)), end=str(1990 + (i % 30)) if i % 4 == 0 else None,
                     desc=f"Corpus link ({rtype}) between two people.")
            if i % 2 == 0:
                link("institution", inst["id"], "place", inst["site_id"], "located_in", "directed",
                     desc="The organisation sits on this precise point, not on the city name.")
            if i % 5 == 0 and events:
                ev = events[i % len(events)]
                link("person", person["id"], "event", ev["id"], "participated_in", "directed",
                     desc="Additional participation beyond the event's own participant list.")

        # Bridge the corpus to the records that were already in the registry,
        # so older events gain people and organisations.
        old_events = [int(r["id"]) for r in conn.execute(
            "SELECT id FROM event WHERE deleted_at IS NULL AND title_en NOT LIKE 'Siraj · %' "
            "ORDER BY id")]
        old_people = [int(r["id"]) for r in conn.execute(
            "SELECT id FROM person WHERE deleted_at IS NULL AND ifnull(researcher_notes,'') NOT LIKE 'CORPUS%' "
            "ORDER BY id LIMIT 8")]
        for i, eid in enumerate(old_events):
            have = []
            for row in conn.execute(
                    "SELECT entity1_type t, entity1_id a, entity2_type u, entity2_id b "
                    "FROM relationship WHERE deleted_at IS NULL AND "
                    "((entity1_type='event' AND entity1_id=?) OR (entity2_type='event' AND entity2_id=?))",
                    (eid, eid)):
                if row["t"] == "event":
                    have.append({"entity_type": row["u"], "entity_id": int(row["b"])})
                else:
                    have.append({"entity_type": row["t"], "entity_id": int(row["a"])})
            extra = [
                {"entity_type": "person", "entity_id": people[i % len(people)]["id"]},
                {"entity_type": "person", "entity_id": people[(i + 3) % len(people)]["id"]},
                {"entity_type": "institution", "entity_id": institutions[i % len(institutions)]["id"]},
            ]
            if old_people:
                extra.append({"entity_type": "person", "entity_id": old_people[i % len(old_people)]})
            merged = []
            seen = set()
            for item in have + extra:
                if item["entity_type"] not in ("person", "institution"):
                    continue
                key = (item["entity_type"], int(item["entity_id"]))
                if key in seen:
                    continue
                seen.add(key)
                merged.append({"entity_type": key[0], "entity_id": key[1]})
            update_record(conn, ENTITIES["event"], eid, {"_participants": merged},
                          actor=ACTOR, reason="corpus participants added", commit=False)
            pending += 1
        flush(True)

        for i, inst in enumerate(institutions):
            label_en, label_ar = SPEC_TAGS[i % len(SPEC_TAGS)]
            conn.execute(
                "INSERT OR IGNORE INTO tag (domain, label_en, label_ar) VALUES (?,?,?)",
                ("expertise", label_en, label_ar))
            tid = conn.execute(
                "SELECT id FROM tag WHERE domain=? AND label_en=?",
                ("expertise", label_en)).fetchone()["id"]
            conn.execute(
                "INSERT OR IGNORE INTO entity_tag (entity_type, entity_id, tag_id) VALUES (?,?,?)",
                ("institution", inst["id"], tid))
        for i, person in enumerate(people):
            label_en, label_ar = SPEC_TAGS[i % len(SPEC_TAGS)]
            conn.execute(
                "INSERT OR IGNORE INTO tag (domain, label_en, label_ar) VALUES (?,?,?)",
                ("specialization", label_en, label_ar))
            tid = conn.execute(
                "SELECT id FROM tag WHERE domain=? AND label_en=?",
                ("specialization", label_en)).fetchone()["id"]
            conn.execute(
                "INSERT OR IGNORE INTO entity_tag (entity_type, entity_id, tag_id) VALUES (?,?,?)",
                ("person", person["id"], tid))
            conn.execute(
                """INSERT OR IGNORE INTO evidence
                     (source_id, entity_type, entity_id, support_type, supported_claim,
                      page_or_timestamp, notes, created_by, updated_by)
                   VALUES (?, 'person', ?, ?, ?, ?, ?, ?, ?)""",
                (sources[i % len(sources)], person["id"],
                 ("supports", "contradicts", "contextualizes")[i % 3],
                 "Synthetic claim attached so the record has a citation.",
                 f"p. {(i % 40) + 1}", NOTE, ACTOR, ACTOR))
            made["evidence"] += 1
        for i, ev in enumerate(events):
            conn.execute(
                """INSERT OR IGNORE INTO evidence
                     (source_id, entity_type, entity_id, support_type, supported_claim,
                      notes, created_by, updated_by)
                   VALUES (?, 'event', ?, 'supports', ?, ?, ?, ?)""",
                (sources[(i + 1) % len(sources)], ev["id"],
                 "Synthetic support for the event and its participants.", NOTE, ACTOR, ACTOR))
            made["evidence"] += 1
        flush(True)

        totals = {}
        for table in ("person", "place", "institution", "source", "event", "relationship"):
            totals[table] = conn.execute(
                f"SELECT COUNT(*) c FROM {table} WHERE deleted_at IS NULL").fetchone()["c"]
        located = conn.execute(
            "SELECT COUNT(*) c FROM place WHERE deleted_at IS NULL "
            "AND latitude IS NOT NULL AND longitude IS NOT NULL "
            "AND name_en LIKE '%datum' OR name_en LIKE '%hall' OR name_en LIKE '%building' "
            "OR name_en LIKE '%gate' OR name_en LIKE '%court' OR name_en LIKE '%datum' "
            "OR name_en LIKE '%crossing'").fetchone()["c"]
        linked_events = conn.execute(
            """SELECT COUNT(DISTINCT e.id) c FROM event e
               JOIN relationship r ON r.deleted_at IS NULL AND (
                    (r.entity1_type='event' AND r.entity1_id=e.id AND r.entity2_type IN ('person','institution'))
                 OR (r.entity2_type='event' AND r.entity2_id=e.id AND r.entity1_type IN ('person','institution'))
               ) WHERE e.deleted_at IS NULL""").fetchone()["c"]
        print("CREATED", made)
        print("TOTALS", totals)
        print("EVENTS_WITH_PEOPLE_OR_ORGS", linked_events)
        print("CORPUS_PLACES_TOUCHED", located)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

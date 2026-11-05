"""
SIRAJ · bulk.py — large-scale synthetic dataset generator
=========================================================

Produces a *realistic-shaped*, deterministic (seeded) dataset so that every
interface element — lists, filters, derived fields, charts, reports, pivots,
maps, exports, duplicate detection, pagination, load-more, full-text search —
is exercised against volume rather than a handful of hand-written rows.

Properties that matter
----------------------
* **Deterministic**: the same ``seed`` always produces the same dataset, so the
  verification suite can assert exact counts and reproducible samples.
* **Vocabulary-complete**: every lookup domain is sampled, so every badge,
  filter operator and report bucket has data behind it (some records are left
  deliberately incomplete, some are drafts, some soft-deleted).
* **Topologically sound**: relationships only ever point at records that exist,
  places form a real 3-level hierarchy, positions point at institutions, and
  citations point at sources — so every derived field has something to compute.
* **Fast**: codes are allocated in bulk from the sequence rows, rows are written
  with ``executemany`` inside one transaction, and the FTS index is rebuilt once
  at the end (``rebuild_index``) instead of per row.

Typical use::

    python -m app.cli bulk --profile large        # ~5 000 persons, ~30 000 rows
    python -m app.cli bulk --profile huge         # ~20 000 persons

The generator never deletes anything and never touches reference data; it only
appends. Run it on a scratch database (``SIRAJ_DATA_DIR``) when in doubt.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from . import db

# ---------------------------------------------------------------------------
# name pools — Arabic with the English/translit form used in the same record
# ---------------------------------------------------------------------------
GIVEN_M = [
    ("محمد", "Muhammad"), ("أحمد", "Ahmad"), ("علي", "Ali"), ("حسن", "Hasan"),
    ("حسين", "Husayn"), ("عمر", "Umar"), ("خالد", "Khalid"), ("يوسف", "Yusuf"),
    ("إبراهيم", "Ibrahim"), ("عبد الله", "Abdullah"), ("عبد الرحمن", "Abd al-Rahman"),
    ("مصطفى", "Mustafa"), ("محمود", "Mahmud"), ("سعيد", "Said"), ("سليم", "Salim"),
    ("طارق", "Tariq"), ("زياد", "Ziyad"), ("نبيل", "Nabil"), ("فؤاد", "Fuad"),
    ("كمال", "Kamal"), ("منير", "Munir"), ("رشيد", "Rashid"), ("جمال", "Jamal"),
    ("عصام", "Isam"), ("عدنان", "Adnan"), ("فيصل", "Faysal"), ("ماجد", "Majid"),
    ("سامي", "Sami"), ("هشام", "Hisham"), ("بشير", "Bashir"), ("أنور", "Anwar"),
    ("توفيق", "Tawfiq"), ("شريف", "Sharif"), ("مراد", "Murad"), ("ياسر", "Yasir"),
]
GIVEN_F = [
    ("فاطمة", "Fatima"), ("عائشة", "Aisha"), ("مريم", "Maryam"), ("زينب", "Zaynab"),
    ("خديجة", "Khadija"), ("سلمى", "Salma"), ("ليلى", "Layla"), ("هدى", "Huda"),
    ("نورة", "Noura"), ("سعاد", "Suad"), ("رجاء", "Raja"), ("أمل", "Amal"),
    ("إيمان", "Iman"), ("صفاء", "Safaa"), ("نجاح", "Najah"), ("ياسمين", "Yasmin"),
    ("رنا", "Rana"), ("دلال", "Dalal"), ("سميرة", "Samira"), ("منى", "Muna"),
    ("غادة", "Ghada"), ("إلهام", "Ilham"), ("نسرين", "Nisrin"), ("سناء", "Sanaa"),
    ("بشرى", "Bushra"), ("وفاء", "Wafaa"), ("حنان", "Hanan"), ("ريم", "Reem"),
]
PATRONYMIC = [
    ("بن عبد الله", "b. Abd Allah"), ("بن محمد", "b. Muhammad"), ("بن علي", "b. Ali"),
    ("بن حسن", "b. Hasan"), ("بن سعيد", "b. Said"), ("بن إبراهيم", "b. Ibrahim"),
    ("بن يوسف", "b. Yusuf"), ("بن خالد", "b. Khalid"), ("بن عمر", "b. Umar"),
    ("بن مصطفى", "b. Mustafa"),
]
FAMILY = [
    ("الحداد", "al-Haddad"), ("النجار", "al-Najjar"), ("الخطيب", "al-Khatib"),
    ("الجابري", "al-Jaburi"), ("التميمي", "al-Tamimi"), ("البغدادي", "al-Baghdadi"),
    ("المصري", "al-Misri"), ("الشامي", "al-Shami"), ("الحلبي", "al-Halabi"),
    ("الدمشقي", "al-Dimashqi"), ("القرشي", "al-Qurashi"), ("الهاشمي", "al-Hashimi"),
    ("العبيدي", "al-Ubaydi"), ("الزبيدي", "al-Zubaydi"), ("السعدي", "al-Sadi"),
    ("العمري", "al-Umari"), ("الحسيني", "al-Husayni"), ("الرفاعي", "al-Rifai"),
    ("الشمري", "al-Shammari"), ("العنزي", "al-Anzi"), ("المراكشي", "al-Marrakushi"),
    ("التونسي", "al-Tunisi"), ("الفاسي", "al-Fasi"), ("اليمني", "al-Yamani"),
    ("الكويتي", "al-Kuwayti"), ("اللبناني", "al-Lubnani"), ("الأردني", "al-Urduni"),
    ("السوري", "al-Suri"), ("العراقي", "al-Iraqi"), ("الحجازي", "al-Hijazi"),
    ("الطاهر", "al-Tahir"), ("بن سليمان", "b. Sulayman"), ("بن عيسى", "b. Isa"),
    ("الأمين", "al-Amin"), ("الصادق", "al-Sadiq"), ("الفارابي", "al-Farabi"),
]
NISBA = [
    ("الباحث", "researcher"), ("المؤرخ", "historian"), ("اللغوي", "linguist"),
    ("الفقيه", "jurist"), ("الطبيب", "physician"), ("المهندس", "engineer"),
]

CITY_BY_COUNTRY: dict[str, list[tuple[str, str]]] = {
    "IQ": [("بغداد", "Baghdad"), ("البصرة", "Basra"), ("الموصل", "Mosul"),
           ("النجف", "Najaf"), ("كربلاء", "Karbala"), ("أربيل", "Erbil"),
           ("السليمانية", "Sulaymaniyah"), ("الحلة", "Hillah")],
    "EG": [("القاهرة", "Cairo"), ("الإسكندرية", "Alexandria"), ("أسيوط", "Asyut"),
           ("طنطا", "Tanta"), ("المنصورة", "Mansura"), ("الأقصر", "Luxor")],
    "SY": [("دمشق", "Damascus"), ("حلب", "Aleppo"), ("حمص", "Homs"),
           ("اللاذقية", "Latakia"), ("حماة", "Hama")],
    "SA": [("الرياض", "Riyadh"), ("مكة المكرمة", "Mecca"), ("المدينة المنورة", "Medina"),
           ("جدة", "Jeddah"), ("الدمام", "Dammam")],
    "TR": [("إسطنبول", "Istanbul"), ("أنقرة", "Ankara"), ("إزمير", "Izmir"),
           ("بورصة", "Bursa")],
    "JO": [("عمّان", "Amman"), ("إربد", "Irbid"), ("الزرقاء", "Zarqa")],
    "LB": [("بيروت", "Beirut"), ("طرابلس", "Tripoli"), ("صيدا", "Sidon")],
    "PS": [("القدس", "Jerusalem"), ("غزة", "Gaza"), ("نابلس", "Nablus"),
           ("الخليل", "Hebron")],
    "KW": [("مدينة الكويت", "Kuwait City"), ("حولي", "Hawalli")],
    "TN": [("تونس", "Tunis"), ("صفاقس", "Sfax"), ("القيروان", "Kairouan")],
    "MA": [("الرباط", "Rabat"), ("الدار البيضاء", "Casablanca"), ("فاس", "Fez"),
           ("مراكش", "Marrakesh")],
    "YE": [("صنعاء", "Sanaa"), ("عدن", "Aden"), ("تعز", "Taiz")],
    "AE": [("أبوظبي", "Abu Dhabi"), ("دبي", "Dubai"), ("الشارقة", "Sharjah")],
    "QA": [("الدوحة", "Doha")],
    "BH": [("المنامة", "Manama")],
    "OM": [("مسقط", "Muscat"), ("صلالة", "Salalah")],
    "SD": [("الخرطوم", "Khartoum"), ("أم درمان", "Omdurman")],
    "LY": [("طرابلس", "Tripoli"), ("بنغازي", "Benghazi")],
    "DZ": [("الجزائر", "Algiers"), ("وهران", "Oran"), ("قسنطينة", "Constantine")],
    "IR": [("طهران", "Tehran"), ("أصفهان", "Isfahan"), ("تبريز", "Tabriz")],
    "GB": [("لندن", "London"), ("مانشستر", "Manchester")],
    "FR": [("باريس", "Paris"), ("ليون", "Lyon")],
    "DE": [("برلين", "Berlin"), ("ميونخ", "Munich")],
    "US": [("نيويورك", "New York"), ("شيكاغو", "Chicago"), ("ميشيغان", "Michigan"),
           ("لوس أنجلوس", "Los Angeles"), ("هيوستن", "Houston"), ("بوسطن", "Boston")],
    # ---------- remaining countries of the vocabulary: real cities, so no
    # ---------- synthetic "City of <country>" placeholder ever reaches the data
    "AF": [("كابول", "Kabul"), ("هرات", "Herat"), ("مزار الشريف", "Mazar-i-Sharif"),
           ("قندهار", "Kandahar"), ("بلخ", "Balkh")],
    "AT": [("فيينا", "Vienna"), ("غراتس", "Graz"), ("سالزبورغ", "Salzburg"),
           ("إنسبروك", "Innsbruck")],
    "AU": [("سيدني", "Sydney"), ("ملبورن", "Melbourne"), ("بريسبان", "Brisbane"),
           ("بيرث", "Perth"), ("أديلايد", "Adelaide")],
    "BE": [("بروكسل", "Brussels"), ("أنتويرب", "Antwerp"), ("غنت", "Ghent"),
           ("لييج", "Liège")],
    "CA": [("تورونتو", "Toronto"), ("مونتريال", "Montreal"), ("فانكوفر", "Vancouver"),
           ("أوتاوا", "Ottawa"), ("هاليفاكس", "Halifax")],
    "CH": [("زيورخ", "Zurich"), ("جنيف", "Geneva"), ("برن", "Bern"), ("بازل", "Basel")],
    "CN": [("بكين", "Beijing"), ("شنغهاي", "Shanghai"), ("قوانغتشو", "Guangzhou"),
           ("شيان", "Xi'an"), ("كاشغر", "Kashgar")],
    "CZ": [("براغ", "Prague"), ("برنو", "Brno"), ("أولوموتس", "Olomouc")],
    "DK": [("كوبنهاغن", "Copenhagen"), ("آرهوس", "Aarhus"), ("أودنسه", "Odense")],
    "ES": [("مدريد", "Madrid"), ("برشلونة", "Barcelona"), ("غرناطة", "Granada"),
           ("إشبيلية", "Seville"), ("قرطبة", "Cordoba"), ("طليطلة", "Toledo")],
    "ET": [("أديس أبابا", "Addis Ababa"), ("هرر", "Harar"), ("غوندار", "Gondar"),
           ("لاليبيلا", "Lalibela")],
    "FI": [("هلسنكي", "Helsinki"), ("توركو", "Turku"), ("تامبيري", "Tampere")],
    "GR": [("أثينا", "Athens"), ("سالونيك", "Thessaloniki"), ("كريت", "Crete"),
           ("رودس", "Rhodes")],
    "HU": [("بودابست", "Budapest"), ("دبرتسن", "Debrecen"), ("بيتش", "Pécs")],
    "ID": [("جاكرتا", "Jakarta"), ("سورابايا", "Surabaya"), ("باندونغ", "Bandung"),
           ("آتشيه", "Aceh"), ("ماكاسار", "Makassar")],
    "IE": [("دبلن", "Dublin"), ("كورك", "Cork"), ("غالواي", "Galway")],
    "IN": [("دلهي", "Delhi"), ("مومباي", "Mumbai"), ("حيدر آباد", "Hyderabad"),
           ("لكنو", "Lucknow"), ("كلكتا", "Kolkata"), ("عليكرة", "Aligarh")],
    "IT": [("روما", "Rome"), ("ميلانو", "Milan"), ("نابولي", "Naples"),
           ("فلورنسا", "Florence"), ("البندقية", "Venice"), ("باليرمو", "Palermo"),
           ("بولونيا", "Bologna")],
    "JP": [("طوكيو", "Tokyo"), ("كيوتو", "Kyoto"), ("أوساكا", "Osaka")],
    "KE": [("نيروبي", "Nairobi"), ("مومباسا", "Mombasa"), ("كيسومو", "Kisumu")],
    "KR": [("سول", "Seoul"), ("بوسان", "Busan"), ("إنتشون", "Incheon")],
    "ML": [("باماكو", "Bamako"), ("تمبكتو", "Timbuktu"), ("غاو", "Gao"),
           ("جني", "Djenné")],
    "MY": [("كوالالمبور", "Kuala Lumpur"), ("بينانغ", "Penang"), ("جوهور", "Johor")],
    "NG": [("لاغوس", "Lagos"), ("كانو", "Kano"), ("أبوجا", "Abuja"),
           ("إبادان", "Ibadan")],
    "NL": [("أمستردام", "Amsterdam"), ("لاهاي", "The Hague"), ("لايدن", "Leiden"),
           ("أوترخت", "Utrecht"), ("روتردام", "Rotterdam")],
    "NO": [("أوسلو", "Oslo"), ("بيرغن", "Bergen"), ("تروندهايم", "Trondheim")],
    "NZ": [("أوكلاند", "Auckland"), ("ويلينغتون", "Wellington"), ("كرايست تشيرش", "Christchurch")],
    "PK": [("لاهور", "Lahore"), ("كراتشي", "Karachi"), ("بيشاور", "Peshawar"),
           ("ملتان", "Multan"), ("إسلام آباد", "Islamabad")],
    "PL": [("وارسو", "Warsaw"), ("كراكوف", "Kraków"), ("غدانسك", "Gdańsk")],
    "PT": [("لشبونة", "Lisbon"), ("بورتو", "Porto"), ("كويمبرا", "Coimbra"),
           ("فارو", "Faro")],
    "RO": [("بوخارست", "Bucharest"), ("كلوج", "Cluj"), ("ياش", "Iași")],
    "RS": [("بلغراد", "Belgrade"), ("نوفي ساد", "Novi Sad"), ("نिश", "Niš")],
    "RU": [("موسكو", "Moscow"), ("سانت بطرسبرغ", "Saint Petersburg"),
           ("قازان", "Kazan"), ("داغستان", "Dagestan")],
    "SE": [("ستوكهولم", "Stockholm"), ("غوتنبرغ", "Gothenburg"), ("أوبسالا", "Uppsala")],
    "SN": [("داكار", "Dakar"), ("سانت لويس", "Saint-Louis"), ("تمباكوندا", "Tambacounda")],
    "SO": [("مقديشو", "Mogadishu"), ("هرجيسا", "Hargeisa"), ("بوصاصو", "Bosaso")],
    "TD": [("أنجمينا", "N'Djamena"), ("أبشي", "Abéché"), ("سارة", "Sarh")],
    "ZA": [("كيب تاون", "Cape Town"), ("جوهانسبرغ", "Johannesburg"), ("ديربان", "Durban"),
           ("بريتوريا", "Pretoria")],
    "BR": [("ساو باولو", "São Paulo"), ("ريو دي جانيرو", "Rio de Janeiro"),
           ("سالفادور", "Salvador"), ("ريسيفي", "Recife")],
    "UA": [("كييف", "Kyiv"), ("خاركيف", "Kharkiv"), ("أوديسا", "Odesa"),
           ("لفيف", "Lviv")],
    "DJ": [("جيبوتي", "Djibouti City"), ("علي صبيح", "Ali Sabieh"), ("تاجورة", "Tadjoura")],
    "KM": [("موروني", "Moroni"), ("موتسامودو", "Mutsamudu"), ("فومبوني", "Fomboni")],
    "MR": [("نواكشوط", "Nouakchott"), ("نواذيبو", "Nouadhibou"), ("روصو", "Rosso"),
           ("وادان", "Ouadane"), ("شنقيط", "Chinguetti")],
}

# used only for vocabulary countries that have no city list above: real-name
# shapes, never a "City of <country>" placeholder
GENERIC_CITY_NAMES = [
    ("العاصمة", "Capital City"), ("الميناء", "Port City"), ("الواحة", "Oasis Town"),
    ("القلعة", "Citadel Town"), ("السوق", "Market Town"), ("الجامعة", "University Town"),
]

DISTRICT_PATTERNS = [
    ("حي {city}", "{city} district"), ("المركز التاريخي", "historic centre"),
    ("الضاحية الشمالية", "northern suburb"), ("الضاحية الجنوبية", "southern suburb"),
    ("الحي الجامعي", "university quarter"), ("الحي التجاري", "commercial quarter"),
]

INSTITUTION_PATTERNS = [
    ("جامعة {city}", "University of {city}", "university"),
    ("كلية الآداب في {city}", "Faculty of Arts in {city}", "faculty"),
    ("معهد الدراسات الشرقية في {city}", "Institute of Oriental Studies in {city}", "research_institute"),
    ("المكتبة الوطنية في {city}", "National Library of {city}", "library"),
    ("دار الوثائق في {city}", "National Archives of {city}", "archive"),
    ("مركز البحوث التاريخية في {city}", "Centre for Historical Research in {city}", "research_centre"),
    ("جمعية المؤرخين في {city}", "Historians' Association of {city}", "association"),
    ("مؤسسة التراث في {city}", "Heritage Foundation of {city}", "foundation"),
    ("متحف {city} الوطني", "{city} National Museum", "museum"),
    ("وزارة الثقافة في {city}", "Ministry of Culture in {city}", "ministry"),
    ("مجمع اللغة العربية في {city}", "Arabic Language Academy of {city}", "academy"),
    ("دار الكتب والوثائق في {city}", "House of Books and Documents in {city}", "library"),
    ("قسم التاريخ في جامعة {city}", "Department of History, {city} University", "department"),
    ("المعهد التقني العالي في {city}", "Higher Technical Institute of {city}", "college"),
    ("معهد المخطوطات في {city}", "Manuscript Institute of {city}", "research_institute"),
]

EVENT_PATTERNS = [
    ("مؤتمر {topic} السنوي في {city}", "Annual {topic} Conference in {city}", "conference"),
    ("ندوة {topic} في {city}", "{topic} Seminar in {city}", "seminar"),
    ("ورشة عمل عن {topic}", "Workshop on {topic}", "workshop"),
    ("معرض {topic} في {city}", "{topic} Exhibition in {city}", "exhibition"),
    ("حلقة نقاشية عن {topic}", "Round table on {topic}", "seminar"),
    ("افتتاح {institution}", "Inauguration of {institution}", "ceremony"),
    ("تأسيس {institution}", "Founding of {institution}", "milestone"),
    ("إطلاق مشروع {topic}", "Launch of the {topic} project", "project_launch"),
]
TOPICS = [
    ("التراث المخطوط", "manuscript heritage"), ("التاريخ الاجتماعي", "social history"),
    ("الأعلام والتراجم", "biographical studies"), ("الرقمنة الأرشيفية", "archival digitisation"),
    ("اللغة العربية", "the Arabic language"), ("تاريخ المدن", "urban history"),
    ("الاستشراق", "Orientalism"), ("الوثائق العثمانية", "Ottoman documents"),
    ("النسخ والتحقيق", "textual criticism"), ("الذاكرة الشفوية", "oral memory"),
]

SOURCE_PATTERNS = [
    ("سجل الأعلام في {city}", "Biographical register of {city}", "biographical_dictionary"),
    ("مجلة {institution} - العدد {n}", "Journal of {institution} - issue {n}", "journal_article"),
    ("تقرير {institution} السنوي {year}", "Annual report of {institution} {year}", "report"),
    ("الأرشيف الوطني - ملف {n}", "National archive - file {n}", "archival_document"),
    ("مقابلة شفهية مع {person}", "Oral interview with {person}", "interview"),
    ("رسالة جامعية عن {topic}", "Dissertation on {topic}", "thesis"),
    ("كتاب {topic} — {publisher}", "Book on {topic} — {publisher}", "book"),
    ("موقع {institution} الإلكتروني", "{institution} website", "website"),
    ("مخطوط رقم {n} — {city}", "Manuscript no. {n} — {city}", "manuscript"),
    ("شهادة رسمية من {institution}", "Official certificate from {institution}", "certificate"),
]
PUBLISHERS = ["دار الكتب العلمية", "مطبعة الجامعة", "دار الشؤون الثقافية",
              "المجلس الأعلى للثقافة", "Dar al-Kutub", "University Press",
              "المعهد الألماني للأبحاث الشرقية"]

POSITION_TITLES = [
    ("أستاذ", "Professor"), ("أستاذ مشارك", "Associate Professor"),
    ("أستاذ مساعد", "Assistant Professor"), ("مدرّس", "Lecturer"),
    ("باحث", "Researcher"), ("باحث أول", "Senior Researcher"),
    ("مدير", "Director"), ("رئيس قسم", "Head of Department"),
    ("عميد", "Dean"), ("أمين المكتبة", "Librarian"),
    ("أمين الأرشيف", "Archivist"), ("محرر", "Editor"),
    ("مستشار", "Advisor"), ("منسّق مشروع", "Project Coordinator"),
    ("طالب دراسات عليا", "PhD candidate"), ("معيد", "Teaching Assistant"),
]

# these must be codes that exist in the relation_direction / relationship_type lookups
REL_PERSON_PERSON = ["teacher_of", "colleague_of", "collaborator_of", "student_of",
                     "relative_of", "corresponded_with", "supervised_by", "co_author_of",
                     "rival_of", "child_of"]
REL_PERSON_INST = ["member_of", "employed_by", "director_of", "founder_of",
                   "graduated_from", "board_member_of", "affiliated_with"]
REL_INST_INST = ["partner_of", "affiliated_with", "succeeded_by", "employs",
                 "founded_by", "contains"]
REL_PERSON_PLACE = ["located_in", "affiliated_with", "contains"]
REL_PERSON_EVENT = ["participated_in", "directed_by", "had_participant"]
REL_INST_EVENT = ["participated_in", "founded_by"]
REL_PLACE_PLACE = ["located_in", "contains"]
REL_DIRECTIONS = ["directed", "symmetric"]

TAG_POOL = [
    ("manuscripts", "المخطوطات"), ("oral-history", "التاريخ الشفوي"),
    ("ottoman", "عثماني"), ("modern", "حديث"), ("colonial", "استعماري"),
    ("women", "نساء"), ("education", "تعليم"), ("sufism", "التصوف"),
    ("fiqh", "الفقه"), ("poetry", "الشعر"), ("medicine", "الطب"),
    ("astronomy", "الفلك"), ("geography", "الجغرافيا"), ("archives", "الأرشيفات"),
    ("biography", "التراجم"), ("digitisation", "الرقمنة"), ("rare-books", "الكتب النادرة"),
    ("periodicals", "الدوريات"), ("maps", "الخرائط"), ("inscriptions", "النقوش"),
]
EXT_SCHEMES = [("VIAF", "https://viaf.org/viaf/{v}"), ("Wikidata", "https://www.wikidata.org/wiki/{v}"),
               ("ISNI", "https://isni.org/isni/{v}"), ("GND", "https://d-nb.info/gnd/{v}"),
               ("LOC", "https://id.loc.gov/authorities/{v}")]

NOTES = [
    "سجل تجريبي مُولَّد آلياً لاختبار الواجهة — ليس ادّعاءً تاريخياً.",
    "Synthetic record generated for interface testing — not a historical claim.",
    "بيانات تجريبية: الحقول مأخوذة من قوائم مرجعية حقيقية والقيم مُولَّدة.",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _pick(rng: random.Random, seq: Sequence[Any]) -> Any:
    return seq[rng.randrange(len(seq))]


def _chance(rng: random.Random, p: float) -> bool:
    return rng.random() < p


def _date(rng: random.Random, start_year: int = 1920, end_year: int = 2025) -> str:
    y = rng.randint(start_year, end_year)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _iso(day_offset: int = 0) -> str:
    base = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)
    return base.strftime("%Y-%m-%dT%H:%M:%SZ")


class CodeAllocator:
    """Allocate codes in bulk without a SELECT per row."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.rows: dict[str, dict[str, Any]] = {}
        self.next: dict[str, int] = {}

    def _row(self, entity: str) -> dict[str, Any]:
        if entity not in self.rows:
            db.ensure_sequence(self.conn, entity)
            row = dict(self.conn.execute(
                "SELECT * FROM sequence WHERE entity_type=?", (entity,)).fetchone())
            self.rows[entity] = row
            self.next[entity] = int(row["next_value"])
        return self.rows[entity]

    def take(self, entity: str) -> str:
        row = self._row(entity)
        number = self.next[entity]
        self.next[entity] = number + 1
        return db.format_code(row, number)

    def flush(self) -> None:
        for entity, number in self.next.items():
            self.conn.execute("UPDATE sequence SET next_value=? WHERE entity_type=?",
                              (number, entity))


def _lookup_map(conn: sqlite3.Connection, domain: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT id, code, label_en, label_ar FROM lookup WHERE domain=? ORDER BY sort_order, id",
        (domain,)))


def _vocab(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    domains = [r["domain"] for r in conn.execute(
        "SELECT DISTINCT domain FROM lookup ORDER BY domain")]
    return {d: _lookup_map(conn, d) for d in domains}


def _ids(rows: Sequence[sqlite3.Row], codes: Sequence[str] | None = None) -> list[int]:
    if codes is None:
        return [r["id"] for r in rows]
    wanted = set(codes)
    return [r["id"] for r in rows if r["code"] in wanted]


# ---------------------------------------------------------------------------
# the generator
# ---------------------------------------------------------------------------
PROFILES = {
    "small":   dict(persons=300, institutions=60, places=120, sources=150, events=80,
                    rel_per_person=1.6, positions_per_person=0.6, citations_per_record=0.35),
    "large":   dict(persons=5_000, institutions=900, places=1_600, sources=2_500, events=1_200,
                    rel_per_person=2.4, positions_per_person=1.0, citations_per_record=0.5),
    "huge":    dict(persons=20_000, institutions=3_000, places=5_000, sources=9_000, events=4_000,
                    rel_per_person=2.8, positions_per_person=1.2, citations_per_record=0.6),
}


def generate(
    conn: sqlite3.Connection,
    *,
    profile: str | None = "large",
    persons: int | None = None,
    institutions: int | None = None,
    places: int | None = None,
    sources: int | None = None,
    events: int | None = None,
    rel_per_person: float | None = None,
    seed: int = 20261101,
    actor: str = "bulk-generator",
    progress: bool = True,
) -> dict[str, int]:
    """Append a large synthetic dataset. Returns a dict of inserted counts."""
    cfg = dict(PROFILES.get(profile or "large", PROFILES["large"]))
    for key, val in (("persons", persons), ("institutions", institutions), ("places", places),
                     ("sources", sources), ("events", events),
                     ("rel_per_person", rel_per_person)):
        if val is not None:
            cfg[key] = val
    rng = random.Random(seed)
    V = _vocab(conn)
    codes = CodeAllocator(conn)
    ts = db.now()
    counts: dict[str, int] = {}

    def say(msg: str) -> None:
        if progress:
            print(f"[bulk] {msg}", flush=True)

    L = lambda d, c: next((r["id"] for r in V.get(d, []) if r["code"] == c), None)  # noqa: E731
    status_ids = _ids(V["record_status"])
    auth_ids = _ids(V["authentication_level"])
    doc_ids = _ids(V["documentation_level"])
    prec_ids = _ids(V["date_precision"])
    country_rows = V["country"]
    rel_type_rows = V["relationship_type"]
    tax = {
        "person_classification": _ids(V["person_classification"]),
        "person_status": _ids(V["person_status"]),
        "place_type": _ids(V["place_type"]),
        "geo_precision": _ids(V["geo_precision"]),
        "institution_type": _ids(V["institution_type"]),
        "institution_subcategory": _ids(V["institution_subcategory"]),
        "governance_system": _ids(V["governance_system"]),
        "event_type": _ids(V["event_type"]),
        "source_type": _ids(V["source_type"]),
        "source_reliability": _ids(V["source_reliability"]),
        "relation_direction": _ids(V["relation_direction"]),
        "language": _ids(V["language"]),
    }
    lang_cols = [r["code"] for r in V["language"]]

    say(f"profile={profile or 'large'} persons={cfg['persons']} seed={seed}")

    # ---------------------------------------------------------------- places
    country_place: dict[int, int] = {}
    city_rows: list[tuple[int, str, str, int]] = []   # (id, ar, en, country_id)
    place_code_seq: list[str] = []
    place_id_seq: list[int] = []
    ptypes = tax["place_type"]

    def add_place(arr: dict[str, Any]) -> int:
        code = codes.take("place")
        row = {
            "code": code, "created_at": ts, "updated_at": ts, "created_by": actor,
            "updated_by": actor, "version": 1,
            **arr,
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = conn.execute(f"INSERT INTO place ({cols}) VALUES ({marks})", list(row.values()))
        pid = int(cur.lastrowid)
        place_id_seq.append(pid)
        place_code_seq.append(code)
        return pid

    for crow in country_rows:
        cid = crow["id"]
        name_ar = crow["label_ar"] or crow["label_en"]
        name_en = crow["label_en"] or name_ar
        pid = add_place({
            "name_ar": name_ar, "name_en": name_en, "name_original": name_en,
            "name_original_lang": "en",
            "place_type_id": L("place_type", "country") or _pick(rng, ptypes),
            "country_id": cid,
            "record_status_id": L("record_status", "verified") or _pick(rng, status_ids),
        })
        country_place[cid] = pid

    wanted_cities = max(len(country_rows), cfg["places"] // 3)
    # a name must be unique inside its own country branch: re-drawing an existing
    # name is exactly what produced five identical "City of …" siblings
    used_in_country: dict[int, set[str]] = {}
    QUALIFIERS = [("الجديدة", "New"), ("القديمة", "Old"),
                  ("الشرقية", "East"), ("الغربية", "West")]

    def city_name(crow) -> tuple[str, str]:
        cid = crow["id"]
        taken = used_in_country.setdefault(cid, set())
        order = list(CITY_BY_COUNTRY.get(crow["code"]) or [])
        rng.shuffle(order)
        for ar0, en0 in order:
            if en0 not in taken:
                taken.add(en0)
                return ar0, en0
        for ar0, en0 in order:                    # every real city already used
            for q_ar, q_en in QUALIFIERS:
                candidate = f"{en0} ({q_en})"
                if candidate not in taken:
                    taken.add(candidate)
                    return f"{ar0} ({q_ar})", candidate
        # a vocabulary country with no city list of its own: keep the name
        # plausible instead of emitting "City of <country>" placeholders
        base_ar, base_en = _pick(rng, GENERIC_CITY_NAMES)
        n = sum(1 for v in taken if v.startswith(base_en))
        candidate = base_en if not n else f"{base_en} {n + 1}"
        taken.add(candidate)
        return (base_ar if not n else f"{base_ar} {n + 1}"), candidate

    made = 0
    while made < wanted_cities:
        crow = _pick(rng, country_rows)
        cid = crow["id"]
        ar, en = city_name(crow)
        pid = add_place({
            "name_ar": ar, "name_en": en, "name_original": en,
            "name_original_lang": "en",
            "place_type_id": L("place_type", "city") or _pick(rng, ptypes),
            "country_id": cid, "parent_place_id": country_place.get(cid),
            "latitude": round(rng.uniform(15.0, 42.0), 6),
            "longitude": round(rng.uniform(-10.0, 60.0), 6),
            "geo_precision": _pick(rng, tax["geo_precision"]),
            "city": en,
            "record_status_id": _pick(rng, status_ids),
            "authentication_id": _pick(rng, auth_ids),
        })
        city_rows.append((pid, ar, en, cid))
        made += 1

    # districts (third level) for a share of the cities
    for pid, ar, en, cid in list(city_rows):
        if not _chance(rng, 0.4):
            continue
        pat_ar, pat_en = _pick(rng, DISTRICT_PATTERNS)
        add_place({
            "name_ar": pat_ar.format(city=ar), "name_en": pat_en.format(city=en),
            "place_type_id": L("place_type", "district") or _pick(rng, ptypes),
            "country_id": cid, "parent_place_id": pid,
            "record_status_id": _pick(rng, status_ids),
        })
        if len(place_id_seq) >= cfg["places"]:
            break
    counts["place"] = len(place_id_seq)
    say(f"places: {counts['place']}")

    # ----------------------------------------------------------- institutions
    inst_ids: list[int] = []
    inst_names: list[tuple[str, str]] = []
    for _ in range(cfg["institutions"]):
        pid, city_ar, city_en, cid = _pick(rng, city_rows)
        pat_ar, pat_en, itype = _pick(rng, INSTITUTION_PATTERNS)
        name_ar = pat_ar.format(city=city_ar)
        name_en = pat_en.format(city=city_en)
        if _chance(rng, 0.25):
            name_ar += f" — فرع {_pick(rng, ['أ', 'ب', 'ج', 'د'])}"
            name_en += f" — branch {_pick(rng, ['A', 'B', 'C'])}"
        row = {
            "code": codes.take("institution"), "name_ar": name_ar, "name_en": name_en,
            "name_original": name_en, "name_original_lang": "en",
            "institution_type_id": L("institution_type", itype) or _pick(rng, tax["institution_type"]),
            "subcategory_id": _pick(rng, tax["institution_subcategory"]),
            "governance_id": _pick(rng, tax["governance_system"]),
            "country_id": cid, "place_id": pid, "city": city_en,
            "founded_date": _date(rng, 1850, 2020) if _chance(rng, 0.7) else None,
            "founded_precision": _pick(rng, prec_ids) if _chance(rng, 0.7) else None,
            "website": f"https://example.org/inst/{rng.randint(1000, 999999)}" if _chance(rng, 0.5) else None,
            "objectives": _pick(rng, [
                "دعم البحث التاريخي وتوثيق التراجم.", "حفظ المخطوطات وإتاحتها رقمياً.",
                "تدريب الباحثين على تحقيق النصوص.", "نشر الدوريات العلمية المحكّمة.",
            ]) if _chance(rng, 0.6) else None,
            "abbreviation": ("".join(w[0] for w in name_en.split()[:3])).upper() if _chance(rng, 0.4) else None,
            "record_status_id": _pick(rng, status_ids),
            "authentication_id": _pick(rng, auth_ids),
            "documentation_id": _pick(rng, doc_ids),
            "created_at": ts, "updated_at": ts, "created_by": actor, "updated_by": actor,
            "version": 1,
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = conn.execute(f"INSERT INTO institution ({cols}) VALUES ({marks})", list(row.values()))
        inst_ids.append(int(cur.lastrowid))
        inst_names.append((name_ar, name_en))
    counts["institution"] = len(inst_ids)
    say(f"institutions: {counts['institution']}")

    # ----------------------------------------------------------------- sources
    source_ids: list[int] = []
    for _ in range(cfg["sources"]):
        inst_ar, inst_en = _pick(rng, inst_names)
        pid, city_ar, city_en, cid = _pick(rng, city_rows)
        pat_en, stype = _pick(rng, [(p[1], p[2]) for p in SOURCE_PATTERNS])
        pat_ar = next(p[0] for p in SOURCE_PATTERNS if p[1] == pat_en)
        year = rng.randint(1900, 2026)
        fmt = dict(city=city_en, city_ar=city_ar, institution=inst_en,
                   institution_ar=inst_ar, n=rng.randint(1, 480), year=year,
                   topic=_pick(rng, TOPICS)[1], publisher=_pick(rng, PUBLISHERS),
                   person="أحد الباحثين")
        title_en = pat_en.format(**fmt)
        title_ar = pat_ar.format(**{**fmt, "city": city_ar, "institution": inst_ar,
                                    "topic": _pick(rng, TOPICS)[0]})
        row = {
            "code": codes.take("source"), "title": title_en, "title_ar": title_ar,
            "source_type_id": L("source_type", stype) or _pick(rng, tax["source_type"]),
            "publisher": _pick(rng, PUBLISHERS) if _chance(rng, 0.75) else None,
            "url": f"https://example.org/src/{rng.randint(1000, 9999999)}" if _chance(rng, 0.45) else None,
            "publication_date": f"{year:04d}" if _chance(rng, 0.4) else _date(rng, year, year),
            "publication_precision": L("date_precision", "year") if _chance(rng, 0.5) else _pick(rng, prec_ids),
            "access_date": _date(rng, 2018, 2026) if _chance(rng, 0.4) else None,
            "language": _pick(rng, lang_cols) if lang_cols else "ar",
            "isbn_issn": f"978-{rng.randint(0, 9)}-{rng.randint(1000, 9999)}-{rng.randint(10, 99)}-{rng.randint(0, 9)}"
                         if _chance(rng, 0.3) else None,
            "archive_reference": f"ARCH/{rng.randint(1, 90)}/{rng.randint(1, 999):03d}" if _chance(rng, 0.35) else None,
            "supported_information": _pick(rng, [
                "يدعم بيانات الميلاد والوفاة.", "يوثّق المناصب الأكاديمية.",
                "يؤكد العلاقات المؤسسية.", "يقدّم تفاصيل عن النشاط العام.",
            ]) if _chance(rng, 0.6) else None,
            "reliability_id": _pick(rng, tax["source_reliability"]),
            "record_status_id": _pick(rng, status_ids),
            "authentication_id": _pick(rng, auth_ids),
            "created_at": ts, "updated_at": ts, "created_by": actor, "updated_by": actor,
            "version": 1,
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = conn.execute(f"INSERT INTO source ({cols}) VALUES ({marks})", list(row.values()))
        source_ids.append(int(cur.lastrowid))
    counts["source"] = len(source_ids)
    say(f"sources: {counts['source']}")

    # ------------------------------------------------------------------ events
    event_ids: list[int] = []
    for _ in range(cfg["events"]):
        pid, city_ar, city_en, cid = _pick(rng, city_rows)
        pat_en, etype = _pick(rng, [(p[1], p[2]) for p in EVENT_PATTERNS])
        pat_ar = next(p[0] for p in EVENT_PATTERNS if p[1] == pat_en)
        inst_ar, inst_en = _pick(rng, inst_names)
        topic_ar, topic_en = _pick(rng, TOPICS)
        fmt_ar = dict(city=city_ar, institution=inst_ar, topic=topic_ar)
        fmt_en = dict(city=city_en, institution=inst_en, topic=topic_en)
        start = _date(rng, 1950, 2026)
        row = {
            "code": codes.take("event"), "title_ar": pat_ar.format(**fmt_ar),
            "title_en": pat_en.format(**fmt_en),
            "event_type_id": L("event_type", etype) or _pick(rng, tax["event_type"]),
            "start_date": start,
            "end_date": start if _chance(rng, 0.5) else _date(rng, int(start[:4]), 2026),
            "place_id": pid,
            "description": _pick(rng, [
                "فعالية علمية جمعت باحثين من عدة مؤسسات.",
                "نشاط ثقافي وثّق جزءاً من الذاكرة المحلية.",
                "حدث أكاديمي أُنتجت عنه وثائق منشورة.",
            ]),
            "significance": _pick(rng, ["أهمية توثيقية", "أهمية محلية", "أهمية إقليمية"]) if _chance(rng, 0.6) else None,
            "record_status_id": _pick(rng, status_ids),
            "authentication_id": _pick(rng, auth_ids),
            "documentation_id": _pick(rng, doc_ids),
            "created_at": ts, "updated_at": ts, "created_by": actor, "updated_by": actor,
            "version": 1,
        }
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = conn.execute(f"INSERT INTO event ({cols}) VALUES ({marks})", list(row.values()))
        event_ids.append(int(cur.lastrowid))
    counts["event"] = len(event_ids)
    say(f"events: {counts['event']}")

    # ----------------------------------------------------------------- persons
    person_ids: list[int] = []
    person_meta: list[tuple[int, str, str]] = []      # (id, name_ar, name_en)
    seen_names: set[str] = set()
    nat_ids = _ids(country_rows)
    attempt = 0
    while len(person_ids) < cfg["persons"] and attempt < cfg["persons"] * 12:
        attempt += 1
        female = _chance(rng, 0.38)
        given_ar, given_en = _pick(rng, GIVEN_F if female else GIVEN_M)
        if _chance(rng, 0.55):
            pat_ar, pat_en = _pick(rng, PATRONYMIC)
        else:
            pat_ar, pat_en = "", ""
        fam_ar, fam_en = _pick(rng, FAMILY)
        name_ar = " ".join(x for x in (given_ar, pat_ar, fam_ar) if x)
        name_en = " ".join(x for x in (given_en, pat_en, fam_en) if x)
        if name_ar in seen_names and _chance(rng, 0.85):
            continue
        seen_names.add(name_ar)
        birth = rng.randint(1900, 2003)
        alive = _chance(rng, 0.24)
        birth_place = _pick(rng, city_rows)
        nat = _pick(rng, nat_ids)
        inst = _pick(rng, inst_ids) if inst_ids and _chance(rng, 0.82) else None
        title_ar, title_en = _pick(rng, POSITION_TITLES)
        row: dict[str, Any] = {
            "code": codes.take("person"),
            "name_ar": name_ar, "name_en": name_en, "name_original": name_en,
            "name_original_lang": "en",
            "name_transliteration": name_en if _chance(rng, 0.5) else None,
            "birth_date": f"{birth:04d}" if _chance(rng, 0.3) else _date(rng, birth, birth),
            "birth_precision": L("date_precision", "year") if _chance(rng, 0.5) else _pick(rng, prec_ids),
            "death_date": (None if alive else _date(rng, birth + 18, min(birth + 96, 2026))),
            "death_precision": (None if alive else _pick(rng, prec_ids)),
            "nationality_id": nat,
            "birthplace_id": birth_place[0] if _chance(rng, 0.7) else None,
            "birthplace_text": None if _chance(rng, 0.7) else birth_place[2],
            "classification_id": _pick(rng, tax["person_classification"]),
            "current_status_id": None if not alive else _pick(rng, tax["person_status"]),
            "current_position": f"{title_en}" if _chance(rng, 0.6) else None,
            "affiliated_institution_id": inst,
            "affiliated_country_id": nat if _chance(rng, 0.7) else None,
            "declared_affiliation": f"{title_ar} — {title_en}" if _chance(rng, 0.45) else None,
            "affiliation_verified": 1 if (inst and _chance(rng, 0.5)) else 0,
            "affiliation_start": _date(rng, 1980, 2022) if inst and _chance(rng, 0.6) else None,
            "affiliation_end": _date(rng, 2000, 2026) if inst and _chance(rng, 0.25) else None,
            "website": f"https://example.org/p/{rng.randint(1000, 999999)}" if _chance(rng, 0.22) else None,
            "cv_url": f"https://example.org/cv/{rng.randint(1000, 99999)}.pdf" if _chance(rng, 0.12) else None,
            "social_accounts": f"@user{rng.randint(100, 99999)}" if _chance(rng, 0.25) else None,
            "public_activity": _pick(rng, [
                "شارك في مؤتمرات علمية وأشرف على رسائل جامعية.",
                "نشر أبحاثاً في دوريات محكّمة وأدار أرشيفاً وثائقياً.",
                "درّس التاريخ الحديث وأشرف على مشاريع رقمنة.",
                "عمل في تحقيق المخطوطات ونشر الفهارس.",
            ]) if _chance(rng, 0.55) else None,
            "institutional_relations": _pick(rng, [
                "عضو في جمعية المؤرخين.", "مستشار في مركز البحوث التاريخية.",
                "عضو مجلس إدارة مكتبة وطنية.",
            ]) if _chance(rng, 0.4) else None,
            "documentation_id": _pick(rng, doc_ids),
            "authentication_id": _pick(rng, auth_ids),
            "record_status_id": _pick(rng, status_ids),
            "researcher_notes": _pick(rng, NOTES) if _chance(rng, 0.5) else None,
            "primary_source_id": _pick(rng, source_ids) if source_ids and _chance(rng, 0.4) else None,
            "created_at": ts, "updated_at": ts, "created_by": actor, "updated_by": actor,
            "version": 1,
        }
        if _chance(rng, 0.03):     # a few soft-deleted rows so restore/trash is exercised
            row["deleted_at"] = _iso(-rng.randint(1, 300))
        if _chance(rng, 0.05):     # a few sparse records → completeness chart has range
            for k in ("name_en", "nationality_id", "classification_id", "documentation_id",
                      "authentication_id", "public_activity", "researcher_notes"):
                row[k] = None
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = conn.execute(f"INSERT INTO person ({cols}) VALUES ({marks})", list(row.values()))
        pid = int(cur.lastrowid)
        person_ids.append(pid)
        person_meta.append((pid, name_ar, name_en))
    counts["person"] = len(person_ids)
    say(f"persons: {counts['person']}")

    # ------------------------------------------------------------ positions
    pos_rows: list[tuple] = []
    for pid, _na, _ne, _name_en in person_meta:
        if not _chance(rng, cfg["positions_per_person"]):
            continue
        for slot in range(rng.randint(1, 3)):
            title_ar, title_en = _pick(rng, POSITION_TITLES)
            iid = _pick(rng, inst_ids) if inst_ids and _chance(rng, 0.88) else None
            start_year = rng.randint(1975, 2023)
            current = 1 if not slot and _chance(rng, 0.3) else 0
            pos_rows.append((
                pid, title_ar, title_en, iid,
                None if iid else "مؤسسة مستقلة", _pick(rng, nat_ids),
                _pick(rng, city_rows)[0], f"{start_year:04d}-01-01",
                None if current else f"{min(start_year + rng.randint(2, 18), 2026):04d}-01-01",
                L("date_precision", "year"), L("date_precision", "year"),
                current, slot, None, ts, ts,
            ))
            if _chance(rng, 0.6):
                break
    if pos_rows:
        conn.executemany(
            """INSERT INTO person_position (person_id, title_ar, title_en, institution_id,
                 institution_text, country_id, place_id, start_date, end_date,
                 start_precision, end_precision, is_current, sort_order, notes,
                 created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", pos_rows)
    counts["person_position"] = len(pos_rows)
    say(f"positions: {len(pos_rows)}")

    # ---------------------------------------------------------- relationships
    rel_lookup = {r["code"]: r["id"] for r in rel_type_rows}
    rel_rows: list[tuple] = []
    seen_rel: set[tuple] = set()

    def rel_type_id(code: str) -> int:
        if code not in rel_lookup:                    # fail loudly on a stale pool
            raise KeyError(f"unknown relationship type {code!r}")
        return rel_lookup[code]

    def add_rel(e1t: str, e1id: int, e2t: str, e2id: int, rtype: str,
                *, start: str | None = None, end: str | None = None) -> None:
        key = (e1t, e1id, rtype, e2t, e2id)
        if key in seen_rel or (e1t, e1id) == (e2t, e2id):
            return
        seen_rel.add(key)
        row = {
            "code": codes.take("relationship"),
            "entity1_type": e1t, "entity1_id": e1id,
            "relationship_type_id": rel_type_id(rtype),
            "entity2_type": e2t, "entity2_id": e2id,
            "direction": _pick(rng, REL_DIRECTIONS),
            "description": _pick(rng, [
                "علاقة موثقة في المصادر الأولية.", "إشارة متكررة في التراجم.",
                "مذكورة في الوثائق المؤسسية.", "علاقة مهنية موثقة جزئياً.",
            ]) if _chance(rng, 0.5) else None,
            "start_date": start, "end_date": end,
            "is_current": 1 if (end is None and _chance(rng, 0.3)) else 0,
            "source_id": _pick(rng, source_ids) if source_ids and _chance(rng, 0.35) else None,
            "authentication_id": _pick(rng, auth_ids),
            "record_status_id": _pick(rng, status_ids),
            "created_at": ts, "updated_at": ts, "created_by": actor, "updated_by": actor,
            "version": 1,
        }
        rel_rows.append(tuple(row.values()))

    rel_cols = """code, entity1_type, entity1_id, relationship_type_id, entity2_type, entity2_id,
        direction, description, start_date, end_date, is_current, source_id,
        authentication_id, record_status_id, created_at, updated_at, created_by, updated_by,
        version"""
    target = int(len(person_ids) * cfg["rel_per_person"])
    for pid, _ar, _en in person_meta:
        for _ in range(rng.randint(0, 4)):
            if len(rel_rows) >= target:
                break
            kind = rng.choices(
                ["person", "institution", "place", "event"],
                weights=[45, 33, 12, 10])[0]
            if kind == "person":
                other = _pick(rng, person_meta)[0]
                add_rel("person", pid, "person", other,
                        _pick(rng, REL_PERSON_PERSON),
                        start=_date(rng, 1950, 2020) if _chance(rng, 0.4) else None)
            elif kind == "institution" and inst_ids:
                add_rel("person", pid, "institution", _pick(rng, inst_ids),
                        _pick(rng, REL_PERSON_INST),
                        start=_date(rng, 1960, 2022) if _chance(rng, 0.5) else None)
            elif kind == "place":
                add_rel("person", pid, "place", _pick(rng, city_rows)[0],
                        _pick(rng, REL_PERSON_PLACE))
            elif kind == "event" and event_ids:
                add_rel("person", pid, "event", _pick(rng, event_ids),
                        _pick(rng, REL_PERSON_EVENT))
        if len(rel_rows) >= target:
            break

    # institution ↔ institution, institution ↔ event, place ↔ place (hierarchy as data)
    for iid in inst_ids:
        if _chance(rng, 0.45) and inst_ids:
            add_rel("institution", iid, "institution", _pick(rng, inst_ids),
                    _pick(rng, REL_INST_INST), start=_date(rng, 1950, 2020))
        if _chance(rng, 0.25) and event_ids:
            add_rel("institution", iid, "event", _pick(rng, event_ids), _pick(rng, REL_INST_EVENT))
    for pid, _ar, _en, _cid in city_rows:
        if _chance(rng, 0.3):
            add_rel("place", pid, "place", country_place.get(_cid) or pid, "located_in")

    if rel_rows:
        conn.executemany(
            f"INSERT INTO relationship ({rel_cols}) VALUES ({', '.join('?' * 19)})", rel_rows)
    counts["relationship"] = len(rel_rows)
    say(f"relationships: {len(rel_rows)}")

    # --------------------------------------------------- citations (source_link)
    link_rows: list[tuple] = []
    seen_link: set[tuple] = set()

    def cite(et: str, eid: int) -> None:
        sid = _pick(rng, source_ids)
        key = (et, eid, sid)
        if key in seen_link:
            return
        seen_link.add(key)
        link_rows.append((sid, et, eid, _pick(rng, [None, "name_ar", "birth_date",
                                                    "affiliated_institution_id", "current_position"]),
                          "استشهاد مُولَّد" if _chance(rng, 0.3) else None, ts))

    for pid, _ar, _en in person_meta[::2]:
        if _chance(rng, cfg["citations_per_record"]):
            for _ in range(rng.randint(1, 3)):
                cite("person", pid)
    for iid in inst_ids[::2]:
        if _chance(rng, cfg["citations_per_record"]):
            cite("institution", iid)
    for pid, _ar, _en, _cid in city_rows:
        if _chance(rng, cfg["citations_per_record"] * 0.7):
            cite("place", pid)
    if link_rows:
        conn.executemany(
            """INSERT OR IGNORE INTO evidence (source_id, entity_type, entity_id,
                 field_key, support_type, notes, created_at)
               VALUES (?,?,?,?,'supports',?,?)""", link_rows)
    counts["evidence"] = len(link_rows)
    say(f"citations: {len(link_rows)}")

    # -------------------------------------------------------------------- tags
    tag_rows = conn.execute("SELECT id FROM tag").fetchall()
    tag_ids = [r["id"] for r in tag_rows]
    if not tag_ids:                     # create the tag vocabulary on demand
        conn.executemany(
            "INSERT INTO tag (domain, label_en, label_ar, sort_order, created_at) VALUES (?,?,?,?,?)",
            [("topic", en, ar, i, ts) for i, (en, ar) in enumerate(TAG_POOL)])
        tag_ids = [r["id"] for r in conn.execute("SELECT id FROM tag").fetchall()]
    etag_rows = []
    for pid, _ar, _en in person_meta:
        if _chance(rng, 0.55):
            for tid in rng.sample(tag_ids, min(len(tag_ids), rng.randint(1, 3))):
                etag_rows.append(("person", pid, tid))
    for iid in inst_ids:
        if _chance(rng, 0.4):
            etag_rows.append(("institution", iid, _pick(rng, tag_ids)))
    if etag_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO entity_tag (entity_type, entity_id, tag_id) VALUES (?,?,?)",
            etag_rows)
    counts["entity_tag"] = len(etag_rows)
    say(f"tags: {len(etag_rows)}")

    # ------------------------------------------------------------ external ids
    ext_rows = []
    for pid, _ar, _en in person_meta:
        if _chance(rng, 0.3):
            scheme, tpl = _pick(rng, EXT_SCHEMES)
            value = str(rng.randint(10_000_000, 999_999_999))
            ext_rows.append(("person", pid, scheme, value, tpl.format(v=value), None, ts))
    for iid in inst_ids:
        if _chance(rng, 0.2):
            scheme, tpl = _pick(rng, EXT_SCHEMES)
            value = str(rng.randint(10_000_000, 999_999_999))
            ext_rows.append(("institution", iid, scheme, value, tpl.format(v=value), None, ts))
    if ext_rows:
        conn.executemany(
            """INSERT OR IGNORE INTO entity_external_id (entity_type, entity_id, scheme,
                 value, url, note, created_at) VALUES (?,?,?,?,?,?,?)""", ext_rows)
    counts["entity_external_id"] = len(ext_rows)
    say(f"external ids: {len(ext_rows)}")

    # --------------------------------------------------------- saved views/demo
    if not conn.execute("SELECT 1 FROM saved_view LIMIT 1").fetchone():
        import json as _json
        demo_views = [
            ("Verified persons", "person",
             {"record_status_id": {"in": ["verified", "published"]}}, None, None),
            ("Persons with an image", "person",
             {"image_url": {"not_empty": True}}, None, None),
            ("Multi-position scholars", "person",
             {"position_count": {"gte": 2}}, None, None),
            ("Institutions by country", "institution",
             {}, None, {"key": "country_name_en", "dir": "asc"}),
        ]
        for name, ent, filters, cols, sort in demo_views:
            conn.execute(
                """INSERT INTO saved_view (name, entity_type, filters, columns, sort,
                     is_shared, owner, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (name, ent, _json.dumps(filters, ensure_ascii=False),
                 _json.dumps(cols) if cols else None,
                 _json.dumps(sort) if sort else None, 1, actor, ts))
        counts["saved_view"] = len(demo_views)

    # ------------------------------------------------------------------- audit
    log_rows = []
    for et, ids_ in (("person", person_ids), ("institution", inst_ids),
                     ("source", source_ids), ("event", event_ids),
                     ("relationship", []), ("place", place_id_seq)):
        for eid in ids_:
            log_rows.append(("bulk", et, eid, None, "create", None, None, None, None,
                             "bulk dataset", actor, None, "generated by app.bulk", _iso(rng.randint(-400, 0))))
    if log_rows:
        conn.executemany(
            """INSERT INTO change_log (tx_id, entity_type, entity_id, entity_code, action,
                 field_key, field_label, old_value, new_value, reason, actor, reviewed_by,
                 notes, changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", log_rows)
    counts["change_log"] = len(log_rows)

    codes.flush()
    conn.commit()
    say("rebuilding the full-text index …")
    docs = db.rebuild_index(conn)
    conn.commit()
    say(f"indexed {docs} documents")

    # keep the SQLite planner happy after a large load
    try:
        conn.execute("ANALYZE")
        conn.commit()
    except sqlite3.DatabaseError:
        pass
    return counts


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts for every table that carries records."""
    out: dict[str, int] = {}
    for entity in ("person", "institution", "place", "relationship", "source", "event"):
        out[entity] = int(conn.execute(f"SELECT COUNT(*) c FROM {entity}").fetchone()["c"])
    for table in ("person_position", "source_link", "entity_tag", "entity_external_id",
                  "change_log", "attachment", "saved_view", "lookup"):
        out[table] = int(conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"])
    out["search_doc"] = int(conn.execute("SELECT COUNT(*) c FROM search_doc").fetchone()["c"])
    return out

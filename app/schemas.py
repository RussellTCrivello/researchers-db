"""
Entity metadata — ONE source of truth for the whole application.

Every screen (form, table, filter builder, column chooser, import mapper,
export template, report) is generated from the definitions below, so adding a
field or a whole new entity type is a change in this file only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# dates and moments
# ---------------------------------------------------------------------------
# A registry of historical records cannot insist on a full timestamp: "1912" is a
# legitimate value, and so is "c. 1900" or "1900s".  What *is* required is that a
# moment, when it is known, can be recorded — so every date column accepts
# ISO-8601 to the minute, and the helper functions below give every value a
# comparable position on one timeline (partial values expand downwards: a year
# starts on 1 January, 00:00).
_DATE_TIME_RE = re.compile(
    r"^(?P<year>\d{3,4})"
    r"(?:-(?P<month>\d{2})"
    r"(?:-(?P<day>\d{2})"
    r"(?:[T ](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.\d+)?)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?)?)?)?$"
)
_PARTIAL_DATE_RE = re.compile(
    r"^(\d{3,4}(-\d{2}(-\d{2})?)?|c\.\s?\d{3,4}s?|\d{3,4}s|\d{3,4}\?)"
    r"([T ]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:?\d{2})?)?$"
)
PARTIAL_DATE_RE = _PARTIAL_DATE_RE        # kept for callers that import the name
DATE_PRECISIONS = ("year", "month", "day", "minute")

# Fields that carry a *time of day* in the interface: the moment itself matters
# (an event starts at 09:30, a contract was signed at 14:00).  Every other date
# field still accepts a time over the API and on import — the picker simply does
# not ask for one by default.
TIME_AWARE_FIELDS = {
    ("event", "start_date"), ("event", "end_date"),
    ("relationship", "start_date"), ("relationship", "end_date"),
    ("source", "publication_date"), ("source", "access_date"),
    ("relationship", "last_review_date"),
}


def parse_date_value(value: Any) -> tuple[str | None, str, str | None]:
    """Normalise a date/moment.  Returns ``(stored, precision, error)``.

    Accepted: ``1950`` · ``1950-04`` · ``1950-04-12`` · ``1950-04-12 14:30`` ·
    ``1950-04-12T14:30Z`` · the legacy research forms ``c. 1900``, ``1900s``,
    ``1900?``.  A time is stored as ``YYYY-MM-DDTHH:MM`` (seconds when given) and
    a timezone suffix is dropped: the registry records wall-clock time, because a
    historical document never tells us the offset.
    """
    if value is None:
        return None, "year", None
    s = str(value).strip().replace("\u200f", "").replace("\u200e", "")
    if not s:
        return None, "year", None
    m = _DATE_TIME_RE.match(s)
    if not m:
        if re.match(r"^(c\.\s?\d{3,4}s?|\d{3,4}s|\d{3,4}\?)$", s):
            return s, "year", None          # circa / decade / uncertain, kept verbatim
        return None, "year", ("must be YYYY, YYYY-MM, YYYY-MM-DD, "
                             "YYYY-MM-DD HH:MM, 'c. YYYY', 'YYYYs' or 'YYYY?'")
    year = int(m.group("year"))
    if not 1 <= year <= 2999:
        return None, "year", "year must be between 1 and 2999"
    month = int(m.group("month")) if m.group("month") else None
    day = int(m.group("day")) if m.group("day") else None
    hour = int(m.group("hour")) if m.group("hour") else None
    minute = int(m.group("minute")) if m.group("minute") else None
    second = int(m.group("second")) if m.group("second") else None
    if month is not None and not 1 <= month <= 12:
        return None, "year", "month must be between 01 and 12"
    if day is not None and not 1 <= day <= 31:
        return None, "year", "day must be between 01 and 31"
    if hour is not None and not 0 <= hour <= 23:
        return None, "year", "hour must be between 00 and 23"
    if minute is not None and not 0 <= minute <= 59:
        return None, "year", "minute must be between 00 and 59"
    if second is not None and not 0 <= second <= 59:
        return None, "year", "second must be between 00 and 59"
    if day is not None and month is not None:
        import calendar
        if day > calendar.monthrange(year if year > 0 else 2000, month)[1]:
            return None, "year", "that day does not exist in that month"
    out = f"{year:04d}"
    precision = "year"
    if month is not None:
        out += f"-{month:02d}"
        precision = "month"
    if day is not None:
        out += f"-{day:02d}"
        precision = "day"
    if hour is not None:
        out += f"T{hour:02d}:{minute or 0:02d}"
        if second:
            out += f":{second:02d}"
        precision = "minute"
    return out, precision, None


def date_precision(value: Any) -> str:
    """How much of the moment is actually known: year · month · day · minute."""
    if value is None or str(value).strip() == "":
        return "year"
    return parse_date_value(value)[1]


def to_timestamp(value: Any) -> str:
    """Comparable ``YYYY-MM-DD HH:MM:SS`` for any accepted date form.

    Used for sorting and for every date filter, so that ``1912``, ``1912-04-12``
    and ``1912-04-12T14:30`` all sit on one timeline instead of comparing as
    strings.  Unknown values sort to the empty string (SQLite sorts NULL last,
    which is what the interface shows as "no date").
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    m = _DATE_TIME_RE.match(s)
    if not m:
        legacy = re.search(r"(\d{3,4})", s)      # c. 1900 / 1900s / 1900?
        if not legacy:
            return ""
        return f"{int(legacy.group(1)):04d}-01-01 00:00:00"
    year = int(m.group("year"))
    month = int(m.group("month") or 1)
    day = int(m.group("day") or 1)
    hour = int(m.group("hour") or 0)
    minute = int(m.group("minute") or 0)
    second = int(m.group("second") or 0)
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
URL_RE = re.compile(r"^(https?://|mailto:|/)[^\s]+$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------
@dataclass
class Field:
    key: str
    type: str                      # text | textarea | url | int | float | date | select | fk | bool | tags
    label_en: str
    label_ar: str
    group: str = "main"
    required: bool = False
    unique: bool = False
    max_len: int | None = None
    domain: str | None = None      # lookup domain for `select`
    ref: str | None = None         # entity key for `fk`
    tag_domain: str | None = None  # tag domain for `tags`
    help_en: str = ""
    help_ar: str = ""
    store: str = "id"              # select fields: store "id" or the vocabulary "code"
    multisearch: bool = True       # include in full-text index
    in_list: bool = True           # default column visibility
    filterable: bool = True
    sortable: bool = True
    read_only: bool = False
    system: bool = False
    placeholder_ar: str = ""
    placeholder_en: str = ""
    time: bool = False             # date fields: does the interface ask for a time?

    @property
    def col(self) -> str:
        return self.key


# ---------------------------------------------------------------------------
# helpers to build fields quickly
# ---------------------------------------------------------------------------
def F(key, type, en, ar, **kw) -> Field:
    return Field(key=key, type=type, label_en=en, label_ar=ar, **kw)


STATUS = lambda **kw: F("record_status_id", "select", "Record status", "حالة السجل",
                        domain="record_status", required=True, group="meta", **kw)
AUTH = lambda **kw: F("authentication_id", "select", "Authentication level", "مستوى التوثيق",
                      domain="authentication_level", group="meta", **kw)
DOC = lambda **kw: F("documentation_id", "select", "Documentation level", "مستوى التوثيق الوثائقي",
                     domain="documentation_level", group="meta", **kw)
PRIMARY_SOURCE = lambda **kw: F("primary_source_id", "fk", "Primary source", "المصدر الأساسي",
                                ref="source", group="meta", **kw)
NOTES = lambda **kw: F("researcher_notes", "textarea", "Researcher's notes", "ملاحظات الباحث",
                       group="meta", **kw)


def system_fields() -> list[Field]:
    return [
        F("created_at", "text", "Created", "تاريخ الإنشاء", group="system", read_only=True,
          in_list=False, filterable=True, system=True),
        F("created_by", "text", "Created by", "أنشأه", group="system", read_only=True,
          in_list=False, system=True),
        F("updated_at", "text", "Last updated", "آخر تحديث", group="system", read_only=True,
          system=True),
        F("updated_by", "text", "Updated by", "حدّثه", group="system", read_only=True,
          in_list=False, system=True),
        F("version", "int", "Version", "الإصدار", group="system", read_only=True,
          in_list=False, system=True),
        F("deleted_at", "text", "Deleted at", "تاريخ الحذف", group="system", read_only=True,
          in_list=False, system=True),
    ]


def code_field(prefix_hint: str) -> Field:
    return F("code", "text", "Identification number", "الرقم التعريفي", group="identity",
             required=True, unique=True, max_len=64, sortable=True,
             help_en=f"Auto-generated from the {prefix_hint} numbering rule; can be overridden.",
             help_ar=f"يُولَّد تلقائياً وفق قاعدة ترقيم {prefix_hint} ويمكن تعديله يدوياً.")


# ---------------------------------------------------------------------------
# EntitySpec
# ---------------------------------------------------------------------------
@dataclass
class EntitySpec:
    key: str
    table: str
    label_en: str
    label_ar: str
    plural_en: str
    plural_ar: str
    icon: str
    code_prefix: str
    fields: list[Field]
    title_fields: list[str]                 # fields used to display the record
    name_fields: tuple[str, ...] = ("name_en", "name_ar")
    default_sort: str = "id"
    default_order: str = "desc"
    tags: tuple[str, ...] = ()
    has_positions: bool = False
    children: tuple[str, ...] = ()
    index_builder: Callable | None = None
    description_en: str = ""
    description_ar: str = ""

    # -- derived helpers ---------------------------------------------------
    def field(self, key: str) -> Field | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def scalar_fields(self) -> list[Field]:
        return [f for f in self.fields if not f.system and f.key not in ("code",)
                and f.type != "tags"]

    @property
    def writable_fields(self) -> list[Field]:
        return [f for f in self.fields if not f.read_only and f.type != "tags"]

    @property
    def filterable_fields(self) -> list[Field]:
        return [f for f in self.fields if f.filterable]

    def labels(self, lang: str = "en") -> dict[str, str]:
        return {f.key: (f.label_ar if lang == "ar" and f.label_ar else f.label_en)
                for f in self.fields}

    def title(self, row: dict) -> str:
        for k in self.name_fields:
            if row.get(k):
                return str(row[k])
        return row.get("code") or str(row.get("id") or "")

    def build_index_rows(self, conn) -> list[dict]:
        """Default: one search document per row, built from multisearch fields."""
        if self.index_builder:
            return self.index_builder(conn)
        rows = conn.execute(f"SELECT * FROM {self.table} WHERE deleted_at IS NULL").fetchall()
        docs = []
        # one lookup-map read per entity (not per row): indexing 20 000 records went
        # from ~14 s to ~2 s with this single line of caching
        lookups = load_lookup_map(conn)
        for r in rows:
            d = dict(r)
            body = [d.get(f.key) for f in self.fields
                    if f.multisearch and f.type in ("text", "textarea", "tags")]
            # resolve lookup labels + FK names so search finds "University of Baghdad"
            body += [label for label in resolve_all_labels(conn, self, d, lookups).values()]
            docs.append({"id": d["id"], "code": d.get("code"),
                         "title": self.title(d), "body": body})
        return docs


# ---------------------------------------------------------------------------
# Label / reference resolution (used by the API and by the index builder)
# ---------------------------------------------------------------------------
def load_lookup_map(conn) -> dict[int, dict]:
    rows = conn.execute("SELECT id, domain, code, label_en, label_ar, color, meta FROM lookup").fetchall()
    return {r["id"]: dict(r) for r in rows}


REF_TITLE_SQL = {
    "source": "COALESCE(NULLIF(title,''), code)",
    "place": "COALESCE(NULLIF(name_en,''), NULLIF(name_ar,''), code)",
    "institution": "COALESCE(NULLIF(name_en,''), NULLIF(name_ar,''), code)",
    "person": "COALESCE(NULLIF(name_en,''), NULLIF(name_ar,''), code)",
    "event": "COALESCE(NULLIF(title_en,''), NULLIF(title_ar,''), code)",
}


def resolve_ref(conn, ref: str, ref_id: int | None) -> dict | None:
    if not ref_id:
        return None
    table = ENTITIES[ref].table if ref in ENTITIES else ref
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (ref_id,)).fetchone()
    if not row:
        return {"id": ref_id, "code": None, "name_en": None, "name_ar": None, "label": f"#{ref_id}"}
    d = dict(row)
    name_en = d.get("name_en") or d.get("title_en") or d.get("title")
    name_ar = d.get("name_ar") or d.get("title_ar")
    return {"id": ref_id, "code": d.get("code"), "name_en": name_en, "name_ar": name_ar,
            "label": name_en or name_ar or d.get("code") or f"#{ref_id}"}


def resolve_all_labels(conn, spec: EntitySpec, row: dict,
                       lookups: dict[int, dict] | None = None) -> dict[str, str]:
    """Return {'field_key': 'human readable label'} for every select/fk field."""
    lookups = lookups if lookups is not None else load_lookup_map(conn)
    out = {}
    for f in spec.fields:
        val = row.get(f.key)
        if val in (None, ""):
            continue
        if f.type == "select" and f.store == "code" and isinstance(val, str):
            lk = next((cand for cand in lookups.values()
                       if cand["domain"] == f.domain and cand["code"] == val), None)
            if lk:
                out[f.key] = f'{lk["label_en"]} / {lk["label_ar"]}'
        elif f.type == "select" and isinstance(val, int):
            lk = lookups.get(val)
            if lk:
                out[f.key] = lk["label_en"] if lk["label_en"] == lk["label_ar"] else \
                    f'{lk["label_en"]} / {lk["label_ar"]}'
        elif f.type == "fk":
            ref = resolve_ref(conn, f.ref, val)
            if ref:
                out[f.key] = ref["label"]
    return out


# ---------------------------------------------------------------------------
# ENTITY DEFINITIONS
# ---------------------------------------------------------------------------

def _own_position_fields() -> list[Field]:
    """The geographic position of a record, kept for that record alone.

    Linking a person, an institution or an event to a named place is an
    association — it never assigns the place's coordinates to the record.
    The record's own point is typed or picked on the map independently, and
    several records associated with one place hold several distinct points.
    The provenance fields mirror place: a coordinate is only as good as the
    way it was obtained.
    """
    return [
        F("latitude", "float", "Latitude", "خط العرض", group="geo", in_list=False,
          help_en="This record's own position, independent of any linked place. "
                  "Type the latitude or pick the point on the map beside it — "
                  "linking a place never assigns its coordinates here.",
          help_ar="موقع هذا السجل الخاص، مستقل عن أي مكان مرتبط. أدخل خط العرض أو "
                  "حدّد النقطة على الخريطة بجانبه — ربط المكان لا يُسند إحداثياته إلى هنا."),
        F("longitude", "float", "Longitude", "خط الطول", group="geo", in_list=False,
          help_en="The longitude of this record's own position. The same named "
                  "place may anchor many different points — each record keeps its own.",
          help_ar="خط الطول لموقع هذا السجل الخاص. قد يحتضن المكان نفسه نقاطاً "
                  "مختلفة كثيرة — لكل سجل إحداثيته الخاصة."),
        F("geo_precision", "select", "Coordinate precision", "دقة الإحداثيات",
          domain="geo_precision", group="geo", in_list=False,
          help_en="How close the point is to the true position: exact point, "
                  "approximate, centroid of an area, or uncertain.",
          help_ar="مدى قرب النقطة من الموقع الحقيقي: نقطة دقيقة، أو تقريبية، أو "
                  "مركز منطقة، أو غير مؤكدة."),
        F("geocoding_method", "select", "How the point was obtained", "طريقة تحديد النقطة",
          domain="geocoding_method", group="geo", in_list=False,
          help_en="Filled automatically when the point is typed or picked on the map.",
          help_ar="يُملأ تلقائياً عند إدخال النقطة أو اختيارها على الخريطة."),
        F("geo_uncertainty_m", "float", "Uncertainty radius (metres)",
          "نصف قطر عدم اليقين (متر)", group="geo", in_list=False,
          help_en="The radius the true position could lie within.",
          help_ar="نصف القطر الذي قد يقع فيه الموقع الحقيقي."),
        F("geometry_source", "text", "Point source", "مصدر النقطة", group="geo",
          in_list=False, max_len=120,
          help_en="Which map or source supplied the point (filled automatically on entry).",
          help_ar="الخريطة أو المصدر الذي أُخذت منه النقطة (يُملأ تلقائياً عند الإدخال)."),
    ]


person_fields: list[Field] = [
    code_field("person"),
    F("name_ar", "text", "Name in Arabic", "الاسم بالعربية", group="identity", required=True,
      max_len=250, placeholder_ar="الاسم الكامل", sortable=True),
    F("name_original", "text", "Name in original language", "الاسم باللغة الأصلية",
      group="identity", max_len=250),
    F("name_en", "text", "Name in English", "الاسم بالإنجليزية", group="identity",
      max_len=250, in_list=False),
    F("name_original_lang", "text", "Original name language", "لغة الاسم الأصلي",
      group="identity", in_list=False, help_en="BCP-47 or plain name, e.g. tr, fr, Ottoman Turkish",
      help_ar="رمز اللغة أو اسمها، مثال: tr، fr، التركية العثمانية"),
    F("name_transliteration", "text", "Transliteration", "النقل الحرفي للاسم",
      group="identity", in_list=False),
    F("image_url", "url", "Image link", "رابط الصورة", group="identity", in_list=False,
      help_en="Portrait URL or an uploaded /api/media/… path (shown in card and gallery views)",
      help_ar="رابط الصورة أو ملف مرفوع بصيغة /api/media/… (يظهر في البطاقات والمعرض)"),
    F("image_alt", "text", "Image alt text", "نص بديل للصورة", group="identity", in_list=False,
      help_en="Short description of the image for accessibility and captions",
      help_ar="وصف موجز للصورة لأغراض الوصول والترقيم"),
    F("birth_date", "date", "Date of birth", "تاريخ الميلاد", group="life", sortable=True),
    F("birth_precision", "select", "Birth date precision", "دقة تاريخ الميلاد",
      domain="date_precision", group="life", in_list=False),
    F("death_date", "date", "Date of death", "تاريخ الوفاة", group="life", sortable=True,
      in_list=False),
    F("death_precision", "select", "Death date precision", "دقة تاريخ الوفاة",
      domain="date_precision", group="life", in_list=False),
    F("nationality_id", "select", "Nationality", "الجنسية", domain="country", group="life"),
    F("birthplace_id", "fk", "Place of birth (record)", "مكان الميلاد (سجل)",
      ref="place", group="life", in_list=False),
    F("birthplace_text", "text", "Place of birth (as stated)", "مكان الميلاد (كما ورد)",
      group="life", max_len=250),
    F("classification_id", "select", "Occupation / classification", "المهنة / التصنيف",
      domain="person_classification", group="career"),
    F("current_status_id", "select", "Current status", "الحالة الحالية", domain="person_status",
      group="career"),
    F("current_position", "text", "Current position", "المنصب الحالي", group="career",
      max_len=250),
    F("affiliated_institution_id", "fk", "Affiliated institution", "المؤسسة التابعة",
      ref="institution", group="career"),
    F("affiliated_country_id", "select", "Affiliated country", "بلد الانتساب",
      domain="country", group="career", in_list=False),
    F("declared_affiliation", "textarea", "Declared institutional affiliation",
      "الانتساب المؤسسي المعلن", group="career", in_list=False),
    F("affiliation_verified", "bool", "Affiliation verified", "الانتساب موثّق",
      group="career", in_list=False,
      help_en="Distinguishes an affiliation confirmed by a source from one the person declared.",
      help_ar="يفرّق بين الانتساب المؤكد بمصدر والانتساب المعلن من الشخص نفسه."),
    F("affiliation_start", "date", "Affiliation start", "بداية الانتساب", group="career",
      in_list=False),
    F("affiliation_end", "date", "Affiliation end", "نهاية الانتساب", group="career",
      in_list=False),
    F("cv_url", "url", "Curriculum vitae", "السيرة الذاتية", group="career", in_list=False),
    F("public_activity", "textarea", "Public activity", "النشاط العام", group="career",
      in_list=False),
    F("institutional_relations", "textarea", "Institutional relations (summary)",
      "العلاقات المؤسسية (ملخص)", group="career", in_list=False,
      help_en="Free-text summary; use the Relationships module for structured links.",
      help_ar="ملخص نصي حر؛ استخدم وحدة العلاقات للروابط المهيكلة."),
    F("website", "url", "Official website", "الموقع الرسمي", group="contact", in_list=False),
    F("social_accounts", "text", "Official accounts", "الحسابات الرسمية", group="contact",
      max_len=500, in_list=False),
    *_own_position_fields(),
    PRIMARY_SOURCE(),
    DOC(),
    AUTH(),
    STATUS(),
    NOTES(),
] + system_fields()

place_fields: list[Field] = [
    code_field("place"),
    F("name_ar", "text", "Place name (Arabic)", "اسم المكان (بالعربية)", group="identity",
      required=True, max_len=250),
    F("name_original", "text", "Original name", "الاسم الأصلي", group="identity", max_len=250),
    F("name_en", "text", "Original name (English)", "الاسم الأصلي (بالإنجليزية)",
      group="identity", max_len=250),
    F("name_original_lang", "text", "Original name language", "لغة الاسم الأصلي",
      group="identity", in_list=False),
    F("place_type_id", "select", "Place type", "نوع المكان", domain="place_type", group="identity"),
    F("image_url", "url", "Image / photo link", "رابط الصورة", group="identity", in_list=False,
      help_en="Image URL or an uploaded /api/media/… path (card and gallery views)",
      help_ar="رابط الصورة أو ملف مرفوع بصيغة /api/media/… (يظهر في البطاقات والمعرض)"),
    F("image_alt", "text", "Image alt text", "نص بديل للصورة", group="identity", in_list=False,
      help_en="Short description of the image for accessibility and captions",
      help_ar="وصف موجز للصورة لأغراض الوصول والترقيم"),
    F("country_id", "select", "Country", "البلد", domain="country", group="location",
      help_en="Controlled vocabulary — add countries under Vocabularies → Country.",
      help_ar="قائمة مرجعية — أضف بلداناً من القوائم المرجعية ← البلد."),
    F("governorate_id", "select", "Governorate", "المحافظة", domain="governorate",
      group="location",
      help_en="Only governorates of the selected country are listed. Choosing one fills the country.",
      help_ar="تُعرض محافظات البلد المحدد فقط. اختيار محافظة يملأ البلد تلقائياً."),
    F("city", "text", "City", "المدينة", group="location", max_len=250),
    F("district_id", "select", "District", "القضاء", domain="district", group="location",
      in_list=False,
      help_en="Only districts of the selected governorate are listed.",
      help_ar="تُعرض أقضية المحافظة المحددة فقط."),
    F("parent_place_id", "fk", "Part of (parent place)", "يتبع (المكان الأعلى)",
      ref="place", group="location", in_list=False,
      help_en="Builds the geographic hierarchy: country → governorate → city → quarter.",
      help_ar="يبني التسلسل الجغرافي: البلد ← المحافظة ← المدينة ← الحي."),
    F("latitude", "float", "Latitude", "خط العرض", group="geo", in_list=False,
      help_en="A location is this coordinate, not the place name. Type the latitude or pick the point on the map beside it.",
      help_ar="الموقع هو هذا الإحداثي لا اسم المكان. أدخل خط العرض أو حدّد النقطة على الخريطة بجانبه."),
    F("longitude", "float", "Longitude", "خط الطول", group="geo", in_list=False,
      help_en="Type the longitude, or pick the point on the map. A name alone does not register a location.",
      help_ar="أدخل خط الطول أو حدّد النقطة على الخريطة. الاسم وحده لا يسجّل موقعاً."),
    F("geo_precision", "select", "Coordinate precision", "دقة الإحداثيات",
      domain="geo_precision", group="geo", in_list=False,
      help_en="How close the point is to the place: exact point, approximate, centroid "
              "of an area, or uncertain.",
      help_ar="مدى قرب النقطة من المكان: نقطة دقيقة، أو تقريبية، أو مركز منطقة، أو غير مؤكدة."),
    F("geocoding_method", "select", "How the point was obtained", "طريقة تحديد النقطة",
      domain="geocoding_method", group="geo", in_list=False,
      help_en="A city point is not a street address. Recording the method keeps a "
              "centroid from being read as a verified location.",
      help_ar="نقطة المدينة ليست عنواناً في شارع. تسجيل الطريقة يمنع قراءة مركز تقريبي "
              "بوصفه موقعاً موثّقاً."),
    F("geo_uncertainty_m", "float", "Uncertainty radius (metres)", "نصف قطر عدم اليقين (متر)",
      group="geo", in_list=False,
      help_en="The radius the true location could lie within. Leave empty when the "
              "point is exact.",
      help_ar="نصف القطر الذي قد يقع ضمنه الموقع الحقيقي. اتركه فارغاً إذا كانت النقطة دقيقة."),
    F("geometry_source", "text", "Geometry source", "مصدر الشكل الجغرافي",
      max_len=200, group="geo", in_list=False,
      help_en="The map, survey or gazetteer the coordinates came from.",
      help_ar="الخريطة أو المسح أو المعجم الذي أُخذت منه الإحداثيات."),
    F("geo_description", "textarea", "Geographic description", "الوصف الجغرافي", group="geo",
      in_list=False),
    F("research_significance", "textarea", "Research significance", "الأهمية البحثية",
      group="research", in_list=False),
    PRIMARY_SOURCE(),
    DOC(),
    AUTH(),
    STATUS(),
    NOTES(),
] + system_fields()

institution_fields: list[Field] = [
    code_field("institution"),
    F("name_ar", "text", "Name in Arabic", "الاسم بالعربية", group="identity", required=True,
      max_len=300),
    F("name_original", "text", "Original name", "الاسم الأصلي", group="identity", max_len=300),
    F("name_en", "text", "Original name (English)", "الاسم الأصلي (بالإنجليزية)",
      group="identity", max_len=300),
    F("name_original_lang", "text", "Original name language", "لغة الاسم الأصلي",
      group="identity", in_list=False),
    F("abbreviation", "text", "Abbreviation", "الاختصار", group="identity", max_len=64),
    F("institution_type_id", "select", "Type of institution", "نوع المؤسسة",
      domain="institution_type", group="identity"),
    F("image_url", "url", "Image / photo link", "رابط الصورة", group="identity", in_list=False,
      help_en="Image URL or an uploaded /api/media/… path (card and gallery views)",
      help_ar="رابط الصورة أو ملف مرفوع بصيغة /api/media/… (يظهر في البطاقات والمعرض)"),
    F("image_alt", "text", "Image alt text", "نص بديل للصورة", group="identity", in_list=False,
      help_en="Short description of the image for accessibility and captions",
      help_ar="وصف موجز للصورة لأغراض الوصول والترقيم"),
    F("subcategory_id", "select", "Subcategory", "التصنيف الفرعي",
      domain="institution_subcategory", group="identity", in_list=False),
    F("founded_date", "date", "Date of establishment", "تاريخ التأسيس", group="history",
      sortable=True),
    F("founded_precision", "select", "Foundation date precision", "دقة تاريخ التأسيس",
      domain="date_precision", group="history", in_list=False),
    F("closed_date", "date", "Date of closure", "تاريخ الإغلاق", group="history",
      in_list=False),
    F("country_id", "select", "Country", "البلد", domain="country", group="location"),
    F("city", "text", "City of headquarters", "مدينة المقر", group="location", max_len=250),
    F("place_id", "fk", "Place (record)", "المكان (سجل)", ref="place", group="location",
      in_list=False),
    F("address", "textarea", "Official address", "العنوان الرسمي", group="location",
      in_list=False),
    F("current_leadership", "text", "Current leadership", "القيادة الحالية", group="people",
      max_len=500, in_list=False),
    F("founders_text", "text", "Founders", "المؤسسون", group="people", max_len=500,
      in_list=False),
    F("objectives", "textarea", "Statement of objectives", "بيان الأهداف", group="profile",
      in_list=False),
    F("org_structure", "textarea", "Organisational structure", "الهيكل التنظيمي",
      group="profile", in_list=False),
    F("governance_id", "select", "Governance system", "نظام الحوكمة",
      domain="governance_system", group="profile", in_list=False),
    F("website", "url", "Website", "الموقع الإلكتروني", group="contact", in_list=False),
    F("official_accounts", "text", "Official accounts", "الحسابات الرسمية", group="contact",
      max_len=500, in_list=False),
    F("research_significance", "textarea", "Research significance", "الأهمية البحثية",
      group="research", in_list=False),
    *_own_position_fields(),
    PRIMARY_SOURCE(),
    DOC(),
    AUTH(),
    STATUS(),
    NOTES(),
] + system_fields()

relationship_fields: list[Field] = [
    code_field("relationship"),
    F("entity1_type", "select", "Entity type 1", "نوع الكيان ١", domain="entity_type",
      group="link", required=True, in_list=False, store="code"),
    F("entity1_id", "fk", "Entity 1", "الكيان ١", ref="person", group="link", required=True,
      in_list=False),
    F("entity1_name", "text", "Entity 1 name", "اسم الكيان ١", group="link", max_len=300),
    F("relationship_type_id", "select", "Relationship type", "نوع العلاقة",
      domain="relationship_type", group="link", required=True),
    F("entity2_type", "select", "Entity type 2", "نوع الكيان ٢", domain="entity_type",
      group="link", required=True, in_list=False, store="code"),
    F("entity2_id", "fk", "Entity 2", "الكيان ٢", ref="person", group="link", required=True,
      in_list=False),
    F("entity2_name", "text", "Entity 2 name", "اسم الكيان ٢", group="link", max_len=300),
    F("direction", "select", "Direction", "الاتجاه", domain="relation_direction",
      group="link", in_list=False, store="code"),
    F("description", "textarea", "Relationship description", "وصف العلاقة", group="detail",
      in_list=False),
    F("start_date", "date", "Start date", "تاريخ البداية", group="detail", sortable=True),
    F("end_date", "date", "End date", "تاريخ النهاية", group="detail", in_list=False),
    F("is_current", "bool", "Current", "سارية", group="detail", in_list=False),
    PRIMARY_SOURCE(),
    F("source_id", "fk", "Verifying source", "المصدر الموثّق", ref="source", group="meta",
      in_list=False),
    AUTH(),
    STATUS(),
    F("last_review_date", "date", "Last review date", "تاريخ آخر مراجعة", group="meta",
      in_list=False),
    NOTES(),
] + system_fields()

source_fields: list[Field] = [
    code_field("source"),
    F("title", "text", "Source name / title", "اسم المصدر / العنوان", group="identity",
      required=True, max_len=500),
    F("title_ar", "text", "Title in Arabic", "العنوان بالعربية", group="identity", max_len=500),
    F("source_type_id", "select", "Source type", "نوع المصدر", domain="source_type",
      group="identity"),
    F("publisher", "text", "Publisher", "الناشر", group="identity", max_len=300),
    F("url", "url", "Web link", "الرابط الإلكتروني", group="identity", in_list=False),
    F("publication_date", "date", "Publication date", "تاريخ النشر", group="identity",
      sortable=True),
    F("publication_precision", "select", "Publication date precision", "دقة تاريخ النشر",
      domain="date_precision", group="identity", in_list=False),
    F("access_date", "date", "Access date", "تاريخ الاطلاع", group="identity", in_list=False),
    F("language", "text", "Language", "اللغة", group="identity", max_len=64, in_list=False),
    F("isbn_issn", "text", "ISBN / ISSN", "ردمك / ردمد", group="identity", max_len=64,
      in_list=False),
    F("archive_reference", "text", "Archive reference", "المرجع الأرشيفي", group="identity",
      max_len=250, in_list=False),
    F("supported_information", "textarea", "Supported information", "المعلومات المدعومة",
      group="content", in_list=False),
    F("entity_type", "select", "Associated entity type", "نوع الكيان المرتبط",
      domain="entity_type", group="content", in_list=False, store="code"),
    F("entity_id", "int", "Associated entity ID", "معرّف الكيان المرتبط", group="content",
      in_list=False),
    F("reliability_id", "select", "Reliability assessment", "تقييم الموثوقية",
      domain="source_reliability", group="assessment"),
    F("verification_notes", "textarea", "Verification notes", "ملاحظات التحقق",
      group="assessment", in_list=False),
    AUTH(),
    STATUS(),
    NOTES(),
] + system_fields()

event_fields: list[Field] = [
    code_field("event"),
    F("title_ar", "text", "Event title (Arabic)", "عنوان الحدث (بالعربية)", group="identity",
      required=True, max_len=300),
    F("title_en", "text", "Event title (English)", "عنوان الحدث (بالإنجليزية)",
      group="identity", max_len=300),
    F("event_type_id", "select", "Event type", "نوع الحدث", domain="event_type",
      group="identity"),
    F("image_url", "url", "Image / photo link", "رابط الصورة", group="identity", in_list=False,
      help_en="Image URL or an uploaded /api/media/… path (card and gallery views)",
      help_ar="رابط الصورة أو ملف مرفوع بصيغة /api/media/… (يظهر في البطاقات والمعرض)"),
    F("image_alt", "text", "Image alt text", "نص بديل للصورة", group="identity", in_list=False,
      help_en="Short description of the image for accessibility and captions",
      help_ar="وصف موجز للصورة لأغراض الوصول والترقيم"),
    F("start_date", "date", "Start date", "تاريخ البداية", group="timing", sortable=True),
    F("end_date", "date", "End date", "تاريخ النهاية", group="timing", in_list=False),
    F("place_id", "fk", "Place", "المكان", ref="place", group="location"),
    F("description", "textarea", "Description", "الوصف", group="detail", in_list=False),
    F("significance", "textarea", "Significance", "الأهمية", group="detail", in_list=False),
    *_own_position_fields(),
    PRIMARY_SOURCE(),
    DOC(),
    AUTH(),
    STATUS(),
    NOTES(),
] + system_fields()


ENTITIES: dict[str, EntitySpec] = {
    "person": EntitySpec(
        key="person", table="person", label_en="Person", label_ar="شخص",
        plural_en="Persons", plural_ar="الأشخاص", icon="user", code_prefix="PER",
        fields=person_fields, title_fields=["name_ar", "name_en"],
        name_fields=("name_en", "name_ar"), default_sort="updated_at", tags=("specialization",),
        has_positions=True,
        children=("positions", "specializations", "relationships", "sources", "attachments"),
        description_en="Researchers, scholars, officials and other individuals.",
        description_ar="الباحثون والعلماء والمسؤولون وسائر الشخصيات.",
    ),
    "place": EntitySpec(
        key="place", table="place", label_en="Place", label_ar="مكان",
        plural_en="Places", plural_ar="الأماكن", icon="map-pin", code_prefix="PLC",
        fields=place_fields, title_fields=["name_ar", "name_en"],
        name_fields=("name_en", "name_ar"), default_sort="updated_at",
        children=("relationships", "sources", "attachments"),
        description_en="Cities, districts, sites and buildings of research interest.",
        description_ar="المدن والأقضية والمواقع والمباني ذات الأهمية البحثية.",
    ),
    "institution": EntitySpec(
        key="institution", table="institution", label_en="Institution", label_ar="مؤسسة",
        plural_en="Institutions", plural_ar="المؤسسات", icon="building", code_prefix="INS",
        fields=institution_fields, title_fields=["name_ar", "name_en"],
        name_fields=("name_en", "name_ar"), default_sort="updated_at", tags=("expertise",),
        children=("specializations", "relationships", "sources", "attachments"),
        description_en="Universities, research centres, ministries, associations.",
        description_ar="الجامعات ومراكز البحث والوزارات والجمعيات.",
    ),
    "relationship": EntitySpec(
        key="relationship", table="relationship", label_en="Relationship", label_ar="علاقة",
        plural_en="Relationships", plural_ar="العلاقات", icon="link", code_prefix="REL",
        fields=relationship_fields, title_fields=["entity1_name", "entity2_name"],
        name_fields=("entity1_name",), default_sort="updated_at",
        description_en="Typed, sourced links between any two records.",
        description_ar="روابط موثّقة ومصنّفة بين أي سجلين.",
    ),
    "source": EntitySpec(
        key="source", table="source", label_en="Source", label_ar="مصدر",
        plural_en="Sources", plural_ar="المصادر", icon="book", code_prefix="SRC",
        fields=source_fields, title_fields=["title", "title_ar"],
        name_fields=("title", "title_ar"), default_sort="updated_at",
        children=("links", "attachments"),
        description_en="Documents, archives, interviews and web references.",
        description_ar="الوثائق والأرشيفات والمقابلات والمراجع الإلكترونية.",
    ),
    "event": EntitySpec(
        key="event", table="event", label_en="Event", label_ar="حدث",
        plural_en="Events", plural_ar="الأحداث", icon="calendar", code_prefix="EVT",
        fields=event_fields, title_fields=["title_ar", "title_en"],
        name_fields=("title_en", "title_ar"), default_sort="updated_at",
        children=("relationships", "sources", "attachments"),
        description_en="Historical events that connect persons, places and institutions.",
        description_ar="أحداث تاريخية تربط الأشخاص والأماكن والمؤسسات.",
    ),
}

# which date fields the interface asks a *time* for (see TIME_AWARE_FIELDS)
for _entity_key, _spec in ENTITIES.items():
    for _field in _spec.fields:
        if (_entity_key, _field.key) in TIME_AWARE_FIELDS:
            _field.time = True

ENTITY_TYPES = list(ENTITIES.keys())


def entity_meta(lang: str = "en") -> list[dict]:
    out = []
    for e in ENTITIES.values():
        out.append({
            "key": e.key,
            "label": e.label_ar if lang == "ar" else e.label_en,
            "label_en": e.label_en, "label_ar": e.label_ar,
            "plural_en": e.plural_en, "plural_ar": e.plural_ar,
            "icon": e.icon, "code_prefix": e.code_prefix,
            "description_en": e.description_en, "description_ar": e.description_ar,
            "tags": list(e.tags), "has_positions": e.has_positions,
            "children": list(e.children),
        })
    return out


def fields_meta(spec: EntitySpec) -> list[dict]:
    return [{
        "key": f.key, "type": f.type, "label_en": f.label_en, "label_ar": f.label_ar,
        "group": f.group, "required": f.required, "unique": f.unique, "max_len": f.max_len,
        "domain": f.domain, "ref": f.ref, "tag_domain": f.tag_domain, "store": f.store,
        "help_en": f.help_en, "help_ar": f.help_ar, "in_list": f.in_list,
        "filterable": f.filterable, "sortable": f.sortable, "read_only": f.read_only,
        "system": f.system, "placeholder_ar": f.placeholder_ar,
        "placeholder_en": f.placeholder_en,
        "time": bool(f.time),
    } for f in spec.fields]


# ---------------------------------------------------------------------------
# validation (used by API create/update and by the importer)
# ---------------------------------------------------------------------------
def coerce(spec: EntitySpec, key: str, value: Any) -> tuple[Any, str | None]:
    """Return (coerced_value, error_message)."""
    f = spec.field(key)
    if f is None:
        return None, f"Unknown field '{key}'"
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if f.required and f.key != "code":
            return None, f"{f.label_en} is required"
        return None, None
    if isinstance(value, str):
        value = value.strip()
    if f.type in ("text", "textarea", "url"):
        if f.max_len and len(str(value)) > f.max_len:
            return None, f"{f.label_en} exceeds {f.max_len} characters"
        if f.type == "url" and value and not URL_RE.match(str(value)):
            return None, f"{f.label_en} must be a valid http(s) URL, mailto: or /path"
        return str(value), None
    if f.type == "int":
        try:
            return int(float(value)), None
        except (TypeError, ValueError):
            return None, f"{f.label_en} must be an integer"
    if f.type == "float":
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None, f"{f.label_en} must be a number"
        if f.key == "latitude" and not -90 <= num <= 90:
            return None, "Latitude must be between -90 and 90"
        if f.key == "longitude" and not -180 <= num <= 180:
            return None, "Longitude must be between -180 and 180"
        return num, None
    if f.type == "date":
        stored, _precision, error = parse_date_value(value)
        if error:
            return None, f"{f.label_en} {error}"
        return stored, None
    if f.type == "bool":
        if isinstance(value, bool):
            return int(value), None
        return (1 if str(value).lower() in ("1", "true", "yes", "y", "نعم", "on") else 0), None
    if f.type == "select":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value), None
        s = str(value).strip()
        if s.isdigit():
            return int(s), None
        # non-numeric values are resolved against the vocabulary (code or label)
        return s, None
    if f.type == "fk":
        s = str(value).strip()
        if s.isdigit():
            return int(s), None
        return value, f"{f.label_en} expects a numeric record id"
    return value, None


def year_of(value: Any) -> int | None:
    """Best-effort year extraction used for timelines and decade reports."""
    if value is None:
        return None
    m = re.search(r"(\d{3,4})", str(value))
    return int(m.group(1)) if m else None


def date_sort_key(value: Any) -> tuple[int, int, int]:
    if not value:
        return (0, 0, 0)
    y = year_of(value) or 0
    mo = re.search(r"\d{3,4}-(\d{2})", str(value))
    dy = re.search(r"\d{3,4}-\d{2}-(\d{2})", str(value))
    return (y, int(mo.group(1)) if mo else 0, int(dy.group(1)) if dy else 0)


# ===========================================================================
# Derived (related-table) fields
# ---------------------------------------------------------------------------
# A derived field is a scalar SQL expression anchored on the entity table alias
# `t`.  It can be displayed, filtered, sorted, exported, grouped in reports and
# used in card layouts — so "any field, including those from related tables" is
# a first-class column rather than a rendering trick.
# ===========================================================================
@dataclass
class Derived:
    key: str
    label_en: str
    label_ar: str
    sql: str
    type: str = "text"          # text | int | date
    group: str = "related"
    filterable: bool = True
    sortable: bool = True
    in_list: bool = False
    unit: str | None = None
    help_en: str = ""
    help_ar: str = ""


def _lookup_label(col: str) -> str:
    return f"(SELECT l.label_en FROM lookup l WHERE l.id = t.{col})"


def _count(sql: str) -> str:
    return f"({sql})"


def _completeness(cols: list[str]) -> str:
    parts = [f"(CASE WHEN t.{c} IS NOT NULL AND TRIM(CAST(t.{c} AS TEXT)) <> '' "
             f"THEN 1 ELSE 0 END)" for c in cols]
    return f"(({' + '.join(parts)}) * 100 / {len(cols)})"


PERSON_CORE = ["name_ar", "birth_date", "nationality_id", "classification_id",
               "current_status_id", "affiliated_institution_id", "primary_source_id",
               "authentication_id", "record_status_id", "researcher_notes"]
INST_CORE = ["name_ar", "institution_type_id", "country_id", "founded_date",
             "primary_source_id", "authentication_id", "record_status_id",
             "website", "objectives", "researcher_notes"]
PLACE_CORE = ["name_ar", "place_type_id", "country_id", "governorate_id", "latitude",
              "longitude", "primary_source_id", "record_status_id"]
SOURCE_CORE = ["title", "source_type_id", "reliability_id", "publication_date",
               "publisher", "url", "record_status_id", "authentication_id"]
EVENT_CORE = ["title_ar", "event_type_id", "start_date", "place_id",
              "primary_source_id", "record_status_id"]

DERIVED_FIELDS: dict[str, list[Derived]] = {
    "person": [
        Derived("has_coords", "Own position recorded", "موقع خاص مسجَّل",
                "CASE WHEN t.latitude IS NOT NULL AND t.longitude IS NOT NULL THEN 1 ELSE 0 END",
                "int", "geo",
                help_en="1 when the person's own coordinates are recorded — independent of any linked place.",
                help_ar="=1 عند تسجيل إحداثيات الشخص الخاصة — مستقلة عن أي مكان مرتبط."),
        Derived("birth_year", "Birth year", "سنة الميلاد", "year_of(t.birth_date)",
                "int", "life", unit="year", help_en="Sortable/filterable numeric year.",
                help_ar="سنة رقمية قابلة للفرز والتصفية."),
        Derived("death_year", "Death year", "سنة الوفاة", "year_of(t.death_date)",
                "int", "life", unit="year"),
        Derived("age_at_death", "Age at death", "العمر عند الوفاة",
                "CASE WHEN year_of(t.death_date) IS NOT NULL AND year_of(t.birth_date) IS NOT NULL "
                "THEN year_of(t.death_date) - year_of(t.birth_date) END", "int", "life"),
        Derived("nationality_label", "Nationality (label)", "الجنسية (تسمية)",
                _lookup_label("nationality_id"), "text", "life"),
        Derived("classification_label", "Classification (label)", "التصنيف (تسمية)",
                _lookup_label("classification_id"), "text", "career"),
        Derived("status_label", "Status (label)", "الحالة (تسمية)",
                _lookup_label("record_status_id"), "text", "meta"),
        Derived("authentication_label", "Authentication (label)", "التحقق (تسمية)",
                _lookup_label("authentication_id"), "text", "meta"),
        Derived("institution_name", "Institution (name)", "المؤسسة (الاسم)",
                "(SELECT COALESCE(i.name_en, i.name_ar) FROM institution i "
                "WHERE i.id = t.affiliated_institution_id)", "text", "career"),
        Derived("institution_code", "Institution (ID)", "المؤسسة (الرقم)",
                "(SELECT i.code FROM institution i WHERE i.id = t.affiliated_institution_id)",
                "text", "career"),
        Derived("institution_country", "Institution country", "بلد المؤسسة",
                "(SELECT c.label_en FROM institution i JOIN lookup c ON c.id = i.country_id "
                "WHERE i.id = t.affiliated_institution_id)", "text", "career"),
        Derived("birthplace_name", "Birthplace (name)", "مكان الميلاد (الاسم)",
                "(SELECT COALESCE(p.name_en, p.name_ar) FROM place p WHERE p.id = t.birthplace_id)",
                "text", "life"),
        Derived("positions_count", "Positions", "عدد المناصب",
                _count("SELECT COUNT(*) FROM person_position pp WHERE pp.person_id = t.id"),
                "int", "related"),
        Derived("relationships_count", "Relationships", "عدد العلاقات",
                _count("SELECT COUNT(*) FROM relationship r WHERE r.deleted_at IS NULL AND "
                       "((r.entity1_type='person' AND r.entity1_id=t.id) OR "
                       "(r.entity2_type='person' AND r.entity2_id=t.id))"), "int", "related"),
        Derived("citations_count", "Citations", "عدد الاستشهادات",
                _count("SELECT COUNT(*) FROM evidence e WHERE e.entity_type='person' "
                       "AND e.entity_id = t.id"), "int", "related"),
        Derived("tags_text", "Specialisations", "التخصصات",
                "(SELECT GROUP_CONCAT(x.label_en, ' · ') FROM tag x "
                "JOIN entity_tag et ON et.tag_id = x.id "
                "WHERE et.entity_type='person' AND et.entity_id = t.id)", "text", "related"),
        Derived("completeness", "Record completeness %", "نسبة اكتمال السجل %",
                _completeness(PERSON_CORE), "int", "quality", unit="%"),
        Derived("last_change", "Last change", "آخر تغيير",
                "(SELECT MAX(cl.changed_at) FROM change_log cl WHERE cl.entity_type='person' "
                "AND cl.entity_id = t.id)", "date", "quality"),
    ],
    "institution": [
        Derived("has_coords", "Own position recorded", "موقع خاص مسجَّل",
                "CASE WHEN t.latitude IS NOT NULL AND t.longitude IS NOT NULL THEN 1 ELSE 0 END",
                "int", "geo"),
        Derived("type_label", "Type (label)", "النوع (تسمية)",
                _lookup_label("institution_type_id"), "text", "identity"),
        Derived("country_label", "Country (label)", "البلد (تسمية)",
                _lookup_label("country_id"), "text", "location"),
        Derived("founded_year", "Year founded", "سنة التأسيس", "year_of(t.founded_date)",
                "int", "history", unit="year"),
        Derived("place_name", "Place (name)", "المكان (الاسم)",
                "(SELECT COALESCE(p.name_en, p.name_ar) FROM place p WHERE p.id = t.place_id)",
                "text", "location"),
        Derived("persons_count", "Affiliated persons", "الأشخاص المنتسبون",
                _count("SELECT COUNT(*) FROM person p WHERE p.affiliated_institution_id = t.id "
                       "AND p.deleted_at IS NULL"), "int", "related"),
        Derived("positions_count", "Recorded positions", "المناصب المسجلة",
                _count("SELECT COUNT(*) FROM person_position pp WHERE pp.institution_id = t.id"),
                "int", "related"),
        Derived("relationships_count", "Relationships", "عدد العلاقات",
                _count("SELECT COUNT(*) FROM relationship r WHERE r.deleted_at IS NULL AND "
                       "((r.entity1_type='institution' AND r.entity1_id=t.id) OR "
                       "(r.entity2_type='institution' AND r.entity2_id=t.id))"), "int", "related"),
        Derived("governance_label", "Governance (label)", "الحوكمة (تسمية)",
                _lookup_label("governance_id"), "text", "profile"),
        Derived("completeness", "Record completeness %", "نسبة اكتمال السجل %",
                _completeness(INST_CORE), "int", "quality", unit="%"),
    ],
    "place": [
        Derived("type_label", "Type (label)", "النوع (تسمية)",
                _lookup_label("place_type_id"), "text", "identity"),
        Derived("country_label", "Country (label)", "البلد (تسمية)",
                _lookup_label("country_id"), "text", "location"),
        Derived("parent_name", "Parent place", "المكان الأعلى",
                "(SELECT COALESCE(p.name_en, p.name_ar) FROM place p WHERE p.id = t.parent_place_id)",
                "text", "location"),
        Derived("has_coords", "Geocoded", "مُحدَّد الإحداثيات",
                "CASE WHEN t.latitude IS NOT NULL AND t.longitude IS NOT NULL THEN 1 ELSE 0 END",
                "int", "geo"),
        Derived("children_count", "Sub-places", "الأماكن التابعة",
                _count("SELECT COUNT(*) FROM place p WHERE p.parent_place_id = t.id"), "int", "related"),
        Derived("institutions_count", "Institutions here", "المؤسسات هنا",
                _count("SELECT COUNT(*) FROM institution i WHERE i.place_id = t.id "
                       "AND i.deleted_at IS NULL"), "int", "related"),
        Derived("persons_born_count", "Persons born here", "مولودون هنا",
                _count("SELECT COUNT(*) FROM person p WHERE p.birthplace_id = t.id "
                       "AND p.deleted_at IS NULL"), "int", "related"),
        Derived("relationships_count", "Relationships", "عدد العلاقات",
                _count("SELECT COUNT(*) FROM relationship r WHERE r.deleted_at IS NULL AND "
                       "((r.entity1_type='place' AND r.entity1_id=t.id) OR "
                       "(r.entity2_type='place' AND r.entity2_id=t.id))"), "int", "related"),
        Derived("completeness", "Record completeness %", "نسبة اكتمال السجل %",
                _completeness(PLACE_CORE), "int", "quality", unit="%"),
        Derived("geo_precision_label", "Precision (label)", "الدقة (تسمية)",
                _lookup_label("geo_precision"), "text", "geo"),
        Derived("geocoding_method_label", "Method (label)", "الطريقة (تسمية)",
                _lookup_label("geocoding_method"), "text", "geo"),
    ],
    "source": [
        Derived("type_label", "Type (label)", "النوع (تسمية)",
                _lookup_label("source_type_id"), "text", "identity"),
        Derived("reliability_label", "Reliability (label)", "الموثوقية (تسمية)",
                _lookup_label("reliability_id"), "text", "assessment"),
        Derived("year", "Publication year", "سنة النشر", "year_of(t.publication_date)",
                "int", "identity", unit="year"),
        Derived("citations_count", "Citations", "الاستشهادات",
                _count("SELECT COUNT(*) FROM evidence e WHERE e.source_id = t.id"),
                "int", "related"),
        Derived("primary_for_count", "Primary source for", "مصدر أساسي لـ",
                _count("SELECT (SELECT COUNT(*) FROM person p WHERE p.primary_source_id=t.id) + "
                       "(SELECT COUNT(*) FROM place pl WHERE pl.primary_source_id=t.id) + "
                       "(SELECT COUNT(*) FROM institution i WHERE i.primary_source_id=t.id) + "
                       "(SELECT COUNT(*) FROM event e WHERE e.primary_source_id=t.id)"),
                "int", "related"),
        Derived("completeness", "Record completeness %", "نسبة اكتمال السجل %",
                _completeness(SOURCE_CORE), "int", "quality", unit="%"),
    ],
    "relationship": [
        Derived("type_label", "Type (label)", "النوع (تسمية)",
                _lookup_label("relationship_type_id"), "text", "link"),
        Derived("status_label", "Status (label)", "الحالة (تسمية)",
                _lookup_label("record_status_id"), "text", "meta"),
        Derived("start_year", "Start year", "سنة البداية", "year_of(t.start_date)",
                "int", "detail", unit="year"),
        Derived("end_year", "End year", "سنة النهاية", "year_of(t.end_date)",
                "int", "detail", unit="year"),
        Derived("source_title", "Source (title)", "المصدر (العنوان)",
                "(SELECT s.title FROM source s WHERE s.id = t.source_id)", "text", "meta"),
        Derived("duration_years", "Duration (years)", "المدة (سنوات)",
                "CASE WHEN year_of(t.end_date) IS NOT NULL AND year_of(t.start_date) IS NOT NULL "
                "THEN year_of(t.end_date) - year_of(t.start_date) END", "int", "detail"),
    ],
    "event": [
        Derived("has_coords", "Own position recorded", "موقع خاص مسجَّل",
                "CASE WHEN t.latitude IS NOT NULL AND t.longitude IS NOT NULL THEN 1 ELSE 0 END",
                "int", "geo"),
        Derived("type_label", "Type (label)", "النوع (تسمية)",
                _lookup_label("event_type_id"), "text", "identity"),
        Derived("year", "Year", "السنة", "year_of(t.start_date)", "int", "timing", unit="year"),
        Derived("place_name", "Place (name)", "المكان (الاسم)",
                "(SELECT COALESCE(p.name_en, p.name_ar) FROM place p WHERE p.id = t.place_id)",
                "text", "location"),
        Derived("participants_count", "Participants", "المشاركون",
                _count("SELECT COUNT(*) FROM relationship r WHERE r.deleted_at IS NULL AND "
                       "((r.entity2_type='event' AND r.entity2_id=t.id) OR "
                       "(r.entity1_type='event' AND r.entity1_id=t.id))"), "int", "related"),
        Derived("completeness", "Record completeness %", "نسبة اكتمال السجل %",
                _completeness(EVENT_CORE), "int", "quality", unit="%"),
    ],
}


def derived_map(entity: str) -> dict[str, Derived]:
    return {d.key: d for d in DERIVED_FIELDS.get(entity, [])}


def derived_meta(entity: str) -> list[dict]:
    return [{
        "key": d.key, "label_en": d.label_en, "label_ar": d.label_ar, "type": d.type,
        "group": d.group, "filterable": d.filterable, "sortable": d.sortable,
        "in_list": d.in_list, "unit": d.unit, "help_en": d.help_en, "help_ar": d.help_ar,
        "expr": d.sql, "derived": True,
    } for d in DERIVED_FIELDS.get(entity, [])]

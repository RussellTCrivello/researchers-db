"""
SIRAJ · settings — the typed configuration registry.

A registry, not a key/value bag.  Every setting the application honours is
declared **once**, here, with its type, its default, its allowed values, the
group it belongs to and a bilingual label and explanation.  Everything else is
derived from that declaration:

  * the API (`/api/settings`, `/api/settings/schema`, `/api/meta`) serves it;
  * the settings screen renders itself from it (a control per type, help text,
    default value, reset button) — no hand-written field ever drifts;
  * `PUT /api/settings` validates against it, so an unknown key or an out-of-range
    value is refused with a reason instead of being stored;
  * the value a *consumer* reads comes from `get(conn, key)`, which returns the
    stored value coerced to its declared type, or the declared default.

Three rules worth stating out loud:

1. **A setting exists only if something reads it.**  Every entry below names the
   code path that honours it (`effect`); a key nobody reads is a lie in a settings
   screen.
2. **No row means "the default".**  The `setting` table stores *overrides*; a key
   that was never changed (or was reset) has no row, so an upgrade that improves a
   default improves existing installations instead of freezing them on the old one.
3. **Instance vs. personal.**  Some values are policy (`personal=False`: one
   decision for everybody, stored in the database and audited).  Others are taste
   (`personal=True`: the browser may override them for one person, in
   `localStorage`, without touching the instance).  The screen shows which is which.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from app import db

# --------------------------------------------------------------------------
# groups — the order here is the order of the settings screen
# --------------------------------------------------------------------------
GROUPS: tuple[tuple[str, str, str, str], ...] = (
    ("display", "Display & appearance", "العرض والمظهر", "sliders"),
    ("entry", "Data entry", "إدخال البيانات", "edit"),
    ("search", "Search & filtering", "البحث والتصفية", "search"),
    ("transfer", "Import & export", "الاستيراد والتصدير", "upload"),
    ("quality", "Validation & data quality", "التحقّق وجودة البيانات", "check-circle"),
    ("audit", "Audit & retention", "التدقيق والاحتفاظ", "history"),
    ("maintenance", "Maintenance & backups", "الصيانة والنسخ الاحتياطي", "database"),
    ("map", "Map & geography", "الخريطة والجغرافيا", "map"),
)


@dataclass(frozen=True)
class Spec:
    """One declared setting.  Immutable, so the registry cannot be edited at runtime."""

    key: str
    group: str
    kind: str                      # bool | int | enum | text
    default: str
    label_en: str
    label_ar: str
    help_en: str = ""
    help_ar: str = ""
    values: tuple[str, ...] = ()   # enum only; the first one is the recommended value
    minimum: int | None = None     # int only (inclusive)
    maximum: int | None = None
    personal: bool = False         # may a browser override it for one person?
    effect: str = ""               # the code path that honours it (documentation)
    requires: str = ""             # "restart" when the value is only read at boot
    # enum presentation (optional): (value, label_en, label_ar, group_id) per
    # choice and (group_id, label_en, label_ar) per group — the screen renders
    # grouped options instead of raw identifiers.
    choices: tuple[tuple[str, str, str, str], ...] = ()
    choice_groups: tuple[tuple[str, str, str], ...] = ()

    # -- typed access -------------------------------------------------------
    def coerce(self, raw: Any) -> Any:
        """Return (value) as the declared type, or raise ValueError(reason)."""
        if self.kind == "bool":
            s = str(raw).strip().lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off"):
                return False
            raise ValueError("not_bool")
        if self.kind == "int":
            try:
                n = int(str(raw).strip())
            except (TypeError, ValueError):
                raise ValueError("not_integer") from None
            if self.minimum is not None and n < self.minimum:
                raise ValueError("below_minimum")
            if self.maximum is not None and n > self.maximum:
                raise ValueError("above_maximum")
            return n
        if self.kind == "decimal":
            try:
                n = float(str(raw).strip().replace(",", "."))
            except (TypeError, ValueError):
                raise ValueError("not_a_number") from None
            if not math.isfinite(n):
                raise ValueError("not_a_number")
            if self.minimum is not None and n < self.minimum:
                raise ValueError("below_minimum")
            if self.maximum is not None and n > self.maximum:
                raise ValueError("above_maximum")
            return n
        if self.kind == "enum":
            s = str(raw).strip()
            if s not in self.values:
                raise ValueError("not_allowed")
            return s
        return str(raw if raw is not None else "").strip()

    def store(self, raw: Any) -> str:
        """The canonical string form written to the `setting` table."""
        v = self.coerce(raw)
        if self.kind == "bool":
            return "true" if v else "false"
        if self.kind == "decimal":
            # a canonical decimal: no exponent, no trailing zeros, always a point
            text = f"{v:.7f}".rstrip("0").rstrip(".")
            return "0" if text in ("", "-0") else text
        return str(v)

    @property
    def typed_default(self) -> Any:
        return self.coerce(self.default)

    def public(self) -> dict:
        return {
            "key": self.key, "group": self.group, "kind": self.kind,
            "default": self.default, "values": list(self.values),
            "minimum": self.minimum, "maximum": self.maximum,
            "personal": self.personal, "requires": self.requires,
            "choices": [{"value": v, "label_en": en, "label_ar": ar, "group": g}
                        for v, en, ar, g in self.choices],
            "choice_groups": [{"id": g, "label_en": en, "label_ar": ar}
                              for g, en, ar in self.choice_groups],
            "label_en": self.label_en, "label_ar": self.label_ar,
            "help_en": self.help_en, "help_ar": self.help_ar,
            "effect": self.effect,
        }


def _map_provider_choices() -> tuple[tuple[tuple[str, str, str], ...],
                                     tuple[tuple[str, str, str, str], ...],
                                     tuple[str, ...]]:
    """The map-view choices, taken from the provider catalogue itself, so the
    settings screen can never list a map type the map cannot show."""
    from app.geo import providers as map_providers

    group_labels = {
        "offline": ("Offline & graphical", "دون اتصال ورسومية"),
        "standard": ("Standard maps", "خرائط قياسية"),
        "aerial": ("Aerial imagery", "صور جوية"),
        "terrain": ("Terrain", "تضاريس"),
    }
    groups = tuple((g, *group_labels.get(g, (g, g))) for g in map_providers.GROUPS)
    choices: list[tuple[str, str, str, str]] = []
    values: list[str] = []
    for gid in map_providers.GROUPS:
        for prov in map_providers.catalog():
            if prov["group"] != gid:
                continue
            choices.append((prov["id"], prov["label_en"], prov["label_ar"], gid))
            values.append(prov["id"])
    # the recommended default first: the offline graphical map
    values.remove(map_providers.DEFAULT_PROVIDER)
    values.insert(0, map_providers.DEFAULT_PROVIDER)
    return groups, tuple(choices), tuple(values)


_MAP_PROVIDER_GROUPS, _MAP_PROVIDER_CHOICES, _MAP_PROVIDER_VALUES = _map_provider_choices()


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------
SPECS: tuple[Spec, ...] = (
    # ---- display & appearance ------------------------------------------
    Spec("display.theme", "display", "enum", "light",
         "Colour theme", "المظهر اللوني",
         "Light, dark, or follow the operating system. Applies to this browser when "
         "set as a personal preference, to everyone when set as the instance default.",
         "فاتح أو داكن أو تابع لنظام التشغيل. يُطبَّق على هذا المتصفح كتفضيل شخصي، وعلى الجميع كافتراضي للمنصة.",
         values=("light", "dark", "system"), personal=True,
         effect="app.js applyAppearance() → <html data-theme>"),
    Spec("display.density", "display", "enum", "comfortable",
         "Table density", "كثافة الجداول",
         "Comfortable rows, or compact rows that fit about a third more records on screen.",
         "صفوف مريحة، أو صفوف مضغوطة تعرض نحو ثلث سجلات إضافية على الشاشة.",
         values=("comfortable", "compact"), personal=True,
         effect="core.js state.density → list.js table class + CSS"),
    Spec("display.page_size", "display", "int", "25",
         "Rows per page", "عدد الصفوف في الصفحة",
         "How many records a list loads at a time (and how many “Load more” adds).",
         "عدد السجلات التي تُحمَّل في المرة الواحدة، وعدد ما تضيفه «تحميل المزيد».",
         minimum=5, maximum=500, personal=True,
         effect="core.js pageSize() → views/list.js"),
    Spec("display.default_language", "display", "enum", "ar",
         "Default language", "اللغة الافتراضية",
         "The language a first visit opens in. A language the visitor picked is remembered "
         "and wins over this value.",
         "اللغة التي يُفتح بها الزائر الأول مرة. اختيار الزائر لغةً يُحفظ ويتقدّم على هذه القيمة.",
         values=("ar", "en"), effect="app.js boot() → first paint language"),

    # ---- data entry -----------------------------------------------------
    Spec("ui.form_mode", "entry", "enum", "page",
         "Where forms open", "أين تُفتح النماذج",
         "Full page, pop-up window, or automatic (pop-up from 960 px wide). See PHASE6.md.",
         "صفحة كاملة أو نافذة منبثقة أو تلقائي (منبثقة عند عرض ٩٦٠ بكسل أو أكثر).",
         values=("page", "dialog", "auto"), personal=True,
         effect="core.js formMode() → views/record.js openFormDialog()"),
    Spec("ui.form_dialog_size", "entry", "enum", "xl",
         "Pop-up width", "عرض النافذة المنبثقة",
         "How wide a form dialog opens. “xl” is the two-column layout; “wide” is a "
         "narrower single-column feel.",
         "عرض نافذة النموذج. «xl» تخطيط بعمودين، و«wide» إحساس أضيق بعمود واحد.",
         values=("wide", "xl"), personal=True,
         effect="core.js formDialogSize() → modal(size)"),
    Spec("ui.inline_create", "entry", "bool", "true",
         "Allow creating missing records from a field", "السماح بإنشاء سجل ناقص من الحقل",
         "On, every related-record field offers “create new” so nobody has to leave a form "
         "to add a missing place or institution. Off, the vocabulary is closed: only "
         "existing records can be linked.",
         "عند التشغيل، يعرض كل حقل مرتبط خيار «إنشاء جديد» دون مغادرة النموذج. وعند الإيقاف تكون المفردات مغلقة: لا يُربط إلا سجل موجود.",
         personal=True, effect="components/fields.js → combobox({allowCreate})"),

    # ---- search ---------------------------------------------------------
    Spec("search.min_chars", "search", "int", "2",
         "Characters before searching", "عدد الأحرف قبل البحث",
         "Global search waits for this many characters before it queries the server.",
         "ينتظر البحث الشامل هذا العدد من الأحرف قبل الاستعلام من الخادم.",
         minimum=1, maximum=5, personal=True,
         effect="app.js global search → /api/search"),
    Spec("search.results_limit", "search", "int", "20",
         "Results in the search panel", "عدد النتائج في لوحة البحث",
         "How many hits the global search panel shows per group, before asking for more.",
         "عدد النتائج التي تعرضها لوحة البحث لكل مجموعة قبل طلب المزيد.",
         minimum=5, maximum=100, personal=True,
         effect="app.js global search → /api/search?limit="),

    # ---- import & export ------------------------------------------------
    Spec("import.max_rows", "transfer", "int", "20000",
         "Maximum rows per import", "أقصى عدد صفوف في الاستيراد",
         "A commit above this many rows is refused before anything is written, so one bad "
         "file cannot stall the registry.",
         "يُرفض التنفيذ إذا تجاوز عدد الصفوف هذه القيمة قبل كتابة أي شيء، فلا يُعطّل ملفٌّ سيئ السجلّ.",
         minimum=100, maximum=500000,
         effect="api.import_commit() → 422 with the measured row count"),
    Spec("import.default_mode", "transfer", "enum", "create",
         "Default import mode", "نمط الاستيراد الافتراضي",
         "What the import wizard starts with: only create new records, only update matched "
         "ones, or both.",
         "ما يبدأ به معالج الاستيراد: إنشاء سجلات جديدة فقط، أو تحديث المتطابق فقط، أو الاثنان.",
         values=("create", "update", "upsert"),
         effect="api.import_commit() default + views import wizard"),
    Spec("export.max_rows", "transfer", "int", "50000",
         "Maximum rows per export", "أقصى عدد صفوف في التصدير",
         "An export larger than this fails with a clear message instead of producing a file "
         "that silently stops early.",
         "يفشل التصدير الأكبر من هذه القيمة برسالة واضحة بدل إنتاج ملف يتوقف بصمت.",
         minimum=1000, maximum=500000,
         effect="transfer.export_bytes() ceiling"),

    # ---- validation & data quality --------------------------------------
    Spec("validation.require_source_on_publish", "quality", "bool", "true",
         "Require a source before publishing", "اشتراط مصدر قبل النشر",
         "A record cannot move to a published/verified status while it has no citation or "
         "primary source. Every published claim must be traceable.",
         "لا يمكن ترقية السجل إلى حالة منشور/موثّق دون اقتباس أو مصدر أساسي. كل ادّعاء منشور يجب أن يكون قابلاً للتتبّع.",
         effect="repo.create_record()/update_record() → 422"),
    Spec("validation.min_completeness", "quality", "int", "0",
         "Minimum completeness to publish (%)", "أدنى نسبة اكتمال للنشر (٪)",
         "0 disables the floor. Above 0, publishing a record below this completeness is "
         "refused, with the missing fields listed.",
         "القيمة ٠ تعطّل الحد. وفوقها يُرفض نشر سجل اكتماله أقل من ذلك، مع سرد الحقول الناقصة.",
         minimum=0, maximum=100,
         effect="repo.create_record()/update_record() → 422"),
    Spec("validation.require_reason_for_delete", "quality", "bool", "false",
         "Require a reason to delete", "اشتراط سبب للحذف",
         "Deletes and merges must carry a reason, which is written to the audit trail.",
         "يجب أن يحمل الحذف والدمج سبباً يُكتب في سجل التدقيق.",
         effect="repo.soft_delete()/hard_delete()/merge_records() → 422"),

    # ---- audit ----------------------------------------------------------
    Spec("audit.retention_days", "audit", "int", "0",
         "Audit retention (days)", "مدة الاحتفاظ بالتدقيق (أيام)",
         "0 keeps the audit trail forever — the default, and the safe answer. Above 0, "
         "POST /api/maintenance/prune removes change-log rows older than this.",
         "القيمة ٠ تحتفظ بسجل التدقيق إلى الأبد، وهي الافتراضية والآمنة. وفوقها يحذف أمر الصيانة الصفوف الأقدم من ذلك.",
         minimum=0, maximum=36500,
         effect="api.maintenance_prune() — refuses to run while 0"),

    # ---- maintenance ----------------------------------------------------
    Spec("maintenance.backup_includes_files", "maintenance", "bool", "true",
         "Backups include uploaded files", "النسخ الاحتياطي يشمل الملفات المرفوعة",
         "Whether the one-click backup ZIP contains uploads/ as well as the database. A "
         "database-only ZIP is faster but loses images and attachments.",
         "هل يشمل ملف ZIP للنسخ الاحتياطي مجلد المرفوعات مع قاعدة البيانات. الاستغناء عنه أسرع لكنه يفقد الصور والمرفقات.",
         effect="api.maintenance_backup() default"),
    Spec("maintenance.vacuum_after_import", "maintenance", "bool", "false",
         "Compact the database after each import", "ضغط قاعدة البيانات بعد كل استيراد",
         "Runs VACUUM once a commit finishes. Slower, but keeps the file small on "
         "import-heavy days.",
         "ينفّذ VACUUM بعد انتهاء التنفيذ. أبطأ، لكنه يبقي حجم الملف صغيراً في أيام الاستيراد الكثيف.",
         effect="api.import_commit() → db.vacuum()"),

    # ---- map & geography ------------------------------------------------
    Spec("map.provider", "map", "enum", "local",
         "Base map provider", "مزوّد خريطة الأساس",
         "Where the base map comes from: the offline vector pack, a standard street "
         "map, aerial imagery (plain or hybrid) or terrain. The offline pack needs no "
         "network and no third party; the raster providers are drawn from their public "
         "tile services and require the attribution they state to stay visible.",
         "مصدر خريطة الأساس: الحزمة المتجهية دون اتصال، أو خريطة شوارع قياسية، أو صور "
         "جوية (مباشرة أو هجينة)، أو تضاريس. الحزمة المتجهية تعمل دون اتصال ودون طرف "
         "ثالث؛ أما مزوّدات البلاطات فتُحمَّل من خدماتها العامة ويجب إبقاء الإسناد ظاهراً.",
         values=_MAP_PROVIDER_VALUES, personal=True,
         choices=_MAP_PROVIDER_CHOICES, choice_groups=_MAP_PROVIDER_GROUPS,
         effect="core.js mapDefault() → geomap.js applyProvider(), list.js map tabs, "
                "geopin.js secondaryStyle(), desk.js street map"),
    Spec("map.center_lat", "map", "decimal", "33.3152",
         "Initial latitude", "خط العرض الابتدائي",
         "Where the map opens when there is no view to restore. Validated on write "
         "(-90…90); a saved personal view wins over it.",
         "أين تُفتح الخريطة عند عدم وجود عرض محفوظ. يُتحقق منه عند الكتابة (-90…90)، "
         "والعرض الشخصي المحفوظ يتقدّم عليه.",
         minimum=-90.0, maximum=90.0,
         personal=True, effect="core.js mapDefault() → geomap.js initial view"),
    Spec("map.center_lon", "map", "decimal", "44.3661",
         "Initial longitude", "خط الطول الابتدائي",
         "Longitude of the initial view (-180…180). Values outside that range are "
         "refused rather than wrapped, so a typo is visible.",
         "خط طول العرض الابتدائي (-180…180). القيم خارج هذا المدى تُرفض ولا تُلَفّ، "
         "ليظهر الخطأ بدل أن يخفى.",
         minimum=-180.0, maximum=180.0,
         personal=True, effect="core.js mapDefault() → geomap.js initial view"),
    Spec("map.zoom", "map", "int", "5",
         "Initial zoom", "التكبير الابتدائي",
         "Zoom level the map opens at (1 = world, 18 = street).",
         "مستوى التكبير عند فتح الخريطة (1 = العالم، 18 = الشارع).",
         minimum=1, maximum=18, personal=True,
         effect="core.js mapDefault() → geomap.js initial view"),
    Spec("map.max_points", "map", "int", "4000",
         "Maximum markers per view", "أقصى عدد علامات في العرض",
         "How many records the server returns for one viewport. The map reports what "
         "it left out and asks the reader to zoom in; it never draws a silent sample.",
         "عدد السجلات التي يعيدها الخادم لنافذة عرض واحدة. تُبيّن الخريطة ما استُثني "
         "وتطلب التكبير؛ ولا ترسم عيّنة صامتة.",
         minimum=100, maximum=20000,
         effect="api.map_features() → app.geo.mapdata.features(limit)"),
    Spec("map.cluster", "map", "bool", "true",
         "Group nearby markers", "تجميع العلامات المتقاربة",
         "Groups markers that would overlap into one countable cluster that opens when "
         "clicked. Turn it off to see every marker separately, including stacked ones.",
         "تجميع العلامات المتداخلة في عنقود معدود يُفتح عند النقر. أوقفه لعرض كل علامة "
         "على حدة، بما فيها المتراكبة.",
         personal=True, effect="views/geomap.js cluster source (MapLibre supercluster)"),
    Spec("map.units", "map", "enum", "metric",
         "Measurement units", "وحدات القياس",
         "Units for the distance and area tools.",
         "وحدات أداتَي المسافة والمساحة.",
         values=("metric", "imperial"), personal=True,
         effect="app.geo.spatial.format_distance() → views/geomap.js measure panel"),
    Spec("map.show_labels", "map", "bool", "true",
         "Place labels on the map", "أسماء الأماكن على الخريطة",
         "Draws a name next to markers once the zoom is high enough for it to be "
         "readable. Labels never overlap deliberately: the map thins them out.",
         "يرسم اسماً بجوار العلامة عندما يكفي التكبير لقراءته، وتُخفَّف الأسماء تلقائياً "
         "لمنع التداخل.",
         personal=True, effect="views/geomap.js labelLayer()"),
    Spec("map.download_max_zoom", "map", "int", "15",
         "Download zoom ceiling", "سقف تكبير التنزيل",
         "The deepest zoom a map download may request. Street-level detail multiplies "
         "tiles by four per step; the ceiling keeps one click from pulling millions.",
         "أعمق تكبير يطلبه تنزيل الخرائط. تفاصيل الشوارع تضاعف البلاطات أربع مرات مع "
         "كل درجة؛ يمنع السقف سحب ملايين البلاطات بنقرة واحدة.",
         minimum=1, maximum=19,
         effect="map_api.py POST /api/geo/downloads → job maxzoom validation"),
    Spec("map.download_max_tiles", "map", "int", "25000",
         "Download size cap", "حد حجم التنزيل",
         "The most tiles one download job may store. Beyond the cap the request is "
         "refused with the count it would have needed.",
         "أقصى عدد من البلاطات يخزّنه عمل تنزيل واحد. ما يتجاوز الحقف يُرفض مع بيان "
         "العدد المطلوب.",
         minimum=100, maximum=500000,
         effect="tiledownload.create_job() → job max_tiles validation"),
    Spec("map.download_delay_ms", "map", "int", "250",
         "Download politeness delay", "تأدب تأخير التنزيل",
         "Milliseconds waited between tile fetches, so downloads stay polite to the "
         "public tile services the map providers publish.",
         "المللي ثانية بين طلبات البلاطات، ليبقى التنزيل مهذباً أمام خدمات البلاطات "
         "العامة التي ينشرها المزوّدون.",
         minimum=0, maximum=5000,
         effect="tiledownload._run_job() → per-tile sleep"),
    Spec("map.overlays", "map", "text", "place_hierarchy",
         "Vector overlays", "الطبقات المتجهية",
         "Comma-separated overlays drawn over the basemap: 'relationships' draws a line "
         "for every relationship whose two ends are located, 'place_hierarchy' draws "
         "the parent → child geometry of the place tree. The hierarchy is on by default: "
         "1 817 relationship arcs over one country is a thicket, not information — the "
         "relationship overlay is one click away in the Layers menu.",
         "طبقات مرسومة فوق خريطة الأساس مفصولة بفواصل: 'relationships' يرسم خطاً لكل "
         "علاقة طرفاها محددان جغرافياً، و'place_hierarchy' يرسم تسلسل الأماكن الأصلية والفرعية.",
         personal=True, effect="api.map_overlays() → views/geomap.js overlay layers"),
)

_BY_KEY: dict[str, Spec] = {s.key: s for s in SPECS}


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------
def spec(key: str) -> Spec | None:
    return _BY_KEY.get(key)


def keys() -> list[str]:
    return [s.key for s in SPECS]


def group_specs(group: str) -> list[Spec]:
    return [s for s in SPECS if s.group == group]


def stored(conn: sqlite3.Connection) -> dict[str, str]:
    """Everything actually written to the `setting` table (overrides only)."""
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM setting")}


def overrides(conn: sqlite3.Connection) -> dict[str, str]:
    """Stored values that differ from the declared default, i.e. deliberate choices."""
    out = {}
    for k, v in stored(conn).items():
        sp = spec(k)
        if sp is None or str(v) != sp.default:
            out[k] = v
    return out


def effective(conn: sqlite3.Connection) -> dict[str, Any]:
    """Every declared key → its typed value (stored override, else the default)."""
    raw = stored(conn)
    out: dict[str, Any] = {}
    for sp in SPECS:
        v = raw.get(sp.key)
        try:
            out[sp.key] = sp.coerce(sp.default if v is None else v)
        except ValueError:                       # a hand-edited row that no longer validates
            out[sp.key] = sp.typed_default
    return out


def defaults() -> dict[str, str]:
    """Every declared key → its default, in canonical string form, with no database.

    Used to seed a fresh registry (`app/seed.py`) and by the schema endpoint, so a
    brand-new install and a ten-year-old one describe the same configuration.
    """
    return {sp.key: sp.store(sp.default) for sp in SPECS}


def as_strings(conn: sqlite3.Connection) -> dict[str, str]:
    """Every key → its canonical string form ("true"/"false" for booleans).

    This is the shape `/api/meta` and the browser consume: a value the frontend
    can compare without re-implementing Python's truthiness.
    """
    return {sp.key: sp.store(effective(conn)[sp.key]) for sp in SPECS}


def get(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    """The typed value of one setting — what consumers call."""
    sp = spec(key)
    if sp is None:
        raise KeyError(key)
    row = conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
    if row is None:
        return sp.typed_default if default is None else default
    try:
        return sp.coerce(row["value"])
    except ValueError:
        return sp.typed_default if default is None else default


def get_str(conn: sqlite3.Connection, key: str) -> str:
    """The canonical string form (what the API and the screen show)."""
    sp = spec(key)
    return sp.store(get(conn, key)) if sp else ""


def schema() -> dict:
    """The machine-readable registry: groups, then the specs inside each."""
    return {
        "groups": [{"key": g, "label_en": en, "label_ar": ar, "icon": icon}
                   for g, en, ar, icon in GROUPS],
        "fields": [s.public() for s in SPECS],
    }


def as_document(conn: sqlite3.Connection) -> dict:
    """Everything a client needs to render the screen and to know what is in force."""
    raw = stored(conn)
    eff = effective(conn)
    fields = []
    for sp in SPECS:
        row = raw.get(sp.key)
        value = sp.store(eff[sp.key])
        # "instance" means *this value was chosen here*; a row that merely repeats
        # the shipped default (a reset leaves one behind, as does a restart) is
        # still the default, and the screen must say so rather than claim an
        # override nobody made.
        is_default = value == sp.store(sp.default)
        fields.append({
            **sp.public(),
            "value": value,
            "source": "default" if is_default else "instance",
            "updated_at": conn.execute(
                "SELECT updated_at FROM setting WHERE key=?", (sp.key,)
            ).fetchone()["updated_at"] if row is not None else None,
            "is_default": is_default,
            "stored": row is not None,
        })
    return {"groups": schema()["groups"], "fields": fields,
            "overrides": len([f for f in fields if f["source"] == "instance"])}


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def validate(payload: dict) -> tuple[dict[str, str], list[dict]]:
    """Split a payload into (canonical values, problems).  Nothing is written here."""
    clean: dict[str, str] = {}
    problems: list[dict] = []
    if not isinstance(payload, dict):
        return {}, [{"key": None, "reason": "not_an_object", "message": "Body must be an object"}]
    for key, value in payload.items():
        sp = spec(key)
        if sp is None:
            problems.append({"key": key, "value": value, "reason": "unknown_key",
                             "message": f"'{key}' is not a known setting",
                             "known": keys()[:3] + ["…"]})
            continue
        try:
            clean[key] = sp.store(value)
        except ValueError as exc:
            reason = str(exc)
            problems.append({
                "key": key, "value": value, "reason": reason,
                "kind": sp.kind, "values": list(sp.values),
                "minimum": sp.minimum, "maximum": sp.maximum,
                "message": _reason_text(sp, reason),
            })
    return clean, problems


def _reason_text(sp: Spec, reason: str) -> str:
    if reason == "not_bool":
        return f"'{sp.key}' takes true or false"
    if reason == "not_integer":
        return f"'{sp.key}' takes a whole number"
    if reason == "below_minimum":
        return f"'{sp.key}' must be at least {sp.minimum}"
    if reason == "above_maximum":
        return f"'{sp.key}' must be at most {sp.maximum}"
    if reason == "not_allowed":
        return f"'{sp.key}' must be one of: " + ", ".join(sp.values)
    return f"'{sp.key}' is not valid"


def save(conn: sqlite3.Connection, payload: dict, actor: str = "admin",
         reason: str | None = None) -> dict:
    """Validate, store and audit.  Returns {changed, settings, problems}."""
    clean, problems = validate(payload)
    if problems:
        # all-or-nothing: a refused payload writes nothing at all
        return {"changed": [], "problems": problems, "settings": effective(conn)}
    before = effective(conn)
    changed: list[dict] = []
    for key, value in clean.items():
        old = before.get(key)
        if str(old) == value or (isinstance(old, bool) and ("true" if old else "false") == value):
            continue
        conn.execute(
            """INSERT INTO setting (key, value, updated_at) VALUES (?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value,
               updated_at=excluded.updated_at""", (key, value, db.now()))
        changed.append({"key": key, "old": None if old is None else str(old), "new": value})
        db.log_change(conn, entity_type="setting", entity_id=None, entity_code=key,
                      action="update", field_key=key,
                      field_label=spec(key).label_en if spec(key) else key,
                      old_value=None if old is None else str(old), new_value=value,
                      actor=actor, reason=reason or "settings", notes="configuration")
    if changed:
        conn.commit()
    return {"changed": changed, "problems": problems, "settings": effective(conn)}


def reset(conn: sqlite3.Connection, keys_to_reset: Iterable[str] | None = None,
          group: str | None = None, actor: str = "admin") -> dict:
    """Drop overrides so the declared defaults apply again (audited)."""
    targets = list(keys_to_reset or [])
    if group:
        targets += [s.key for s in group_specs(group)]
    if not targets:
        targets = keys()
    unknown = [k for k in targets if spec(k) is None]
    targets = [k for k in targets if spec(k) is not None]
    before = effective(conn)
    reset_keys: list[str] = []
    changed: list[str] = []
    for key in targets:
        cur = conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        if cur is None:
            continue
        sp = spec(key)
        conn.execute("DELETE FROM setting WHERE key=?", (key,))
        reset_keys.append(key)
        # A row that already held the declared default is dropped, but there is
        # nothing to record: logging "25 → 25" would bury the real changes in the
        # audit trail (a "reset everything" used to write 18 such rows).
        if sp.store(cur["value"]) == sp.store(sp.default):
            continue
        changed.append(key)
        db.log_change(conn, entity_type="setting", entity_id=None, entity_code=key,
                      action="update", field_key=key, field_label=sp.label_en,
                      old_value=cur["value"], new_value=sp.default,
                      actor=actor, reason="settings reset", notes="back to the default")
    if reset_keys:
        conn.commit()
        # leave one row per declared key behind, so `SELECT * FROM setting` still
        # lists the whole configuration after a reset (the value is the default;
        # `source` reports "default", so nothing looks overridden)
        ensure(conn)
    return {"reset": reset_keys, "changed": changed, "unknown": unknown,
            "settings": effective(conn),
            "before": {k: str(before[k]) for k in reset_keys}}


def ensure(conn: sqlite3.Connection) -> int:
    """Make sure the table carries a row per declared key (idempotent, called at boot).

    A row is *not* required — absence means "use the default" — but the shipped
    database has always carried them, and operators read the table directly.  We
    insert the default when a key is missing entirely, so `SELECT * FROM setting`
    still lists the whole configuration.
    """
    have = {r["key"] for r in conn.execute("SELECT key FROM setting")}
    added = 0
    for sp in SPECS:
        if sp.key not in have:
            conn.execute("INSERT OR IGNORE INTO setting (key, value) VALUES (?,?)",
                         (sp.key, sp.default))
            added += 1
    if added:
        conn.commit()
    return added

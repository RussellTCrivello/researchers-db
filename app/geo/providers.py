"""
SIRAJ · base map providers.

A map is only as trustworthy as its base layer, and a base layer is only usable if its
terms are known. So every provider here is a **declaration**, not a URL buried in the
frontend: its family, its kind, its tiles (or the fact that it needs none), its maximum
zoom, the attribution string that must be displayed, the licence, and the usage rules a
deployment has to respect.

Four families, so a researcher can pick the cartography the question needs:

  * **offline** — the shipped Natural Earth vector pack (`app/geo/basemap.sqlite`). No
    network, no third party, no rate limit, public domain. This is the default, because a
    registry that stops working when a tile server is unreachable is not a registry.
  * **standard** — road/street cartography: OpenStreetMap, Esri World Street Map and the
    two CARTO basemaps. Readable place names, good for orientation.
  * **aerial** — satellite and aerial imagery: Esri World Imagery, and a hybrid of that
    imagery with a boundaries-and-places reference layer. This is what a field survey
    uses to see the ground itself — a tell, a mound, a shoreline that moved.
  * **terrain** — OpenTopoMap: contours, relief and hydrography.

Choosing a provider is a setting (`map.provider`) and a personal preference; its
attribution is rendered in the map corner by contract, its licence and terms URL travel
with it, and the map refuses to start a provider it does not know rather than silently
drawing an empty canvas.
"""
from __future__ import annotations

NATURAL_EARTH = {
    "label_en": "Natural Earth (public domain)",
    "label_ar": "ناتشورال إيرث (ملكية عامة)",
    "url": "https://www.naturalearthdata.com/about/terms-of-use/",
}

ESRI_IMAGERY_ATTR_EN = ("Imagery © Esri, Maxar, Earthstar Geographics, "
                        "and the GIS User Community")
ESRI_IMAGERY_ATTR_AR = ("الصور © إيزري، ماكسار، إيرثستار جيوغرافيكس، "
                        "ومجتمع مستخدمي نظم المعلومات الجغرافية")
ESRI_TERMS = "https://www.esri.com/en-us/legal/terms/full-master-agreement"

PROVIDERS = {
    # ------------------------------------------------------------- offline ---
    "local": {
        "id": "local",
        "kind": "vector-local",
        "group": "offline",
        "swatch": "#cfdbe6",
        "label_en": "Offline vector basemap",
        "label_ar": "خريطة أساس متجهية دون اتصال",
        "hint_en": "Ships with the application: countries, provinces, urban areas, "
                   "coastlines, lakes, rivers and cities from the bundled Natural Earth "
                   "pack. Covers the whole world with no network.",
        "hint_ar": "تُشحن مع التطبيق: الدول والمقاطعات والمناطق الحضرية والسواحل "
                   "والبحيرات والأنهار والمدن من حزمة ناتشورال إيرث المرفقة، وتغطي "
                   "العالم كله دون اتصال.",
        "requires_network": False,
        "max_zoom": 12,
        "attribution_en": "Basemap: Natural Earth (public domain)",
        "attribution_ar": "خريطة الأساس: ناتشورال إيرث (ملكية عامة)",
        "attribution_url": NATURAL_EARTH["url"],
        "license": "public domain",
        "terms_url": NATURAL_EARTH["url"],
        "usage_en": "No limits and no tracking. Attribution is shown even though the "
                    "licence does not require it.",
        "usage_ar": "بلا حدود وبلا تتبّع. يُعرض الإسناد رغم أن الترخيص لا يشترطه.",
                "downloadable": False,
        "download_note_en": "This map type ships with the application — the bundled world packs already store it permanently.",
        "download_note_ar": "نوع الخريطة هذا مرفق مع التطبيق — الحزم العالمية المرفقة تخزّنه بشكل دائم أصلاً.",
"style": {
            "version": 8,
            "name": "SIRAJ local",
            "sources": {},
            "layers": [
                {"id": "background", "type": "background",
                 "paint": {"background-color": "#e9eef3"}},
            ],
            # the vector layers themselves are added by the client from the local
            # pack, because they arrive as GeoJSON per viewport rather than as tiles
            "metadata": {"siraj:local_basemap": True},
        },
    },
    # ------------------------------------------------------------ standard ---
    "osm": {
        "id": "osm",
        "kind": "raster",
        "group": "standard",
        "swatch": "#eef3e6",
        "label_en": "OpenStreetMap (standard)",
        "label_ar": "خريطة الشارع المفتوح (قياسية)",
        "hint_en": "The OpenStreetMap standard tiles. Community-funded infrastructure: "
                   "suitable for light, interactive use, not for bulk downloads.",
        "hint_ar": "بلاطات خريطة الشارع المفتوح القياسية. بنية مجتمعية: مناسبة للاستخدام "
                   "التفاعلي الخفيف، لا للتنزيل الكثيف.",
        "requires_network": True,
        "max_zoom": 19,
        "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        "tile_size": 256,
        "attribution_en": "© OpenStreetMap contributors",
        "attribution_ar": "© مساهمو خريطة الشارع المفتوح",
        "attribution_url": "https://www.openstreetmap.org/copyright",
        "license": "ODbL 1.0",
        "terms_url": "https://operations.osmfoundation.org/policies/tiles/",
        "usage_en": "Tile usage policy applies: keep traffic modest, set a valid "
                    "User-Agent/Referer, no bulk downloading, no offline scraping. For "
                    "heavy use, run your own tile server or use a commercial provider.",
        "usage_ar": "تنطبق سياسة استخدام البلاطات: حافظ على حركة معتدلة، واستخدم معرّفاً "
                    "صالحاً، ولا تنزّل البلاطات جملةً. للاستخدام الكثيف شغّل خادمك الخاص.",
                "downloadable": False,
        "download_note_en": "OpenStreetMap's tile usage policy forbids bulk downloading and offline scraping. Use the bundled world street map for offline work — it stores the same map type permanently and needs no third party.",
        "download_note_ar": "سياسة بلاطات خريطة الشارع المفتوح تمنع التنزيل الجماعي والنسخ دون اتصال. استخدم خريطة الشوارع العالمية المرفقة للعمل دون اتصال — فهي تخزّن نوع الخريطة نفسه بشكل دائم ودون طرف ثالث.",
"style": {
            "version": 8,
            "name": "SIRAJ · OSM",
            "sources": {"base": {"type": "raster",
                                 "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                                 "tileSize": 256, "maxzoom": 19,
                                 "attribution": "© OpenStreetMap contributors"}},
            "layers": [{"id": "base", "type": "raster", "source": "base"}],
        },
    },
    "esri-street": {
        "id": "esri-street",
        "kind": "raster",
        "group": "standard",
        "swatch": "#f5f2e8",
        "label_en": "Esri World Street Map",
        "label_ar": "خريطة الشوارع العالمية من إيزري",
        "hint_en": "A second standard street style with denser labels and shaded "
                   "relief — useful when OpenStreetMap's styling is not legible enough.",
        "hint_ar": "نمط شوارع قياسي ثانٍ بأسماء أكثر وتظليل للتضاريس، مفيد عندما لا تكون "
                   "خرائط الشارع المفتوح واضحة بما يكفي.",
        "requires_network": True,
        "max_zoom": 19,
        "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Street_Map/MapServer/tile/{z}/{y}/{x}"],
        "tile_size": 256,
        "attribution_en": "© Esri, HERE, Garmin, USGS, © OpenStreetMap contributors",
        "attribution_ar": "© إيزري، هير، غارمين، هيئة المسح الجيولوجي الأمريكية، "
                          "© مساهمو خريطة الشارع المفتوح",
        "attribution_url": "https://www.esri.com/en-us/legal/terms/full-master-agreement",
        "license": "Esri Terms of Use · ODbL 1.0 (OSM data)",
        "terms_url": ESRI_TERMS,
        "usage_en": "Esri's public basemap services are offered for use with attribution "
                    "under the Esri Terms of Use. A deployment with sustained traffic "
                    "should use an ArcGIS location-platform key of its own.",
        "usage_ar": "تُقدَّم خدمات إيزري العامة مع الإسناد وفق شروط الاستخدام. النسخ "
                    "عالية الحركة ينبغي أن تستخدم مفتاحاً خاصاً بها.",
                "downloadable": True,
        "download_note_en": "Esri's terms allow modest local caching with attribution kept visible. Keep downloads to the regions your research needs.",
        "download_note_ar": "شروط إيزري تسمح بتخزين محلي محدود مع إبقاء الإسناد ظاهراً. اقتصر على مناطق بحثك.",
"style": {
            "version": 8,
            "name": "SIRAJ · Esri street",
            "sources": {"base": {"type": "raster",
                                 "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/"
                                           "services/World_Street_Map/MapServer/tile/"
                                           "{z}/{y}/{x}"],
                                 "tileSize": 256, "maxzoom": 19,
                                 "attribution": "© Esri, HERE, Garmin, USGS, "
                                                "© OpenStreetMap contributors"}},
            "layers": [{"id": "base", "type": "raster", "source": "base"}],
        },
    },
    "carto-light": {
        "id": "carto-light",
        "kind": "raster",
        "group": "standard",
        "swatch": "#f4f4f2",
        "label_en": "CARTO Positron (light)",
        "label_ar": "كارتو بوزيترون (فاتح)",
        "hint_en": "A muted grey basemap that keeps the registry's own markers and "
                   "overlays the most legible layer on screen.",
        "hint_ar": "خريطة أساس رمادية هادئة تُبرز معالم السجل وطبقاته فوقها.",
        "requires_network": True,
        "max_zoom": 20,
        "tiles": ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
                  "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
                  "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"],
        "tile_size": 256,
        "attribution_en": "© OpenStreetMap contributors · © CARTO",
        "attribution_ar": "© مساهمو خريطة الشارع المفتوح · © كارتو",
        "attribution_url": "https://carto.com/attributions",
        "license": "ODbL 1.0 (data) · CARTO terms (tiles)",
        "terms_url": "https://carto.com/basemaps",
        "usage_en": "Free for light use with attribution. Read CARTO's basemap terms "
                    "before pointing a public, high-traffic instance at them.",
        "usage_ar": "مجانية للاستخدام الخفيف مع الإسناد. راجع شروط خرائط كارتو قبل "
                    "توجيه نسخة عامة عالية الحركة إليها.",
                "downloadable": True,
        "download_note_en": "Free for light use with attribution — modest regional downloads are within the terms; read CARTO's basemap terms for scale limits.",
        "download_note_ar": "استخدام خفيف مجاني مع الإسناد — التنزيلات الإقليمية المحدودة ضمن الشروط؛ راجع شروط بلاطات كارتو للحدود.",
"style": {
            "version": 8,
            "name": "SIRAJ · CARTO light",
            "sources": {"base": {"type": "raster",
                                 "tiles": ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
                                           "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
                                           "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"],
                                 "tileSize": 256, "maxzoom": 20,
                                 "attribution": "© OpenStreetMap contributors · © CARTO"}},
            "layers": [{"id": "base", "type": "raster", "source": "base"}],
        },
    },
    "carto-dark": {
        "id": "carto-dark",
        "kind": "raster",
        "group": "standard",
        "swatch": "#2b2f33",
        "label_en": "CARTO Dark Matter",
        "label_ar": "كارتو دارك ماتر",
        "hint_en": "A dark basemap for bright overlays and for work in a dim room.",
        "hint_ar": "خريطة أساس داكنة تُبرز الطبقات الفاتحة وتناسب العمل في إضاءة خفيفة.",
        "requires_network": True,
        "max_zoom": 20,
        "tiles": ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
                  "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
                  "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"],
        "tile_size": 256,
        "attribution_en": "© OpenStreetMap contributors · © CARTO",
        "attribution_ar": "© مساهمو خريطة الشارع المفتوح · © كارتو",
        "attribution_url": "https://carto.com/attributions",
        "license": "ODbL 1.0 (data) · CARTO terms (tiles)",
        "terms_url": "https://carto.com/basemaps",
        "usage_en": "Same terms as the light basemap; attribution stays visible.",
        "usage_ar": "الشروط نفسها المطبقة على الخريطة الفاتحة، مع إبقاء الإسناد ظاهراً.",
                "downloadable": True,
        "download_note_en": "Free for light use with attribution — modest regional downloads are within the terms; read CARTO's basemap terms for scale limits.",
        "download_note_ar": "استخدام خفيف مجاني مع الإسناد — التنزيلات الإقليمية المحدودة ضمن الشروط؛ راجع شروط بلاطات كارتو للحدود.",
"style": {
            "version": 8,
            "name": "SIRAJ · CARTO dark",
            "sources": {"base": {"type": "raster",
                                 "tiles": ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
                                           "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
                                           "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"],
                                 "tileSize": 256, "maxzoom": 20,
                                 "attribution": "© OpenStreetMap contributors · © CARTO"}},
            "layers": [{"id": "base", "type": "raster", "source": "base"}],
        },
    },
    # -------------------------------------------------------------- aerial ---
    "esri-imagery": {
        "id": "esri-imagery",
        "kind": "raster",
        "group": "aerial",
        "swatch": "#5b6b4a",
        "label_en": "Aerial imagery",
        "label_ar": "صور جوية",
        "hint_en": "Satellite and aerial photographs of the ground itself — the view a "
                   "field survey needs to see a site, a shoreline or a road that a drawn "
                   "map does not show.",
        "hint_ar": "صور بالأقمار الصناعية وجواً للأرض نفسها — العرض الذي يحتاجه المسح "
                   "الميداني لرؤية موقع أو ساحل أو طريق لا تُظهره الخريطة المرسومة.",
        "requires_network": True,
        "max_zoom": 19,
        "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        "tile_size": 256,
        "attribution_en": ESRI_IMAGERY_ATTR_EN,
        "attribution_ar": ESRI_IMAGERY_ATTR_AR,
        "attribution_url": ESRI_TERMS,
        "license": "Esri Terms of Use (imagery © Esri, Maxar, Earthstar Geographics)",
        "terms_url": ESRI_TERMS,
        "usage_en": "Imagery is served by Esri's public World Imagery service and must "
                    "keep its attribution. Sustained or commercial traffic should use an "
                    "ArcGIS location-platform key or a licensed imagery service.",
        "usage_ar": "تُقدَّم الصور من خدمة إيزري العامة ويجب إبقاء الإسناد ظاهراً. "
                    "الاستخدام المستمر أو التجاري ينبغي أن يستخدم مفتاحاً أو خدمة مرخّصة.",
                "downloadable": True,
        "download_note_en": "Esri permits local caching of reasonable quantities with attribution. Keep downloads to the regions your research needs.",
        "download_note_ar": "إيزري يسمح بتخزين محلي بكميات معقولة مع الإسناد. اقتصر على مناطق بحثك.",
"style": {
            "version": 8,
            "name": "SIRAJ · aerial imagery",
            "sources": {"imagery": {"type": "raster",
                                    "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/"
                                              "services/World_Imagery/MapServer/tile/"
                                              "{z}/{y}/{x}"],
                                    "tileSize": 256, "maxzoom": 19,
                                    "attribution": ESRI_IMAGERY_ATTR_EN}},
            "layers": [{"id": "imagery", "type": "raster", "source": "imagery"}],
        },
    },
    "esri-hybrid": {
        "id": "esri-hybrid",
        "kind": "raster",
        "group": "aerial",
        "swatch": "#6d7f57",
        "label_en": "Aerial hybrid (imagery + labels)",
        "label_ar": "صور جوية هجينة (صور + أسماء)",
        "hint_en": "Aerial imagery with a boundaries-and-places layer drawn over it: the "
                   "ground and the names on it in one view.",
        "hint_ar": "صور جوية مع طبقة حدود وأسماء فوقها: الأرض وأسماؤها في عرض واحد.",
        "requires_network": True,
        "max_zoom": 19,
        "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/"
                  "World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        "tile_size": 256,
        "attribution_en": ESRI_IMAGERY_ATTR_EN + " · labels © Esri",
        "attribution_ar": ESRI_IMAGERY_ATTR_AR + " · الأسماء © إيزري",
        "attribution_url": ESRI_TERMS,
        "license": "Esri Terms of Use (imagery · reference layer)",
        "terms_url": ESRI_TERMS,
        "usage_en": "Two Esri services in one view (World Imagery and the World "
                    "Boundaries and Places reference layer); both attributions stay "
                    "visible, and the same licensing note as the plain imagery applies.",
        "usage_ar": "خدمتان من إيزري في عرض واحد (الصور العالمية وطبقة الحدود والأسماء)، "
                    "ويبقى الإسنادان ظاهرين، مع ملاحظة الترخيص نفسها.",
                "downloadable": True,
        "download_note_en": "Both Esri layers may be cached locally in reasonable quantities, with both attributions kept visible.",
        "download_note_ar": "يجري تخزين طبقتي إيزري محلياً بكميات معقولة، مع إبقاء الإسنيدين ظاهرين.",
"style": {
            "version": 8,
            "name": "SIRAJ · aerial hybrid",
            "sources": {
                "imagery": {"type": "raster",
                            "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/"
                                      "services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                            "tileSize": 256, "maxzoom": 19,
                            "attribution": ESRI_IMAGERY_ATTR_EN},
                # a transparent reference layer: boundaries and place names only
                "labels": {"type": "raster",
                           "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/"
                                     "services/Reference/World_Boundaries_and_Places/"
                                     "MapServer/tile/{z}/{y}/{x}"],
                           "tileSize": 256, "maxzoom": 19,
                           "attribution": "labels © Esri"},
            },
            "layers": [
                {"id": "imagery", "type": "raster", "source": "imagery"},
                {"id": "labels", "type": "raster", "source": "labels"},
            ],
        },
    },
    # ------------------------------------------------------------- terrain ---
    "opentopomap": {
        "id": "opentopomap",
        "kind": "raster",
        "group": "terrain",
        "swatch": "#e8e2cf",
        "label_en": "Terrain (OpenTopoMap)",
        "label_ar": "التضاريس (أوبن توبو ماب)",
        "hint_en": "Contours, relief and hydrography — for reading a valley, a pass or a "
                   "watershed, which a street map flattens away.",
        "hint_ar": "خطوط كنتور وتضاريس ومجاري مائية — لقراءة وادٍ أو ممرٍّ أو مستجمع "
                   "مائي، وهي ما تُسطّحه خرائط الشوارع.",
        "requires_network": True,
        "max_zoom": 17,
        "tiles": ["https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
                  "https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
                  "https://c.tile.opentopomap.org/{z}/{x}/{y}.png"],
        "tile_size": 256,
        "attribution_en": "© OpenStreetMap contributors · SRTM · © OpenTopoMap (CC-BY-SA)",
        "attribution_ar": "© مساهمو خريطة الشارع المفتوح · بيانات SRTM · © أوبن توبو ماب",
        "attribution_url": "https://opentopomap.org/about",
        "license": "CC-BY-SA 3.0 (tiles) · ODbL 1.0 (data)",
        "terms_url": "https://opentopomap.org/about#tileusage",
        "usage_en": "A community tile service: attribution and share-alike apply, and "
                    "bulk downloading is not permitted. Keep traffic modest.",
        "usage_ar": "خدمة بلاطات مجتمعية: يلزم الإسناد والمشاركة بالمثل، ولا يُسمح "
                    "بالتنزيل الكثيف. حافظ على حركة معتدلة.",
                "downloadable": False,
        "download_note_en": "OpenTopoMap's tile usage policy does not permit bulk downloading. Keep traffic modest and interactive.",
        "download_note_ar": "سياسة بلاطات أوپنتوبوماب لا تسمح بالتنزيل الجماعي. أبقِ الحركة متواضعة وتفاعلية.",
"style": {
            "version": 8,
            "name": "SIRAJ · terrain",
            "sources": {"base": {"type": "raster",
                                 "tiles": ["https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
                                           "https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
                                           "https://c.tile.opentopomap.org/{z}/{x}/{y}.png"],
                                 "tileSize": 256, "maxzoom": 17,
                                 "attribution": "© OpenStreetMap contributors · SRTM · "
                                                "© OpenTopoMap (CC-BY-SA)"}},
            "layers": [{"id": "base", "type": "raster", "source": "base"}],
        },
    },
}

# Street-level offline pack (Gaza vectormap + optional tilepack). The client
# paints the vectormap as GeoJSON overlays; the tilepack (when present) is a
# raster source under /api/geo/tiles/{z}/{x}/{y}.webp.
PROVIDERS["streets-offline"] = {
    "id": "streets-offline",
    "kind": "vector-streets",
    "group": "offline",
    "swatch": "#e8f0e4",
    "label_en": "Offline street map (world)",
    "label_ar": "خريطة الشوارع دون اتصال (العالم)",
    "hint_en": "World base — borders, coastlines, rivers, urban areas and cities — "
               "with OpenStreetMap street detail for the working area. No network. "
               "Ships as compressed vectormaps.",
    "hint_ar": "أساس عالمي — الحدود والسواحل والأنهار والمناطق الحضرية والمدن — "
               "مع تفاصيل شوارع خريطة الشارع المفتوح لمنطقة العمل. بلا شبكة، "
               "تُشحن مضغوطة.",
    "requires_network": False,
    "max_zoom": 18,
    "attribution_en": "© OpenStreetMap contributors",
    "attribution_ar": "© مساهمو خريطة الشارع المفتوح",
    "attribution_url": "https://www.openstreetmap.org/copyright",
    "license": "ODbL 1.0",
    "terms_url": "https://www.openstreetmap.org/copyright",
    "usage_en": "Offline extract for research orientation. Attribution required.",
    "usage_ar": "مقتطف دون اتصال للتوجيه البحثي. يلزم الإسناد.",
            "downloadable": False,
        "download_note_en": "This map type ships with the application — the bundled world packs already store it permanently.",
        "download_note_ar": "نوع الخريطة هذا مرفق مع التطبيق — الحزم العالمية المرفقة تخزّنه بشكل دائم أصلاً.",
"style": {
        "version": 8,
        "name": "SIRAJ streets offline",
        "sources": {},
        "layers": [
            {"id": "background", "type": "background",
             "paint": {"background-color": "#f4f1ea"}},
        ],
        "metadata": {"siraj:streets_offline": True, "siraj:local_basemap": True},
    },
}

PROVIDERS["streets-hybrid"] = {
    "id": "streets-hybrid",
    "kind": "hybrid-streets",
    "group": "offline",
    "swatch": "#dce8f2",
    "label_en": "Offline hybrid (Natural Earth + streets)",
    "label_ar": "مدمجة دون اتصال (ناتشورال إيرث + شوارع)",
    "hint_en": "World Natural Earth underlay with the world street pack on top; "
               "street-level detail where the pack carries it.",
    "hint_ar": "خلفية ناتشورال إيرث العالمية مع حزمة الشوارع العالمية فوقها؛ "
               "وتفصيل على مستوى الشارع حيث تتوفر الحزمة.",
    "requires_network": False,
    "max_zoom": 18,
    "attribution_en": "Basemap: Natural Earth (public domain) · streets © OpenStreetMap contributors",
    "attribution_ar": "الأساس: ناتشورال إيرث (ملكية عامة) · الشوارع © مساهمو خريطة الشارع المفتوح",
    "attribution_url": "https://www.openstreetmap.org/copyright",
    "license": "public domain + ODbL 1.0",
    "terms_url": "https://www.openstreetmap.org/copyright",
    "usage_en": "Both layers ship with the application; no network.",
    "usage_ar": "الطبقتان مرفقان مع التطبيق؛ بلا شبكة.",
            "downloadable": False,
        "download_note_en": "This map type ships with the application — the bundled world packs already store it permanently.",
        "download_note_ar": "نوع الخريطة هذا مرفق مع التطبيق — الحزم العالمية المرفقة تخزّنه بشكل دائم أصلاً.",
"style": {
        "version": 8,
        "name": "SIRAJ streets hybrid",
        "sources": {},
        "layers": [
            {"id": "background", "type": "background",
             "paint": {"background-color": "#e9eef3"}},
        ],
        "metadata": {"siraj:streets_hybrid": True, "siraj:local_basemap": True},
    },
}

DEFAULT_PROVIDER = "local"

#: the families, in the order the Layers menu shows them, with their own labels
GROUPS = ("offline", "standard", "aerial", "terrain")


def catalog() -> list[dict]:
    """Everything the interface needs to offer a choice, minus the tile templates."""
    out = []
    for pid, prov in PROVIDERS.items():
        out.append({
            "id": pid, "kind": prov["kind"],
            "group": prov.get("group", "standard"), "swatch": prov.get("swatch", "#ccc"),
            "label_en": prov["label_en"], "label_ar": prov["label_ar"],
            "hint_en": prov["hint_en"], "hint_ar": prov["hint_ar"],
            "requires_network": prov["requires_network"],
            "max_zoom": prov["max_zoom"],
            "attribution_en": prov["attribution_en"],
            "attribution_ar": prov["attribution_ar"],
            "attribution_url": prov["attribution_url"],
            "license": prov["license"], "terms_url": prov["terms_url"],
            "usage_en": prov["usage_en"], "usage_ar": prov["usage_ar"],
            "downloadable": prov.get("downloadable", False),
            "download_note_en": prov.get("download_note_en", ""),
            "download_note_ar": prov.get("download_note_ar", ""),
        })
    return out


def grouped() -> list[dict]:
    """The catalogue arranged by family — what the Layers menu renders."""
    out = []
    for group in GROUPS:
        members = [p for p in catalog() if p["group"] == group]
        if members:
            out.append({"id": group, "providers": members})
    return out


def get(provider_id: str | None) -> dict:
    """The provider, or the default — never an exception, never a blank map."""
    return PROVIDERS.get(provider_id or DEFAULT_PROVIDER, PROVIDERS[DEFAULT_PROVIDER])

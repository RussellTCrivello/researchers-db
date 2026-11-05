"""
Build compact country + governorate/province reference JSON for seed.py.

Downloads ISO sources into app/resources/ when missing, then writes:
  app/resources/countries.json
  app/resources/governorates.json

Selection for governorates/provinces:
  • every ISO 3166-2 subdivision with no parentCode (first-level), plus
  • every Governorate / Province / State / Emirate even when nested under a region
    (so e.g. Erbil still appears under Iraq).

Run:  python scripts/build_geo_ref.py
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "app" / "resources"

PRIMARY_NESTED = {"Governorate", "Province", "State", "Emirate"}

SOURCES = {
    "iso3166_1.json":
        "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.json",
    "countries_en.json":
        "https://raw.githubusercontent.com/umpirsky/country-list/master/data/en/country.json",
    "countries_ar.json":
        "https://raw.githubusercontent.com/umpirsky/country-list/master/data/ar/country.json",
    "iso3166_2_full.json":
        "https://iso3166-2-api.vercel.app/api/all",
}

COUNTRY_OVERRIDES = {
    "PS": {"label_en": "Palestine", "label_ar": "فلسطين"},
    "SY": {"label_en": "Syria", "label_ar": "سوريا"},
    "US": {"label_en": "United States", "label_ar": "الولايات المتحدة"},
    "GB": {"label_en": "United Kingdom", "label_ar": "المملكة المتحدة"},
    "AE": {"label_en": "United Arab Emirates", "label_ar": "الإمارات العربية المتحدة"},
    "CZ": {"label_en": "Czechia", "label_ar": "التشيك"},
    "CD": {"label_en": "Congo (DRC)", "label_ar": "الكونغو الديمقراطية"},
    "CG": {"label_en": "Congo (Republic)", "label_ar": "الكونغو"},
    "KR": {"label_en": "South Korea", "label_ar": "كوريا الجنوبية"},
    "KP": {"label_en": "North Korea", "label_ar": "كوريا الشمالية"},
    "RU": {"label_en": "Russia", "label_ar": "روسيا"},
    "IR": {"label_en": "Iran", "label_ar": "إيران"},
    "LA": {"label_en": "Laos", "label_ar": "لاوس"},
    "MD": {"label_en": "Moldova", "label_ar": "مولدوفا"},
    "TZ": {"label_en": "Tanzania", "label_ar": "تنزانيا"},
    "BO": {"label_en": "Bolivia", "label_ar": "بوليفيا"},
    "VE": {"label_en": "Venezuela", "label_ar": "فنزويلا"},
    "BN": {"label_en": "Brunei", "label_ar": "بروناي"},
    "VA": {"label_en": "Vatican City", "label_ar": "الفاتيكان"},
}


def _ensure_sources() -> None:
    RES.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        path = RES / name
        if path.exists() and path.stat().st_size > 100:
            continue
        print(f"downloading {name} …")
        with urllib.request.urlopen(url, timeout=180) as resp:
            path.write_bytes(resp.read())


def _lang_names(local: str | None, tag: str) -> list[str]:
    if not local:
        return []
    out = []
    for m in re.finditer(rf"([^,;]+?)\s*\({re.escape(tag)}\)", local):
        name = m.group(1).strip()
        if name:
            out.append(name)
    return out


def _ascii_fold(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _pick_en(iso_name: str, local: str | None) -> tuple[str, list[str]]:
    eng = _lang_names(local, "eng")
    aliases: list[str] = []
    for n in eng:
        if n and n != iso_name and n not in aliases:
            aliases.append(n)
    label = eng[0] if eng else iso_name
    if iso_name and iso_name not in aliases and iso_name != label:
        aliases.append(iso_name)
    folded = _ascii_fold(label)
    if folded != label and folded not in aliases:
        aliases.append(folded)
    return label, aliases


def _pick_ar(local: str | None, fallback_en: str) -> str:
    ara = _lang_names(local, "ara")
    if ara:
        return ara[0]
    for tag in ("aeb", "apc", "arq", "ary", "arz"):
        hit = _lang_names(local, tag)
        if hit:
            return hit[0]
    return fallback_en


def build() -> None:
    _ensure_sources()
    iso1 = json.loads((RES / "iso3166_1.json").read_text(encoding="utf-8"))
    ar_map = json.loads((RES / "countries_ar.json").read_text(encoding="utf-8"))
    en_map = json.loads((RES / "countries_en.json").read_text(encoding="utf-8"))
    subs = json.loads((RES / "iso3166_2_full.json").read_text(encoding="utf-8"))

    countries = []
    for row in sorted(iso1, key=lambda r: (r.get("name") or "").lower()):
        code = row["alpha-2"]
        if not code or code == "ZZ":
            continue
        ov = COUNTRY_OVERRIDES.get(code, {})
        label_en = ov.get("label_en") or en_map.get(code) or row["name"]
        label_ar = ov.get("label_ar") or ar_map.get(code) or label_en
        countries.append({
            "code": code,
            "label_en": label_en,
            "label_ar": label_ar,
            "iso3": row.get("alpha-3") or "",
            "region": row.get("region") or "",
        })

    govs = []
    for cc in sorted(subs.keys()):
        block = subs[cc]
        if not isinstance(block, dict):
            continue
        order = 0
        items = []
        for code, info in block.items():
            if not isinstance(info, dict):
                continue
            parent = info.get("parentCode")
            typ = info.get("type") or ""
            if parent is not None and typ not in PRIMARY_NESTED:
                continue
            name = info.get("name") or code
            local = info.get("localOtherName")
            label_en, aliases = _pick_en(name, local)
            label_ar = _pick_ar(local, label_en)
            items.append((code, label_en, label_ar, typ, aliases))
        items.sort(key=lambda x: x[1].lower())
        for code, label_en, label_ar, typ, aliases in items:
            order += 10
            govs.append({
                "code": code,
                "country": cc,
                "label_en": label_en,
                "label_ar": label_ar,
                "sort": order,
                "type": typ,
                "aliases": aliases[:8],
            })

    (RES / "countries.json").write_text(
        json.dumps(countries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (RES / "governorates.json").write_text(
        json.dumps(govs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {RES / 'countries.json'} ({len(countries)})")
    print(f"wrote {RES / 'governorates.json'} ({len(govs)})")


if __name__ == "__main__":
    build()

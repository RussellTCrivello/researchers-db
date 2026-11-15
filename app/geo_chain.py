"""The geographical knowledge structure: one strict administrative chain.

A consistent, global hierarchy — every administrative unit in the system is a row
in this chain, at one of six levels:

    country → governorate (province) → district (region / sub-region)
            → municipality → village (neighborhood) → community (cluster)

The chain is the single source of truth for:

  * seed.py        — which lookup domains exist and how they nest;
  * server API     — parent validation on create/update and server-side
                     parent filtering (selecting a unit exposes ONLY its
                     direct children);
  * core.js        — A.ADMIN_CHAIN mirrors ADMIN_CHAIN below (a test enforces
                     the parity), powering every hierarchical selector;
  * place          — physical locations reference units at any depth
                     (place.country_id … place.community_id), keeping
                     administrative units, physical locations, boundaries
                     (unit meta: centroid/bbox) and real-world entities
                     (persons, institutions, events, military units — each
                     with their own coordinates) distinct yet interconnected.

Historical dimensions: units may carry meta {historical: true, valid_from,
valid_to, predecessor, successor} so renamed, merged or dissolved units keep
their place in the structure instead of being deleted.

Level labels (the words shown in the UI) live in ADMIN_LEVELS.
"""
from __future__ import annotations

# Strict top-down order. Index == level (0 = country … 5 = community).
ADMIN_CHAIN: list[str] = [
    "country",
    "governorate",
    "district",
    "municipality",
    "village",
    "community",
]

# child domain → parent domain (every non-country unit has exactly one parent)
ADMIN_PARENT: dict[str, str] = {
    child: ADMIN_CHAIN[i - 1]
    for i, child in enumerate(ADMIN_CHAIN)
    if i > 0
}

# domain → (level, label_en, label_ar, sort_order for lookup_domain)
ADMIN_LEVELS: dict[str, tuple[int, str, str, int]] = {
    "country":      (0, "Country", "البلد", 50),
    "governorate":  (1, "Governorates / provinces", "المحافظات / الأقاليم", 52),
    "district":     (2, "Districts / regions", "الأقضية / المناطق", 54),
    "municipality": (3, "Municipalities", "البلديات", 56),
    "village":      (4, "Neighborhoods & villages", "الأحياء والقرى", 58),
    "community":    (5, "Communities / clusters", "التجمعات السكانية", 61),
}


def is_admin_domain(domain: str) -> bool:
    return domain in ADMIN_LEVELS


def expected_parent(domain: str) -> str | None:
    """Parent domain for `domain`, or None for the top of the chain."""
    return ADMIN_PARENT.get(domain)


def level_of(domain: str) -> int:
    return ADMIN_LEVELS[domain][0]

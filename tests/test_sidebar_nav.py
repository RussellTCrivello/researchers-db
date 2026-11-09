"""Sidebar accordion — the military twelve organised in layered folds.

The sidebar is a multi-layered accordion: five collapsible sections (Workspace,
Military Organization, Entities, Data operations, Administration) keep the
navigation quiet, and the military twelve sit inside themed sub-groups
(Organization, Operations, Logistics, Leadership, Records).  The Leader is a
person, so "Commanders" is the military-category person register.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
LOC = ROOT / "app/static/js/locales"

NAV_KEYS = [
    "nav.milorg", "nav.mil.org", "nav.mil.ops", "nav.mil.logi", "nav.mil.lead",
    "nav.mil.rec", "nav.mil.units", "nav.mil.regions", "nav.mil.branches",
    "nav.mil.categories", "nav.mil.deployments", "nav.mil.tasks",
    "nav.mil.training", "nav.mil.armaments", "nav.mil.holdings",
    "nav.mil.commanders", "nav.mil.traits", "nav.mil.assignments",
    "nav.mil.notes",
]


def test_shell_carries_the_accordion_sections():
    for sec in ("workspace", "mil", "registry", "data", "admin"):
        assert f'data-sec="{sec}"' in HTML, sec
    assert HTML.count('class="nav-sec-head"') == 5
    assert HTML.count('class="nav-sec-caret"') == 5
    # the military folds and the registry entities mount here
    assert 'id="milNav"' in HTML and 'id="entityNav"' in HTML
    # the pinned shell entries survive the restructure
    assert 'data-route="military"' in HTML
    assert 'data-i18n="nav.workspace"' in HTML


def test_military_twelve_organised_into_themed_subgroups():
    for key in ("org", "ops", "logi", "lead", "rec"):
        assert f'data-sub="{key}"' in APP_JS or f'key: "{key}"' in APP_JS, key
    # every listed item is wired to its entity
    for ent in ("region", "division", "classification", "armament", "holding",
                "deployment", "mission", "training", "trait", "assignment",
                "note", "unit"):
        assert f'ent: "{ent}"' in APP_JS, ent
    # Commanders is the person register filtered to the military category
    assert 'ent: "person"' in APP_JS and 'q: "category:military"' in APP_JS
    assert 'href="#/entity/${it.ent}' in APP_JS


def test_accordion_labels_translated_in_both_languages():
    en = json.loads((LOC / "en.json").read_text(encoding="utf-8"))
    ar = json.loads((LOC / "ar.json").read_text(encoding="utf-8"))
    for k in NAV_KEYS:
        assert en.get(k) and ar.get(k), k
        assert en[k] != ar[k], f"{k} must be translated, not echoed"
    # the group vocabulary mirrors the user's names
    assert en["nav.mil.branches"] == "Branches"
    assert en["nav.mil.tasks"] == "Tasks"
    assert en["nav.mil.deployments"] == "Deployment Operations"
    assert en["nav.mil.traits"] == "Leadership Traits"
    assert ar["nav.mil.branches"] == "الفروع"
    assert ar["nav.mil.commanders"] == "القادة"


def test_accordion_state_and_a11y_wired():
    # open folds persist per browser and are restored at build time
    assert "siraj.navAcc" in APP_JS
    assert "navAccApply" in APP_JS and "revealActiveNav" in APP_JS
    # heads are real buttons with an accessibility state
    assert 'aria-expanded' in HTML
    assert "setAttribute(\"aria-expanded\"" in APP_JS
    # the delegated toggle listens on the nav
    assert 'addEventListener("click"' in APP_JS
    # every t()/data-i18n key the accordion uses resolves in the bundles
    used = ["nav.milorg"] + [f"nav.mil.{x}" for x in
            ("org", "ops", "logi", "lead", "rec", "units", "regions",
             "branches", "categories", "deployments", "tasks", "training",
             "armaments", "holdings", "commanders", "traits", "assignments",
             "notes")]
    en = json.loads((LOC / "en.json").read_text(encoding="utf-8"))
    assert all(k in en for k in used)


# --------------------------------------------------------------- live contract
def test_commanders_register_filters_to_military_persons(tmp_path, monkeypatch):
    """The Commanders link is the person register under `category:military` —
    the query string must actually filter (code-store vocabulary included)."""
    from fastapi.testclient import TestClient

    from app import db
    from app.military import seed as mil_seed
    from app.military import service

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "registry.db")
    db.init_db(seed_demo=False)
    with service.transaction() as conn:
        mil_seed.load_sample(conn)
    c = TestClient(__import__("app.server.api", fromlist=["app"]).app)
    got = c.post("/api/person/query",
                 json={"query": "category:military", "page_size": 50}).json()
    codes = {i.get("code") for i in got["items"]}
    assert got["total"] == 4, got
    assert {"SAMP-P-01", "SAMP-P-02", "SAMP-P-03", "SAMP-P-04"} <= codes
    civilian = c.post("/api/person/query",
                      json={"query": "category:civilian", "page_size": 50}).json()
    assert civilian["total"] == 1
    assert civilian["items"][0]["code"] == "SAMP-P-05"

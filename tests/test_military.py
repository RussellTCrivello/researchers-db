"""Military Organization — test suite (self-contained module).

Isolated from the SIRAJ registry: every test runs against a temporary
throwaway ``registry.db`` (see tests/conftest.py and the ``tmp_db`` fixture).
Covers the rule catalogue (§8), the naming engine (§11.2), the audit trail
(§12.3), role enforcement (§8.9), the sample and bulk datasets, and the
unified-database migration (015_military_org.sql).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.military import dbm, naming, rules, seed, service
from app.military.rules import RuleViolation
from app.military.service import ServiceError


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the unified registry database at a throwaway file (per test)."""
    from app import db
    db_path = tmp_path / "registry.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(dbm, "_initialised", False)
    # the unified deployment carries the registry schema (lookup vocabularies
    # included) under the military tables — model that, not a bare fragment
    conn = db.connect()
    try:
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def conn(tmp_db):
    with service.transaction() as c:
        yield c


@pytest.fixture()
def client(tmp_db):
    from app.server.api import app as full_app
    with TestClient(full_app) as tc:
        yield tc


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _region(conn, name="Test Region", **kw):
    return service.create(conn, "region", {"name": name, **kw}, "tester")


def _unit(conn, name="Test Unit", **kw):
    payload = {"name": name, "direct_personnel": 10}
    payload.update(kw)
    return service.create(conn, "unit", payload, "tester")


def _deployment(conn, **kw):
    payload = {"name": "Test Deployment", "start_date": "2026-01-01"}
    payload.update(kw)
    return service.create(conn, "deployment", payload, "tester")


# ---------------------------------------------------------------------------
# schema + naming engine
# ---------------------------------------------------------------------------
def test_schema_initialises_and_seeds_20_series(conn):
    naming.seed_options(conn)
    count = conn.execute("SELECT COUNT(*) AS n FROM naming_series_option").fetchone()["n"]
    assert count == 20


def test_docname_is_generated_and_unique(conn):
    a = _region(conn, "Alpha")
    b = _region(conn, "Bravo")
    assert a["docname"] == "MIL-REG-00001"
    assert b["docname"] == "MIL-REG-00002"


def test_year_token_partitions_by_year(conn):
    p1 = naming.preview(conn, "deployment", {"year": "2026"})
    assert p1["next"] == "MIL-DEP-2026-00001"
    p2 = naming.preview(conn, "deployment", {"year": "2027"})
    assert p2["next"] == "MIL-DEP-2027-00001"


def test_category_segment_and_width(conn):
    p = naming.preview(conn, "armament", {"category": "Weapons"},
                       "MIL-ARM-.{category}.#####")
    assert p["next"] == "MIL-ARM-WEAPONS00001"  # token dots + slot dot dropped
    q = naming.preview(conn, "training", {"year": "2026"}, "MIL-TRN-.######")
    assert q["next"] == "MIL-TRN-000001"  # explicit width 6, slot dot dropped


def test_preview_does_not_reserve(conn):
    a = naming.preview(conn, "unit", {"year": "2026"})
    b = naming.preview(conn, "unit", {"year": "2026"})
    assert a["next"] == b["next"] == "MIL-UNIT-00001"
    assert a["reserved"] is False


def test_counter_adjust_is_logged(conn):
    naming.seed_options(conn)
    opt = conn.execute(
        "SELECT id FROM naming_series_option WHERE label = 'MIL-REG-'").fetchone()
    naming.adjust_counter(conn, opt["id"], "", 500, "admin")
    p = naming.preview(conn, "region", {"year": "2026"})
    assert p["next_value"] == 501
    log = conn.execute("SELECT * FROM naming_adjustment_log").fetchone()
    assert log["new_value"] == 500 and log["actor"] == "admin"


def test_counter_adjust_is_admin_only_http(client):
    res = client.get("/api/military/naming/status")
    opt_id = res.json()["series"][0]["id"]
    res = client.put("/api/military/naming/counter",
                     json={"option_id": opt_id, "partition": "", "new_value": 10},
                     headers={"X-Military-Role": "staff"})
    assert res.status_code == 403
    res = client.put("/api/military/naming/counter",
                     json={"option_id": opt_id, "partition": "", "new_value": 10},
                     headers={"X-Military-Role": "admin"})
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# tree integrity
# ---------------------------------------------------------------------------
def test_tree_self_parent_rejected(conn):
    r = _region(conn)
    with pytest.raises(RuleViolation) as exc:
        service.update(conn, "region", r["id"], {"parent_id": r["id"]}, "tester")
    assert exc.value.code == "tree_self_parent"


def test_tree_cycle_rejected(conn):
    a = _region(conn, "A")
    b = _region(conn, "B", parent_id=a["id"])
    with pytest.raises(RuleViolation) as exc:
        service.update(conn, "region", a["id"], {"parent_id": b["id"]}, "tester")
    assert exc.value.code == "tree_cycle"


def test_tree_paths_and_depths(conn):
    a = _region(conn, "A")
    b = _region(conn, "B", parent_id=a["id"])
    c = _region(conn, "C", parent_id=b["id"])
    assert a["path"] == f"/{a['id']}/" and a["depth"] == 0
    assert b["path"] == f"/{a['id']}/{b['id']}/" and b["depth"] == 1
    assert c["depth"] == 2


def test_reparent_rebuilds_subtree_paths(conn):
    a = _region(conn, "A")
    b = _region(conn, "B", parent_id=a["id"])
    c = _region(conn, "C", parent_id=b["id"])
    top = _region(conn, "TOP")
    service.update(conn, "region", b["id"], {"parent_id": top["id"]}, "tester")
    b2 = service.get_record(conn, "region", b["id"])
    c2 = service.get_record(conn, "region", c["id"])
    assert b2["path"] == f"/{top['id']}/{b['id']}/"
    assert c2["path"] == f"/{top['id']}/{b['id']}/{c['id']}/"
    assert c2["depth"] == 2


# ---------------------------------------------------------------------------
# date rules
# ---------------------------------------------------------------------------
def test_end_before_start_rejected(conn):
    unit = _unit(conn)
    with pytest.raises(RuleViolation) as exc:
        _deployment(conn, unit_id=unit["id"], start_date="2026-05-05",
                    end_date="2026-05-01")
    assert exc.value.code == "date_order"


def test_invalid_date_format_rejected(conn):
    unit = _unit(conn)
    with pytest.raises(ServiceError) as exc:
        _deployment(conn, unit_id=unit["id"], start_date="05/05/2026")
    assert exc.value.code == "invalid_date"


# ---------------------------------------------------------------------------
# deployment rules + pointer sync
# ---------------------------------------------------------------------------
def test_completed_deployment_needs_end_date(conn):
    unit = _unit(conn)
    with pytest.raises(RuleViolation) as exc:
        _deployment(conn, unit_id=unit["id"], status="Completed")
    assert exc.value.code == "completed_needs_end"


def test_one_current_deployment_per_unit(conn):
    unit = _unit(conn)
    _deployment(conn, unit_id=unit["id"], is_current=True)
    with pytest.raises(RuleViolation) as exc:
        _deployment(conn, unit_id=unit["id"], name="Second", is_current=True)
    assert exc.value.code == "one_current_deployment"


def test_current_deployment_pointer_sync(conn):
    unit = _unit(conn)
    dep = _deployment(conn, unit_id=unit["id"], is_current=True)
    u = service.get_record(conn, "unit", unit["id"])
    assert u["current_deployment_id"] == dep["id"]
    # clearing the flag clears the pointer
    service.update(conn, "deployment", dep["id"], {"is_current": False}, "tester")
    u = service.get_record(conn, "unit", unit["id"])
    assert u["current_deployment_id"] is None
    # deleting the current deployment never leaves a dangling pointer
    dep2 = _deployment(conn, unit_id=unit["id"], is_current=True)
    service.delete(conn, "deployment", dep2["id"], "tester")
    u = service.get_record(conn, "unit", unit["id"])
    assert u["current_deployment_id"] is None


def test_deployment_status_transitions(conn):
    unit = _unit(conn)
    dep = _deployment(conn, unit_id=unit["id"], status="Planned")
    with pytest.raises(RuleViolation) as exc:
        service.update(conn, "deployment", dep["id"], {"status": "Completed",
                                                       "end_date": "2026-02-01"}, "tester")
    assert exc.value.code == "status_transition"
    service.update(conn, "deployment", dep["id"], {"status": "Active"}, "tester")
    service.update(conn, "deployment", dep["id"], {"status": "Completed",
                                                   "end_date": "2026-03-01"}, "tester")
    with pytest.raises(RuleViolation):
        service.update(conn, "deployment", dep["id"], {"status": "Active"}, "tester")


# ---------------------------------------------------------------------------
# mission rules
# ---------------------------------------------------------------------------
def _mission(conn, **kw):
    payload = {"name": "Test Mission", "start_date": "2026-01-01"}
    payload.update(kw)
    return service.create(conn, "mission", payload, "tester")


def test_mission_rejects_unrelated_deployment(conn):
    parent = _unit(conn, "Parent")
    child = _unit(conn, "Child", parent_id=parent["id"])
    other = _unit(conn, "Other")
    dep = _deployment(conn, unit_id=child["id"])  # deployment of a child unit
    with pytest.raises(RuleViolation) as exc:
        _mission(conn, unit_id=parent["id"], deployment_id=dep["id"],
                 start_date="2026-02-01")
    assert exc.value.code == "mission_deployment_mismatch"
    with pytest.raises(RuleViolation):
        _mission(conn, unit_id=other["id"], deployment_id=dep["id"],
                 start_date="2026-02-01")


def test_mission_allows_ancestor_deployment(conn):
    parent = _unit(conn, "Parent")
    child = _unit(conn, "Child", parent_id=parent["id"])
    dep = _deployment(conn, unit_id=parent["id"])
    # a subordinate mission under the parent formation's deployment is consistent
    m = _mission(conn, unit_id=child["id"], deployment_id=dep["id"],
                 start_date="2026-02-01")
    assert m["deployment_id"] == dep["id"]
    # same-unit mission is consistent too
    m2 = _mission(conn, unit_id=parent["id"], deployment_id=dep["id"],
                  name="Same", start_date="2026-03-01")
    assert m2["id"]


def test_executed_mission_needs_end_date(conn):
    unit = _unit(conn)
    with pytest.raises(RuleViolation) as exc:
        _mission(conn, unit_id=unit["id"], status="Executed")
    assert exc.value.code == "executed_needs_end"


def test_mission_status_transitions(conn):
    unit = _unit(conn)
    m = _mission(conn, unit_id=unit["id"])
    with pytest.raises(RuleViolation):
        service.update(conn, "mission", m["id"], {"status": "Executed",
                                                  "end_date": "2026-02-01"}, "tester")
    service.update(conn, "mission", m["id"], {"status": "Ongoing"}, "tester")
    service.update(conn, "mission", m["id"], {"status": "Executed",
                                              "end_date": "2026-02-01"}, "tester")


# ---------------------------------------------------------------------------
# command appointments
# ---------------------------------------------------------------------------
def _commander(conn, name="Test Commander", **kw):
    payload = {"full_name": name}
    payload.update(kw)
    return service.create(conn, "commander", payload, "tester")


def _assignment(conn, **kw):
    payload = {"assigned_date": "2026-01-01"}
    payload.update(kw)
    return service.create(conn, "assignment", payload, "tester")


def test_appointment_overlap_rejected(conn):
    unit = _unit(conn)
    c1 = _commander(conn, "One")
    c2 = _commander(conn, "Two")
    _assignment(conn, unit_id=unit["id"], commander_id=c1["id"],
                assigned_date="2020-01-01", relieved_date="2025-12-31",
                is_current=False)
    with pytest.raises(RuleViolation) as exc:
        _assignment(conn, unit_id=unit["id"], commander_id=c2["id"],
                    assigned_date="2025-06-01", is_current=False)
    assert exc.value.code == "appointment_overlap"
    # sequential appointment is fine
    a2 = _assignment(conn, unit_id=unit["id"], commander_id=c2["id"],
                     assigned_date="2026-01-01", is_current=True)
    assert a2["id"]


def test_one_current_appointment_per_unit_role(conn):
    unit = _unit(conn)
    c1 = _commander(conn, "One")
    c2 = _commander(conn, "Two")
    _assignment(conn, unit_id=unit["id"], commander_id=c1["id"],
                assigned_date="2020-01-01", is_current=True)
    with pytest.raises(RuleViolation) as exc:
        _assignment(conn, unit_id=unit["id"], commander_id=c2["id"],
                    assigned_date="2026-01-01", is_current=True)
    assert exc.value.code in ("one_current_appointment", "appointment_overlap")


def test_commander_pointer_sync(conn):
    unit = _unit(conn)
    c1 = _commander(conn, "One")
    c2 = _commander(conn, "Two")
    a1 = _assignment(conn, unit_id=unit["id"], commander_id=c1["id"],
                     assigned_date="2020-01-01", is_current=True)
    u = service.get_record(conn, "unit", unit["id"])
    assert u["commander_id"] == c1["id"]
    service.update(conn, "assignment", a1["id"],
                   {"is_current": False, "relieved_date": "2025-12-31"}, "tester")
    u = service.get_record(conn, "unit", unit["id"])
    assert u["commander_id"] is None
    _assignment(conn, unit_id=unit["id"], commander_id=c2["id"],
                assigned_date="2026-01-01", is_current=True)
    u = service.get_record(conn, "unit", unit["id"])
    assert u["commander_id"] == c2["id"]


def test_cannot_retire_commander_with_current_appointment(conn):
    unit = _unit(conn)
    c1 = _commander(conn, "One")
    _assignment(conn, unit_id=unit["id"], commander_id=c1["id"],
                assigned_date="2020-01-01", is_current=True)
    service.update(conn, "commander", c1["id"], {"status": "Reserve"}, "tester")
    with pytest.raises(RuleViolation) as exc:
        service.update(conn, "commander", c1["id"], {"status": "Retired"}, "tester")
    assert exc.value.code == "unresolved_appointment"


def test_commander_status_transitions(conn):
    c = _commander(conn)
    # the record's lifecycle is Active → Reserve → Retired; Retired is terminal
    with pytest.raises(RuleViolation) as exc:
        service.update(conn, "commander", c["id"], {"status": "Retired"}, "tester")
    assert exc.value.code == "status_transition"
    service.update(conn, "commander", c["id"], {"status": "Reserve"}, "tester")
    service.update(conn, "commander", c["id"], {"status": "Active"}, "tester")
    service.update(conn, "commander", c["id"], {"status": "Reserve"}, "tester")
    service.update(conn, "commander", c["id"], {"status": "Retired"}, "tester")
    with pytest.raises(RuleViolation) as exc:
        service.update(conn, "commander", c["id"], {"status": "Active"}, "tester")
    assert exc.value.code == "status_transition"


# ---------------------------------------------------------------------------
# training capacity + quantity rules
# ---------------------------------------------------------------------------
def test_training_participants_capped_by_subtree_personnel(conn):
    parent = _unit(conn, "Parent", direct_personnel=10)
    _unit(conn, "Child", parent_id=parent["id"], direct_personnel=5)
    with pytest.raises(RuleViolation) as exc:
        service.create(conn, "training", {
            "exercise_name": "Over", "unit_id": parent["id"],
            "start_date": "2026-01-01", "end_date": "2026-01-02",
            "duration_days": 2, "participant_count": 16}, "tester")
    assert exc.value.code == "participant_over_capacity"
    tr = service.create(conn, "training", {
        "exercise_name": "OK", "unit_id": parent["id"],
        "start_date": "2026-01-01", "end_date": "2026-01-02",
        "duration_days": 2, "participant_count": 15}, "tester")
    assert tr["id"]


def test_training_duration_must_match_dates(conn):
    unit = _unit(conn)
    with pytest.raises(RuleViolation) as exc:
        service.create(conn, "training", {
            "exercise_name": "Bad", "unit_id": unit["id"],
            "start_date": "2026-01-01", "end_date": "2026-01-03",
            "duration_days": 2, "participant_count": 1}, "tester")
    assert exc.value.code == "duration_mismatch"


def test_holding_quantity_positive_and_unique(conn):
    unit = _unit(conn)
    arm = service.create(conn, "armament", {"name": "Test Rifle"}, "tester")
    with pytest.raises(ServiceError) as exc:  # schema-level min=1
        service.create(conn, "holding", {"unit_id": unit["id"],
                                         "armament_id": arm["id"],
                                         "quantity": 0}, "tester")
    assert exc.value.code == "out_of_range"
    with pytest.raises(RuleViolation) as exc:  # rule-catalogue guard (direct)
        rules.check_holding({"quantity": 0})
    assert exc.value.code == "quantity_positive"
    service.create(conn, "holding", {"unit_id": unit["id"],
                                     "armament_id": arm["id"],
                                     "quantity": 5}, "tester")
    with pytest.raises(RuleViolation) as exc:
        service.create(conn, "holding", {"unit_id": unit["id"],
                                         "armament_id": arm["id"],
                                         "quantity": 3}, "tester")
    assert exc.value.code == "duplicate_holding"


def test_holding_condition_allowlist(conn):
    unit = _unit(conn)
    arm = service.create(conn, "armament", {"name": "Test Rifle"}, "tester")
    with pytest.raises(ServiceError) as exc:
        service.create(conn, "holding", {"unit_id": unit["id"],
                                         "armament_id": arm["id"],
                                         "quantity": 1,
                                         "condition": "Battered"}, "tester")
    assert exc.value.code == "invalid_choice"


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------
def test_note_target_validation(conn):
    unit = _unit(conn)
    n = service.create(conn, "note", {"entity_type": "unit", "target_id": unit["id"],
                                      "note_text": "hello", "author": "tester",
                                      "note_at": "2026-01-01"}, "tester")
    assert n["id"]
    with pytest.raises(RuleViolation) as exc:
        service.create(conn, "note", {"entity_type": "unit", "target_id": 9999,
                                      "note_text": "ghost", "author": "tester",
                                      "note_at": "2026-01-01"}, "tester")
    assert exc.value.code == "note_target_missing"
    with pytest.raises(ServiceError):  # vocabulary violation caught at schema level
        service.create(conn, "note", {"entity_type": "galaxy", "target_id": 1,
                                      "note_text": "x", "author": "tester",
                                      "note_at": "2026-01-01"}, "tester")


# ---------------------------------------------------------------------------
# deletion policy
# ---------------------------------------------------------------------------
def test_delete_blocked_by_dependents(conn):
    r = _region(conn)
    _unit(conn, "Dependent", region_id=r["id"])
    with pytest.raises(RuleViolation) as exc:
        service.delete(conn, "region", r["id"], "tester")
    assert exc.value.code == "delete_blocked"


def test_delete_unit_with_children_blocked(conn):
    parent = _unit(conn, "Parent")
    _unit(conn, "Child", parent_id=parent["id"])
    with pytest.raises(RuleViolation):
        service.delete(conn, "unit", parent["id"], "tester")


def test_delete_leaf_ok(conn):
    r = _region(conn)
    service.delete(conn, "region", r["id"], "tester")
    assert service.get_record(conn, "region", r["id"]) is None


# ---------------------------------------------------------------------------
# audit trail + immutability
# ---------------------------------------------------------------------------
def test_audit_records_create_update_delete(conn):
    r = _region(conn, "Audited")
    service.update(conn, "region", r["id"], {"name": "Renamed"}, "tester")
    service.delete(conn, "region", r["id"], "tester")
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    actions = [row["action"] for row in rows]
    assert actions == ["create", "update", "delete"]
    assert rows[1]["summary"] and "name" in rows[1]["summary"]


def test_docname_and_id_not_editable(conn):
    r = _region(conn)
    with pytest.raises(ServiceError) as exc:
        service.update(conn, "region", r["id"], {"docname": "HACK-1"}, "tester")
    assert exc.value.code == "field_not_editable"
    with pytest.raises(ServiceError):
        service.update(conn, "region", r["id"], {"id": 42}, "tester")


def test_unknown_field_rejected(conn):
    with pytest.raises(ServiceError) as exc:
        service.create(conn, "region", {"name": "X", "bogus": 1}, "tester")
    assert exc.value.code == "unknown_field"


# ---------------------------------------------------------------------------
# roles over HTTP
# ---------------------------------------------------------------------------
def test_viewer_is_read_only(client):
    res = client.post("/api/military/regions", json={"name": "V"},
                      headers={"X-Military-Role": "viewer"})
    assert res.status_code == 403
    res = client.get("/api/military/regions", headers={"X-Military-Role": "viewer"})
    assert res.status_code == 200


def test_staff_cannot_delete(client):
    res = client.post("/api/military/regions", json={"name": "S"},
                      headers={"X-Military-Role": "staff"})
    assert res.status_code == 201
    rid = res.json()["record"]["id"]
    res = client.delete(f"/api/military/regions/{rid}",
                        headers={"X-Military-Role": "staff"})
    assert res.status_code == 403
    res = client.delete(f"/api/military/regions/{rid}",
                        headers={"X-Military-Role": "admin"})
    assert res.status_code == 200


def test_crud_over_http_and_meta(client):
    meta = client.get("/api/military/meta").json()
    assert "unit" in meta["entities"] and "roles" in meta
    res = client.post("/api/military/units",
                      json={"name": "HTTP Unit", "direct_personnel": 3},
                      headers={"X-Military-Role": "staff"})
    assert res.status_code == 201
    record = res.json()["record"]
    assert record["docname"].startswith("MIL-UNIT-")
    res = client.get(f"/api/military/units/{record['id']}")
    assert res.json()["record"]["name"] == "HTTP Unit"
    res = client.patch(f"/api/military/units/{record['id']}",
                       json={"status": "Training"},
                       headers={"X-Military-Role": "staff"})
    assert res.json()["record"]["status"] == "Training"
    res = client.get("/api/military/units", params={"q": "HTTP"})
    assert res.json()["total"] == 1
    res = client.get("/api/military/units/tree")
    assert res.status_code == 200


def test_http_rule_violations_are_structured(client):
    res = client.post("/api/military/deployments",
                      json={"name": "D", "unit_id": 1, "start_date": "2026-05-05",
                            "end_date": "2026-05-01"},
                      headers={"X-Military-Role": "staff"})
    assert res.status_code in (404, 422)
    body = res.json()
    assert body["detail"]["ok"] is False
    assert "code" in body["detail"]["error"]


# ---------------------------------------------------------------------------
# sample dataset
# ---------------------------------------------------------------------------
def test_sample_loads_clean_and_is_labeled_fictional(conn):
    result = seed.load_sample(conn)
    assert result["loaded"] and result["fictional"] is True
    assert "FICTIONAL" in result["disclaimer"]
    problems = seed.check_sample_rules(conn)
    assert problems == []
    # idempotent: second load skips without force
    again = seed.load_sample(conn)
    assert again["skipped"] is True
    # every entity type got sample records
    for entity in ("region", "division", "classification", "commander", "unit",
                   "deployment", "mission", "armament", "holding", "training",
                   "assignment", "note"):
        spec = service.ENTITY_SPECS[entity]
        n = conn.execute(f"SELECT COUNT(*) AS n FROM {spec['table']}").fetchone()["n"]
        assert n > 0, entity


def test_sample_force_reset_and_clear(conn):
    seed.load_sample(conn)
    before = conn.execute("SELECT COUNT(*) AS n FROM military_unit").fetchone()["n"]
    seed.load_sample(conn, force=True)
    after = conn.execute("SELECT COUNT(*) AS n FROM military_unit").fetchone()["n"]
    assert before == after > 0
    # docnames continue after reset — no collisions
    names = [r["docname"] for r in conn.execute(
        "SELECT docname FROM military_unit ORDER BY id").fetchall()]
    assert len(names) == len(set(names))
    result = seed.clear_sample(conn)
    assert result["removed_records"] > 0
    assert conn.execute("SELECT COUNT(*) AS n FROM military_unit").fetchone()["n"] == 0
    # audit trail survives the clear (append-only)
    assert conn.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"] > 0


def test_sample_force_reset_across_separate_transactions(tmp_db):
    """Regression: force reset must work in a *fresh* transaction, like HTTP
    requests do (the single-connection flow masks defer/reset behaviour)."""
    with service.transaction() as conn:
        seed.load_sample(conn)
    with service.transaction() as conn:
        result = seed.load_sample(conn, force=True)
    assert result["loaded"] is True
    with service.transaction() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM military_unit").fetchone()["n"] > 0
        assert seed.check_sample_rules(conn) == []


def test_sample_cli_verify_passes_with_sample(tmp_db, capsys):
    with service.transaction() as conn:
        seed.load_sample(conn)
    from app.military import cli
    assert cli.verify() == 0
    out = capsys.readouterr().out
    assert "11/11 checks passed" in out
    assert "FAILED" not in out


def test_workspace_summary_end_to_end(conn):
    """Regression: dashboard queries with bind parameters must run (summary 500)."""
    seed.load_sample(conn)
    data = service.summary(conn)
    assert data["cards"]["active_units"] > 0
    assert data["cards"]["current_deployments"] >= 1
    assert data["cards"]["open_missions"] >= 1
    assert data["cards"]["active_commanders"] >= 1
    for key in ("unit_status", "unit_type", "region_distribution"):
        assert data["charts"][key], key
    for key in ("upcoming_deployments", "upcoming_trainings", "low_readiness_units",
                "recent_activity", "unit_readiness"):
        assert data["lists"][key], key


def test_force_summary_reflects_tree(conn):
    seed.load_sample(conn)
    brigade = conn.execute(
        "SELECT id FROM military_unit WHERE code = '12-TB'").fetchone()
    summary = service.force_summary(conn, brigade["id"])
    assert summary["subtree_personnel"] == 120 + 85 + 60 + 30 + 28 + 45
    assert summary["current_deployment"] is not None
    assert summary["current_deployment"]["is_current"] == 1
    assert len(summary["children"]) == 3


def test_armament_holdings_rollup(conn):
    seed.load_sample(conn)
    rifle = conn.execute(
        "SELECT id FROM armament WHERE name LIKE 'MK-4%'").fetchone()
    data = service.armament_holdings(conn, rifle["id"])
    assert data["total_quantity"] == 240 + 85
    assert len(data["holdings"]) == 2


# ---------------------------------------------------------------------------
# shell integration: one application, one locale mechanism
# ---------------------------------------------------------------------------
def test_meta_ships_bilingual_labels():
    from app.military import api as mil_api
    data = mil_api.meta()
    for key, spec in data["entities"].items():
        assert spec["label_en"] and spec["label_ar"], key
        for field in spec["fields"]:
            assert field["label_en"] and field["label_ar"], (key, field["name"])


def test_locale_bundles_mil_namespace_at_parity():
    """en.json and ar.json must carry the same mil.* keys (and nav.military)."""
    import json as _json
    from pathlib import Path
    loc = Path("app/static/js/locales")
    en = _json.loads((loc / "en.json").read_text(encoding="utf-8"))
    ar = _json.loads((loc / "ar.json").read_text(encoding="utf-8"))
    en_mil = {k for k in en if k.startswith("mil.") or k == "nav.military"}
    ar_mil = {k for k in ar if k.startswith("mil.") or k == "nav.military"}
    assert en_mil == ar_mil
    assert len(en_mil) >= 70
    # whole bundles stay at parity too (the house rule)
    assert set(en) == set(ar)


def test_military_workspace_wired_into_shell():
    """The shell must carry the workspace: nav entry, styles, view module."""
    from pathlib import Path
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    assert 'data-route="military"' in html
    assert "/static/js/views/military.js" in html
    assert "/static/css/military.css" in html
    js = Path("app/static/js/views/military.js").read_text(encoding="utf-8")
    for view in ("military", "milList", "milTree", "milForce",
                 "milHoldings", "milNaming", "milAudit", "milDossier"):
        assert f"A.views.{view}" in js, view
    # the duplicate military form is gone: add/edit ride the ONE shared record
    # form (record.js), exactly like places, people and organizations
    assert "A.views.milForm" not in js
    app_js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "/military" in app_js
    # the parallel standalone app is gone: one structure only
    assert not Path("app/military/ui").exists()


# ---------------------------------------------------------------------------
# Unified database + stress-arc regressions (defects surfaced 2026-11-07)
# ---------------------------------------------------------------------------
def _mk_unit(conn, name, *, parent_id=None, personnel=0):
    from app.military import service
    if parent_id is None:
        region = service.create(conn, "region", {"name": f"{name} Region"},
                                actor="t")
        div = service.create(conn, "division", {"name": f"{name} Division",
                                                "region_id": region["id"]},
                             actor="t")
    else:
        row = service.get_record(conn, "unit", parent_id)
        div = {"id": row["division_id"]}
    payload = {"name": name, "division_id": div["id"]}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if personnel:
        payload["direct_personnel"] = personnel
    return service.create(conn, "unit", payload, actor="t")


class TestUnifiedDatabase:
    def test_military_tables_live_inside_registry_db(self, tmp_db):
        """init_db applies 015 into the ONE registry.db database."""
        import sqlite3 as s

        from app import db
        db.init_db(seed_demo=False)
        c = s.connect(db.DB_PATH)
        tables = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        led = c.execute("SELECT ok FROM schema_migration WHERE filename=?",
                        ("015_military_org.sql",)).fetchone()
        c.close()
        assert {"military_unit", "operational_deployment", "mission",
                "unit_armament", "naming_counter"} <= tables
        assert led is not None and led[0] == 1

    def test_015_idempotent_via_ensure(self, tmp_db):
        from app.military import dbm
        dbm.ensure()
        dbm._initialised = False
        dbm.ensure()   # second pass must not raise
        conn = dbm.connect()
        n = conn.execute("SELECT count(*) FROM military_unit").fetchone()[0]
        conn.close()
        assert n == 0


class TestMigrationMachinery:
    def test_splitter_respects_comments_and_literals(self):
        from app.db import split_sql_statements
        script = (
            "-- tricky; comment with semicolon\n"
            "CREATE TABLE t (a TEXT DEFAULT 'x;y');\n"
            "-- another; one\n"
            "INSERT INTO t (a) VALUES ('p;q');\n")
        stmts = split_sql_statements(script)
        assert len(stmts) == 2
        assert "CREATE TABLE" in stmts[0]
        assert "INSERT INTO" in stmts[1]

    def test_run_migrations_tolerates_semicolon_in_comment(
            self, tmp_db, tmp_path, monkeypatch):
        from app import db
        db.init_db(seed_demo=False)
        d = tmp_path / "mig"
        d.mkdir()
        (d / "900_tricky.sql").write_text(
            "-- note: a; b; c\nCREATE TABLE tricky (x TEXT DEFAULT 'a;b');\n",
            encoding="utf-8")
        monkeypatch.setattr(db, "MIGRATIONS_DIR", d)
        conn = db.connect()
        done = db.run_migrations(conn)
        conn.close()
        assert "900_tricky.sql" in done

    def test_checksums_are_deterministic(self, tmp_db, tmp_path, monkeypatch):
        import hashlib

        from app import db
        db.init_db(seed_demo=False)
        d = tmp_path / "mig"
        d.mkdir()
        (d / "901_hash.sql").write_text("CREATE TABLE h (x INTEGER);",
                                        encoding="utf-8")
        monkeypatch.setattr(db, "MIGRATIONS_DIR", d)
        conn = db.connect()
        db.run_migrations(conn)
        row = conn.execute(
            "SELECT checksum FROM schema_migration WHERE filename=?",
            ("901_hash.sql",)).fetchone()
        conn.close()
        expect = hashlib.sha256(b"CREATE TABLE h (x INTEGER);").hexdigest()
        assert row["checksum"] == expect


class TestConcurrency:
    def test_only_one_current_deployment_wins(self, tmp_db):
        """Two writers racing to set the current deployment: exactly one wins.

        Regression for the check-then-act race fixed by BEGIN IMMEDIATE in
        service.transaction().
        """
        import threading

        from app.military import rules, service
        with service.transaction() as conn:
            unit = _mk_unit(conn, "Race Unit")
        errors: list[Exception] = []
        won: list[int] = []
        barrier = threading.Barrier(2)

        def attempt(idx: int) -> None:
            try:
                barrier.wait(timeout=5)
                with service.transaction() as conn:
                    rec = service.create(conn, "deployment", {
                        "name": f"Race Op {idx}", "unit_id": unit["id"],
                        "status": "Active", "is_current": True,
                        "start_date": "2026-01-01"}, actor="t")
                    won.append(rec["id"])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=attempt, args=(i,)) for i in (0, 1)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert len(won) == 1, f"winners={won} errors={errors}"
        assert len(errors) == 1
        assert isinstance(errors[0], (rules.RuleViolation, service.ServiceError))
        with service.transaction() as conn:
            cur = conn.execute(
                "SELECT count(*) FROM operational_deployment WHERE is_current=1 "
                "AND unit_id=?", (unit["id"],)).fetchone()[0]
        assert cur == 1


class TestRollupContract:
    def test_list_returns_null_rollup_but_get_and_tree_compute(self, tmp_db):
        from app.military import service
        with service.transaction() as conn:
            parent = _mk_unit(conn, "R Parent", personnel=10)
            _mk_unit(conn, "R Child", parent_id=parent["id"], personnel=7)
        with service.transaction() as conn:
            rows = service.list_records(conn, "unit")["records"]
        target = [r for r in rows if r["name"] == "R Parent"][0]
        assert target["subtree_personnel"] is None   # lists never compute rollup
        with service.transaction() as conn:
            rec = service.get_record(conn, "unit", target["id"])
        assert rec["subtree_personnel"] == 17        # get computes rollup
        with service.transaction() as conn:
            tree = service.tree(conn, "unit")
        node = _find_node(tree, target["id"])
        assert node is not None and node["subtree_personnel"] == 17


def _find_node(nodes, node_id):
    for n in nodes:
        if n["id"] == node_id:
            return n
        found = _find_node(n.get("children", []), node_id)
        if found:
            return found
    return None


class TestBulkLoader:
    def test_bulk_load_small_scale_is_rule_clean(self, tmp_db):
        from app.military import bulk, seed, service
        with service.transaction() as conn:
            result = bulk.load_bulk(conn, scale=300)
        assert result["loaded"] is True
        assert result["total"] >= 200
        with service.transaction() as conn:
            assert all("(fictional)" in v for v in
                       (r["name"] for r in service.list_records(conn, "unit")["records"]))
        with service.transaction() as conn:
            assert seed.check_sample_rules(conn) == []
        with service.transaction() as conn:
            cur = conn.execute(
                "SELECT unit_id, count(*) AS n FROM operational_deployment "
                "WHERE is_current=1 GROUP BY unit_id HAVING n > 1").fetchall()
        assert cur == []


class TestVolumeUI:
    """Volume-UI fixes (list pagination, tree collapse) — source-level guards.

    Browser execution is unavailable in this environment (Playwright browsers
    cannot be installed), so these assert the shipped wiring rather than
    rendered behaviour; the live smoke checks the same markers on the wire.
    """

    def test_mil_list_paginates_with_offset(self):
        from pathlib import Path
        lst = Path("app/static/js/views/list.js").read_text()
        assert "data-load-more" in lst          # show-more appends the next page
        assert "page_size" in lst              # server-side paging
        src = Path("app/static/js/views/military.js").read_text()
        assert "offset=" in src                # ref options page through fully

    def test_tree_collapses_below_top_level(self):
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        # only top level renders open by default; when the primary filters are
        # at work the kept nodes open to reveal matches in their context
        assert "hasKids && (openAll || depth < 1)" in src
        assert "nodeHtml(c, depth + 1, openAll)" in src   # depth tracked recursively

    def test_load_more_key_exists_in_both_locales(self):
        import json as _json
        from pathlib import Path
        loc = Path("app/static/js/locales")
        for lang in ("en", "ar"):
            keys = _json.loads((loc / f"{lang}.json").read_text(encoding="utf-8"))
            assert "mil.list.loadMore" in keys


# ---------------------------------------------------------------------------
# Integrated-capability regressions (2026-11-07 second directive)
# ---------------------------------------------------------------------------
class TestLinkedFieldCombobox:
    def test_ref_fields_render_searchable_combobox(self):
        """Linked fields ride the SHARED searchable combobox (A.combobox) with
        quick-create enabled — in the one shared record form, which now also
        serves the military entities.  The one-time combobox engine is gone, so
        the application can never grow a second, duplicate one."""
        from pathlib import Path
        src = Path("app/static/js/views/record.js").read_text()
        assert "A.combobox(" in src                    # shared engine, not a local copy
        assert 'allowCreate: f.type === "fk" || vocabCreate' in src   # linked fields addable
        assert 'hidden.dataset.k = f.key' in src       # form reads it like any field
        assert 'entity: f.type === "fk" ? fkEntity : undefined' in src
        assert "function refCombo(" not in src         # no duplicate combobox engine
        assert "bindRefCombos" not in src

    def test_ref_options_fetch_every_page(self):
        """Regression: refOptions was capped at 500 rows, silently dropping
        linked records from dropdowns at volume."""
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        assert "limit=500&offset=" in src

    def test_combobox_options_cover_all_rows_at_volume(self, tmp_db):
        from app.military import service
        with service.transaction() as conn:
            region = service.create(conn, "region", {"name": "Combo Region"},
                                    actor="t")
            for i in range(30):
                service.create(conn, "division", {
                    "name": f"Combo Div {i}", "region_id": region["id"]}, actor="t")
            data = service.list_records(conn, "division", limit=500, offset=0)
        assert data["total"] == 30 and len(data["records"]) == 30


class TestNumberingControl:
    def test_numbering_preview_lives_in_the_shared_form(self):
        """The numbering control (preview chip) of the old military form is now
        the shared form's live document-name preview: the read-only name field
        shows the next value and refreshes as the person types."""
        from pathlib import Path
        src = Path("app/static/js/views/record.js").read_text()
        assert 'data-field="docname"' in src            # the named field
        assert "/next-code" in src                      # live preview endpoint
        assert "f.key === \"code\" || f.key === \"docname\"" in src  # both name systems
        mil = Path("app/static/js/views/military.js").read_text()
        assert "milNameChip" not in mil                 # no second numbering UI

    def test_preview_is_advisory_and_shape_stable(self, tmp_db):
        from app.military import naming, service
        with service.transaction() as conn:
            res = naming.preview(conn, "unit", {"year": "2026"})
        assert res["reserved"] is False
        assert res["next"].startswith("MIL-UNIT-")
        assert res["next_value"] >= 1


class TestSharedFormForMilitary:
    """One form system for the whole application: military add/edit use the
    same advanced record form (record.js) as places, people and organizations —
    settings-integrated (form mode page/dialog, language, density) and
    stay-in-place: the form never navigates the person away from the screen it
    was opened from."""

    def test_meta_carries_vocabulary_options_for_military_selects(self, client):
        """Free-code vocabulary fields expose their allowed values in the
        unified meta, so the shared form renders real dropdowns — and the
        service validates the very same list."""
        from app.military import service as svc
        r = client.get("/api/meta")
        assert r.status_code == 200
        fields = r.json()["fields"]
        checked = 0
        for ent, rows in fields.items():
            if ent not in svc.ENTITY_SPECS:
                continue
            legacy = {f["name"]: f for f in svc.ENTITY_SPECS[ent]["fields"]}
            for d in rows:
                want = (legacy.get(d["key"]) or {}).get("options")
                if want:
                    assert d.get("options") == list(want), (ent, d["key"])
                    checked += 1
        assert checked >= 6, checked   # the vocabularies are actually wired

    def test_next_code_returns_the_document_name_preview(self, client):
        """The generic next-code endpoint speaks document names for military
        entities (the numbering control's preview), not bare numbers."""
        r = client.get("/api/unit/next-code")
        assert r.status_code == 200
        code = r.json()["code"]
        assert code.startswith("MIL-UNIT-"), code
        # context params narrow the naming partition; the call is advisory
        r2 = client.get("/api/unit/next-code", params={"year": "2031"})
        assert r2.status_code == 200

    def test_form_hygiene_and_group_order(self):
        from pathlib import Path
        src = Path("app/static/js/views/record.js").read_text()
        # read-only values (system-maintained docname) are never sent back
        assert "if (el.disabled) return;" in src
        # every spec group renders: known groups ordered, unknown ones appended
        assert '"structure"' in src and '"main"' in src
        assert "!GROUP_ORDER.includes(g)" in src
        # free-code vocabularies render as dropdowns from meta options
        assert "f.options" in src

    def test_stay_in_place_after_save(self):
        from pathlib import Path
        rec = Path("app/static/js/views/record.js").read_text()
        app = Path("app/static/js/app.js").read_text()
        # the screen a form was opened from is remembered …
        assert "formOrigin" in app
        # … and save/cancel return to it instead of navigating away
        assert "replaceRoute(backTo)" in rec
        assert "replaceRoute(behind)" in rec
        assert "ctx.backTo" in rec


class TestInPlaceForms:
    """Add and edit never navigate — for any reason whatsoever.  Clicking an
    add/edit button opens the shared record form as an overlay on the current
    screen (the address never moves), and saving closes the overlay and
    refreshes that screen where it stands, with the record appearing in it."""

    def test_forms_open_never_navigates(self):
        from pathlib import Path
        src = Path("app/static/js/views/record.js").read_text()
        i = src.index("open(entity, id, opts)")
        window = src[i:i + 700]
        assert "location.hash" not in window          # zero navigation …
        assert "inPlace: true" in window              # … it is an overlay
        # saving refreshes the screen in place — no route change at all
        assert "refreshInPlace(entity, record)" in src
        assert "siraj:record-saved" in src
        assert "A._keepScroll = true" in src

    def test_add_and_edit_buttons_are_intercepted(self):
        from pathlib import Path
        app = Path("app/static/js/app.js").read_text()
        assert "App.forms.open(m[1]" in app           # plain clicks open the overlay
        assert 'href^="#/"' in app
        # modified clicks keep their link semantics (new tab, copy address)
        assert "e.defaultPrevented || e.button !== 0" in app

    def test_add_event_stays_on_the_screen(self):
        from pathlib import Path
        src = Path("app/static/js/views/record.js").read_text()
        body = src[src.index("function addEvent"):src.index("A.addEvent = addEvent")]
        assert "location.hash" not in body
        assert 'A.forms.open("event"' in body

    def test_military_entry_points_open_the_overlay(self):
        from pathlib import Path
        mil = Path("app/static/js/views/military.js").read_text()
        assert '/edit">' in mil                       # edit links interceptable
        app = Path("app/static/js/app.js").read_text()
        assert 're: /^\\/military\\/([\\w-]+)\\/(\\d+)\\/edit$/, view: "recordEdit"' in app

    def test_geographic_view_saves_without_rebuilding(self):
        from pathlib import Path
        geo = Path("app/static/js/views/geomap.js").read_text()
        assert "siraj:record-saved" in geo            # soft refresh …
        assert "loadFeatures();" in geo               # … reload features, keep the camera


class TestTreeViewOption:
    """Units (military hierarchy) and Regions (command regions) browse as a
    tree right alongside their existing view — a mode in the same view
    switcher as table/cards/gallery/rows, not a trip to a screen elsewhere.
    Everything visible rides the locale system: every element translates."""

    def test_tree_is_a_view_mode_for_units_and_regions(self):
        from pathlib import Path
        src = Path("app/static/js/views/list.js").read_text()
        assert 'TREE_ENTITIES = new Set(["unit", "region"])' in src
        assert 'out.concat("tree")' in src             # offered in the switcher …
        assert 'st.view === "tree"' in src             # … and rendered in place
        assert "mountListTree" in src
        # the switcher label is keyed, never a bare word
        assert 't("view." + v) || v' in src

    def test_one_tree_engine_for_every_surface(self):
        from pathlib import Path
        mil = Path("app/static/js/views/military.js").read_text()
        lst = Path("app/static/js/views/list.js").read_text()
        assert mil.count("A.entityTree = function") == 1   # one renderer …
        assert "A.entityTree(root.querySelector" in mil    # … used by the tree screen
        assert "A.entityTree(host," in lst                 # … and by the list mode
        # the tree node engine exists nowhere else (list.js has its own,
        # unrelated graph nodes) — its markup markers stay put
        assert "mil-node" not in lst
        assert "data-tree-filter" not in lst
        assert mil.count("mil.tree.filter") == 1           # one filter, one label

    def test_every_tree_element_is_translated(self):
        import json
        from pathlib import Path
        en = json.loads(Path("app/static/js/locales/en.json").read_text(encoding="utf-8"))
        ar = json.loads(Path("app/static/js/locales/ar.json").read_text(encoding="utf-8"))
        assert set(en) == set(ar)                        # full parity, every key
        for key in ("view.tree", "mil.tree.filter", "mil.tree.subtreePersonnel",
                    "mil.tree.subtitle", "list.noRecords", "common.loading"):
            assert en.get(key) and ar.get(key), key      # both languages, non-empty
        mil = Path("app/static/js/views/military.js").read_text()
        # the renderer itself holds no untranslated visible strings
        for key in ("mil.tree.filter", "mil.tree.subtreePersonnel", "list.noRecords"):
            assert f't("{key}")' in mil, key

    def test_tree_endpoints_serve_both_hierarchies(self, client):
        for kind in ("units", "regions"):
            r = client.get(f"/api/military/{kind}/tree")
            assert r.status_code == 200, (kind, r.text)
            body = r.json()
            assert isinstance(body.get("tree"), list), kind


class TestLinkedVocabularies:
    """Fields that have a supplementary table behind them link to it — the
    country and language vocabularies (bilingual, admin-managed) drive proper
    linked controls instead of free-text boxes.  Vocabulary values display and
    export as their bilingual labels; the canonical code is what is stored."""

    def test_country_fields_link_to_the_vocabulary(self, client):
        meta = client.get("/api/meta").json()
        for ent, key in (("region", "country"), ("armament", "origin_country")):
            f = next(x for x in meta["fields"][ent] if x["key"] == key)
            assert f["type"] == "select", (ent, key)
            assert f["domain"] == "country", (ent, key)
        # rank and command role have fixed lists — dropdown material, not text
        for ent, key in (("commander", "rank_title"), ("assignment", "role")):
            f = next(x for x in meta["fields"][ent] if x["key"] == key)
            assert f["type"] == "select", (ent, key)
            assert f.get("options"), (ent, key)

    def test_language_fields_link_to_the_vocabulary(self, client):
        meta = client.get("/api/meta").json()
        for ent, key in (("source", "language"),
                         ("person", "name_original_lang"),
                         ("place", "name_original_lang"),
                         ("institution", "name_original_lang")):
            f = next(x for x in meta["fields"][ent] if x["key"] == key)
            assert f["type"] == "select" and f["domain"] == "language", (ent, key)
            assert f["store"] == "code", (ent, key)

    def test_service_stores_the_canonical_code(self, tmp_db):
        from app.military import seed, service
        with service.transaction() as conn:
            seed.ensure_country_vocab(conn)
            # the code is accepted directly …
            r1 = service.create(conn, "region",
                                {"name": "Code Region", "country": "XX"}, actor="t")
            # … and a (fictional) country name resolves to it
            r2 = service.create(conn, "region", {
                "name": "Label Region",
                "country": "Republic of Aldervale (fictional)"}, actor="t")
            assert r1["country"] == "XX" and r2["country"] == "XX"
            # unknown countries are refused — the table is the source of truth
            try:
                service.create(conn, "region",
                               {"name": "Nowhere", "country": "Narnia"}, actor="t")
                raise AssertionError("expected invalid_choice")
            except service.ServiceError as e:
                assert e.code == "invalid_choice"

    def test_vocab_entry_is_bilingual_and_idempotent(self, tmp_db):
        from app.military import seed, service
        with service.transaction() as conn:
            seed.ensure_country_vocab(conn)
            seed.ensure_country_vocab(conn)
            rows = conn.execute(
                "SELECT label_en, label_ar FROM lookup"
                " WHERE domain='country' AND code='XX'").fetchall()
            assert len(rows) == 1
            assert rows[0]["label_en"] and rows[0]["label_ar"]  # both languages
            # rows written before the field linked to the vocabulary kept free
            # text; the ensure step maps them onto the code
            service.create(conn, "armament",
                           {"name": "Legacy Arms", "category": "Weapons"},
                           actor="t")
            conn.execute(
                "UPDATE armament SET origin_country='Aldervale (fictional)'"
                " WHERE name='Legacy Arms'")
            seed.ensure_country_vocab(conn)
            got = conn.execute(
                "SELECT origin_country FROM armament WHERE name='Legacy Arms'").fetchone()
            assert got["origin_country"] == "XX"

    def test_registry_language_values_resolve_and_display(self, client):
        res = client.post("/api/person", json={
            "name_ar": "اختبار ربط اللغة", "name_original_lang": "English"})
        assert res.status_code in (200, 201), res.text
        body = res.json()
        rec = body.get("record") or body
        assert rec["name_original_lang"] == "en"   # label resolved to the code
        q = client.post("/api/person/query", json={"page_size": 50}).json()
        item = next(i for i in q["items"] if i["id"] == rec["id"])
        assert item["_labels"]["name_original_lang"]["en"] == "English"

    def test_list_and_export_show_labels_not_codes(self, tmp_db):
        from app import repo
        from app.military import seed, service
        from app.military.specs import MIL_SPECS
        with service.transaction() as conn:
            seed.ensure_country_vocab(conn)
            service.create(conn, "region",
                           {"name": "Labelled Region", "country": "XX"}, actor="t")
            # the very path lists and exports read through decorates codes
            out = repo.list_records(conn, MIL_SPECS["region"], {"page_size": 5})
            item = out["items"][0]
            lab = (item.get("_labels") or {}).get("country")
            assert lab and lab["en"] and lab["ar"]

    def test_form_never_renders_an_empty_dropdown(self):
        """A vocabulary select with no vocabulary behind it (military unit role)
        is an honest text box — never an empty dropdown."""
        from pathlib import Path
        src = Path("app/static/js/views/record.js").read_text()
        assert "never an empty dropdown" in src
        assert 'f = Object.assign({}, f, { type: "text" })' in src
        mil = Path("app/static/js/views/military.js").read_text()
        # the dossier resolves vocabulary codes to bilingual labels
        assert 'f.type === "select" && f.domain' in mil


class TestListViewTools:
    def test_sort_filter_export_wiring(self):
        from pathlib import Path
        lst = Path("app/static/js/views/list.js").read_text()
        assert "data-sort" in lst                  # column sorting
        assert "filterRowEl" in lst                # deep filter builder rows
        assert "/api/export/" in lst               # export modal endpoint
        src = Path("app/static/js/views/military.js").read_text()
        assert "URLSearchParams" in src            # deep-link query state

    def test_export_csv_service_roundtrip(self, tmp_db):
        from app.military import service
        with service.transaction() as conn:
            for i in range(3):
                service.create(conn, "classification",
                               {"name": f"Export Class {i}"}, actor="t")
            res = service.export_csv(conn, "classification")
            one = service.export_csv(conn, "classification",
                                     q="Export Class 1")
        lines = res["csv"].strip().splitlines()
        assert lines[0].startswith("id,docname,")
        assert res["rows"] == 3
        assert one["rows"] == 1

    def test_api_export_and_quality_routes(self, client):
        h = {"X-Military-Role": "staff"}
        r = client.post("/api/military/classifications",
                        json={"name": "Route Export Class"}, headers=h)
        assert r.status_code == 201
        csv_r = client.get("/api/military/classifications/export.csv", headers=h)
        body = csv_r.json()
        assert csv_r.status_code == 200 and body["ok"] is True
        assert "Route Export Class" in body["csv"]
        q = client.get("/api/military/quality", headers=h)
        assert q.status_code == 200 and "entities" in q.json()
        assert q.json()["buckets"][-1] == "100%"


class TestRecordDossier:
    def test_dossier_route_and_related_map(self):
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        app = Path("app/static/js/app.js").read_text()
        assert "milDossier" in app and "/show$" in app
        assert "A.views.milDossier" in src
        assert "RELATED" in src and '"deployments", "unit_id"' in src
        assert "milNoteAdd" in src                  # inline polymorphic notes

    def test_related_filters_resolve_via_api(self, client):
        h = {"X-Military-Role": "staff"}
        r = client.post("/api/military/units",
                        json={"name": "Dossier Unit"}, headers=h)
        uid = r.json()["record"]["id"]
        d = client.post("/api/military/deployments",
                        json={"name": "Dossier Op", "unit_id": uid,
                              "start_date": "2026-01-01"}, headers=h)
        assert d.status_code == 201
        rel = client.get(f"/api/military/deployments?unit_id={uid}", headers=h)
        assert rel.json()["total"] == 1


class TestCompletenessVariation:
    def test_bulk_dataset_spans_completeness_spectrum(self, tmp_db):
        """The dataset must contain complete, partial AND near-empty records
        (directive: never all-complete, never all-incomplete)."""
        from app.military import bulk, service
        with service.transaction() as conn:
            bulk.load_bulk(conn, scale=300)
            rep = service.quality_report(conn)
        hist = rep["entities"]["unit"]["histogram"]
        near_empty = hist["0-25%"] + hist["25-50%"]
        partial = hist["50-75%"] + hist["75-99%"]
        complete = hist["100%"]
        assert complete > 0 and partial > 0 and near_empty > 0, hist

    def test_quality_report_shape(self, tmp_db):
        from app import db
        from app.military import service
        db.init_db(seed_demo=False)
        rep = service.quality_report(db.connect())
        assert rep["buckets"] == ["0-25%", "25-50%", "50-75%", "75-99%", "100%"]

    def test_cli_c11_checks_variation(self, tmp_db):
        import contextlib
        import io

        from app.military import bulk, cli, service
        with service.transaction() as conn:
            bulk.load_bulk(conn, scale=300)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.verify()
        out = buf.getvalue()
        assert rc == 0
        assert "C.11" in out and "completeness mix present" in out
        assert "FAILED" not in out


class TestIncompleteRecordRobustness:
    def test_note_at_defaults_when_omitted(self, tmp_db):
        from app.military import service
        with service.transaction() as conn:
            unit = _mk_unit(conn, "Noteless Unit")
            rec = service.create(conn, "note", {
                "entity_type": "unit", "target_id": unit["id"],
                "note_text": "no date given", "author": "t"}, actor="t")
        assert rec["note_at"]        # schema NOT NULL: defaulted, not crashed

    def test_rollup_and_tree_survive_null_personnel(self, tmp_db):
        from app.military import service
        with service.transaction() as conn:
            parent = _mk_unit(conn, "Null Parent", personnel=10)
            child = _mk_unit(conn, "Null Child", parent_id=parent["id"])
            # child created WITHOUT direct_personnel (NULL)
        with service.transaction() as conn:
            tree = service.tree(conn, "unit")
        node = _find_node(tree, parent["id"])
        assert node["subtree_personnel"] == 10
        with service.transaction() as conn:
            rec = service.get_record(conn, "unit", child["id"])
        assert rec["subtree_personnel"] in (0, None) or rec["subtree_personnel"] == 0


class TestFreshDatasetRebuild:
    """Fresh-dataset rebuild: registry demo variation + military reload."""

    def _seed_registry_demo(self):
        from app import db
        from app import seed as reg_seed
        db.init_db(seed_demo=False)
        conn = db.connect()
        try:
            reg_seed.seed_demo(conn)
        finally:
            conn.close()

    def test_vary_demo_produces_complete_partial_minimal(self, tmp_db):
        from app import db
        from app import seed as reg_seed
        self._seed_registry_demo()
        conn = db.connect()
        stats = reg_seed.vary_demo(conn)
        conn.close()
        for table in ("person", "place"):
            s = stats[table]
            assert s["full"] > 0 and s["partial"] > 0 and s["minimal"] > 0, s
            assert s["groups_cleared"] > 0

    def test_vary_demo_is_idempotent(self, tmp_db):
        from app import db
        from app import seed as reg_seed
        self._seed_registry_demo()
        conn = db.connect()
        first = reg_seed.vary_demo(conn)
        second = reg_seed.vary_demo(conn)
        # column state must not change on the second pass
        cols = {}
        for table in ("person", "place", "event"):
            cols[table] = [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} ORDER BY id").fetchall()]
        conn.close()
        assert first == second
        conn = db.connect()
        reg_seed.vary_demo(conn)
        for table in ("person", "place", "event"):
            again = [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} ORDER BY id").fetchall()]
            assert again == cols[table]
        conn.close()

    def test_vary_demo_refuses_non_demo_rows(self, tmp_db):
        """Real user data is NEVER modified — the pass must refuse."""
        from app import db
        from app import seed as reg_seed
        self._seed_registry_demo()
        conn = db.connect()
        conn.execute("UPDATE person SET created_by = 'researcher' WHERE id = 1")
        conn.commit()
        try:
            reg_seed.vary_demo(conn)
            raised = False
        except RuntimeError as exc:
            raised = True
            assert "never modified" in str(exc)
        conn.close()
        assert raised

    def test_reload_rebuilds_full_test_dataset(self, tmp_db, capsys):
        from app.military import cli
        self._seed_registry_demo()
        assert cli.reload(scale=200) == 0
        out = capsys.readouterr().out
        assert "registry demo variation" in out
        assert "military sample loaded" in out
        assert "military bulk loaded" in out
        assert cli.verify() == 0
        out = capsys.readouterr().out
        assert "11/11 checks passed" in out
        assert "FAILED" not in out

    def test_registry_demo_rows_keep_identity_under_variation(self, tmp_db):
        from app import db
        from app import seed as reg_seed
        self._seed_registry_demo()
        conn = db.connect()
        reg_seed.vary_demo(conn)
        # identity columns survive: names/codes always present
        missing = conn.execute(
            "SELECT COUNT(*) FROM person WHERE name_ar IS NULL AND "
            "name_en IS NULL AND name_original IS NULL").fetchone()[0]
        codes = conn.execute(
            "SELECT COUNT(*) FROM person WHERE code IS NULL").fetchone()[0]
        conn.close()
        assert missing == 0 and codes == 0


# ---------------------------------------------------------------------------
# Command-domain interfaces (2026-11-07 third directive)
# ---------------------------------------------------------------------------
class TestCommandDomainOrganisation:
    def test_domain_hubs_and_two_tier_nav(self):
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        app = Path("app/static/js/app.js").read_text()
        assert "A.views.milDomain" in src
        assert "milDomain" in app and "forces|operations|training|command" in app
        for d in ("forces", "operations", "training", "command"):
            assert f"{d}: [" in src            # domain entity mapping
        assert "mil-nav-sub" in src            # contextual second tier
        assert "domain:" in src

    def test_every_domain_entity_maps_to_a_hub(self):
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        import re
        dom = re.search(r"const DOMAINS = \{(.*?)\};", src, re.S).group(1)
        listed = set(re.findall(r'"(\w+)"', dom))
        from app.military.service import ENTITY_SPECS
        assert listed == set(ENTITY_SPECS)     # all 12 entities organized


class TestViewModes:
    def test_unified_list_supplies_view_modes(self):
        # military lists run on the shared engine; its viewswitch provides
        # table / cards / gallery / list for every entity alike
        from pathlib import Path
        mil = Path("app/static/js/views/military.js").read_text()
        lst = Path("app/static/js/views/list.js").read_text()
        assert "A.views.list(" in mil          # delegation to the shared engine
        assert "data-viewswitch" in lst
        assert 'siraj.view." + entity' in lst  # mode persisted per entity

    def test_tree_mode_link_for_hierarchy_entities(self):
        """The hierarchies — units and command regions — are exactly the ones
        that offer the tree, in the same screen's view switcher."""
        from pathlib import Path
        src = Path("app/static/js/views/list.js").read_text()
        assert 'TREE_ENTITIES = new Set(["unit", "region"])' in src
        assert 'out.concat("tree")' in src


class TestImportExport:
    def test_import_csv_creates_rows(self, client):
        h = {"X-Military-Role": "staff"}
        csv_text = ("name,category\n"
                    "Import Rifle Alpha,Weapons\n"
                    "Import Rifle Beta,\n")
        r = client.post("/api/military/armaments/import.csv",
                        json={"csv": csv_text, "mode": "create"}, headers=h)
        body = r.json()
        assert r.status_code == 200 and body["ok"] is True
        assert body["summary"]["created"] == 2 and body["summary"]["errors"] == 0

    def test_import_csv_upsert_by_docname(self, client):
        h = {"X-Military-Role": "staff"}
        created = client.post("/api/military/armaments",
                              json={"name": "Upsert Target"}, headers=h).json()["record"]
        csv_text = f"docname,name\n{created['docname']},Upsert Target Renamed\n"
        r = client.post("/api/military/armaments/import.csv",
                        json={"csv": csv_text, "mode": "upsert"}, headers=h)
        body = r.json()
        assert body["summary"]["updated"] == 1 and body["summary"]["created"] == 0
        got = client.get(f"/api/military/armaments/{created['id']}", headers=h).json()
        assert got["record"]["name"] == "Upsert Target Renamed"

    def test_import_csv_reports_rule_violations_per_row(self, client):
        h = {"X-Military-Role": "staff"}
        u = client.post("/api/military/units",
                        json={"name": "Import Rule Unit"}, headers=h).json()["record"]
        first = client.post("/api/military/deployments", json={
            "name": "Import Op One", "unit_id": u["id"],
            "start_date": "2026-01-01", "status": "Active", "is_current": 1},
            headers=h)
        assert first.status_code == 201
        csv_text = ("name,unit_id,start_date,status,is_current\n"
                    f"Import Op Two,{u['id']},2026-02-01,Active,1\n")
        r = client.post("/api/military/deployments/import.csv",
                        json={"csv": csv_text, "mode": "create"}, headers=h)
        body = r.json()
        assert body["summary"]["errors"] == 1
        err = [x for x in body["results"] if x["status"] == "error"][0]
        assert err["line"] == 2 and err["code"]

    def test_import_rejects_unknown_columns_and_needs_staff(self, client):
        h = {"X-Military-Role": "staff"}
        bad = client.post("/api/military/armaments/import.csv",
                          json={"csv": "name,bogus_column\nX,Y\n"}, headers=h)
        assert bad.status_code == 422
        viewer = client.post("/api/military/armaments/import.csv",
                             json={"csv": "name\nZ\n"},
                             headers={"X-Military-Role": "viewer"})
        assert viewer.status_code == 403

    def test_export_round_trip_after_import(self, client):
        h = {"X-Military-Role": "staff"}
        client.post("/api/military/classifications/import.csv",
                    json={"csv": "name\nRound Trip Class\n"}, headers=h)
        exp = client.get("/api/military/classifications/export.csv", headers=h).json()
        assert "Round Trip Class" in exp["csv"]


class TestNumberingHistory:
    def test_naming_history_endpoint(self, client):
        h = {"X-Military-Role": "admin"}
        status = client.get("/api/military/naming/status", headers=h).json()
        series = status["series"][0]
        client.put("/api/military/naming/counter",
                   json={"option_id": series["id"], "partition": "",
                         "new_value": 41, "label": series["label"]}, headers=h)
        r = client.get("/api/military/naming/history", headers=h)
        assert r.status_code == 200
        recs = r.json()["records"]
        assert recs and recs[0]["new_value"] == 41
        assert recs[0]["label"] and recs[0]["actor"]

    def test_naming_history_panel_in_ui(self):
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        assert "/naming/history" in src
        assert "mil.naming.history" in src


class TestShowMoreAndImportWiring:
    def test_dossier_show_more_wired(self):
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        assert "data-relmore" in src and "mil.dossier.showMore" in src

    def test_import_ui_wired_on_every_list(self):
        """One import UI for the whole application: every military list links
        into the shared import wizard (template → mapping → validate → commit);
        the old per-list CSV modal is gone, not duplicated."""
        from pathlib import Path
        src = Path("app/static/js/views/military.js").read_text()
        assert "milImportBtn" in src           # reachable from every list page
        assert "#/import?entity=" in src       # deep-links into the shared wizard
        assert "A.milImport" not in src        # no second, duplicate import UI
        assert "import.csv" not in src
        admin = Path("app/static/js/views/admin.js").read_text()
        assert "A.views.import" in admin       # the one wizard exists


class TestConstraintErrorsClean:
    """Regression (found by live smoke): DB constraint failures must surface
    as clean 4xx errors — never a 500, never an aborted import."""

    def test_duplicate_unique_value_is_409_not_500(self, client):
        h = {"X-Military-Role": "staff"}
        first = client.post("/api/military/classifications",
                            json={"name": "Dupe Guard Class"}, headers=h)
        assert first.status_code == 201
        again = client.post("/api/military/classifications",
                            json={"name": "Dupe Guard Class"}, headers=h)
        assert again.status_code == 409
        err = again.json()["detail"]["error"]
        assert err["code"] == "duplicate"

    def test_import_survives_duplicate_rows(self, client):
        h = {"X-Military-Role": "staff"}
        csv_text = ("name\n"
                    "Import Dupe A\n"
                    "Import Dupe A\n"
                    "Import Dupe B\n")
        r = client.post("/api/military/classifications/import.csv",
                        json={"csv": csv_text, "mode": "create"}, headers=h)
        body = r.json()
        assert r.status_code == 200
        assert body["summary"]["created"] == 2 and body["summary"]["errors"] == 1
        err = [x for x in body["results"] if x["status"] == "error"][0]
        assert err["line"] == 3 and err["code"] == "duplicate"

    def test_bad_foreign_key_is_422_not_500(self, client):
        h = {"X-Military-Role": "staff"}
        r = client.post("/api/military/divisions",
                        json={"name": "FK Guard Division", "region_id": 999999},
                        headers=h)
        assert r.status_code == 422
        assert r.json()["detail"]["error"]["code"] in ("constraint", "tree_missing_parent")

    def test_update_duplicate_is_clean_error(self, client):
        h = {"X-Military-Role": "staff"}
        a = client.post("/api/military/classifications",
                        json={"name": "Upd Dupe A"}, headers=h).json()["record"]
        client.post("/api/military/classifications",
                    json={"name": "Upd Dupe B"}, headers=h)
        r = client.patch(f"/api/military/classifications/{a['id']}",
                         json={"name": "Upd Dupe B"}, headers=h)
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# Unified list engine (2026-11-07 fourth directive): every military table is
# managed through the same query/export/meta contract as People/Places/
# Organizations, with the military service on the write path.
# ---------------------------------------------------------------------------
MIL_KEYS = ("unit", "region", "division", "classification", "armament", "holding",
            "deployment", "mission", "training", "commander", "assignment", "note")


class TestUnifiedMeta:
    def test_meta_carries_all_twelve_military_entities(self, client):
        m = client.get("/api/meta").json()
        keys = {e["key"] for e in m["entities"]}
        assert set(MIL_KEYS) <= keys
        for k in MIL_KEYS:
            fields = {f["key"] for f in m["fields"][k]}
            assert "docname" in fields
            assert m["derived"][k] == []

    def test_meta_field_descriptors_are_engine_shaped(self, client):
        m = client.get("/api/meta").json()
        by_key = {f["key"]: f for f in m["fields"]["unit"]}
        assert by_key["parent_id"]["type"] == "fk"
        assert by_key["parent_id"]["ref"] == "unit"
        assert by_key["status"]["type"] == "select"
        assert by_key["direct_personnel"]["type"] == "int"
        assert by_key["name"]["required"] is True
        assert by_key["docname"]["read_only"] is True

    def test_entity_meta_labels_are_bilingual(self, client):
        m = client.get("/api/meta").json()
        unit = next(e for e in m["entities"] if e["key"] == "unit")
        assert unit["label_en"] and unit["label_ar"] and unit["plural_ar"]


class TestUnifiedQuery:
    def test_query_shape_and_title_shim(self, client):
        r = client.post("/api/unit/query", json={"page": 1, "page_size": 5}).json()
        assert set(r) >= {"items", "total", "page", "pages"}
        if r["items"]:
            it = r["items"][0]
            assert it["name_en"] == it["name_ar"] == it["_title"]

    def test_filter_operators(self, client):
        def total(payload):
            return client.post("/api/commander/query", json=payload).json()["total"]
        all_ = total({})
        assert total({"where": [{"field": "status", "op": "eq", "value": "Active"}]}) <= all_
        assert total({"where": [{"field": "full_name", "op": "contains", "value": "a"}]}) <= all_
        assert total({"where": [{"field": "commission_date", "op": "year_lte", "value": "2030"}]}) <= all_
        assert total({"where": [{"field": "commission_date", "op": "is_null"}]}) <= all_
        assert total({"where": [{"field": "id", "op": "in", "value": [1, 2, 3]}]}) <= 3

    def test_between_and_logic_or(self, client):
        r = client.post("/api/holding/query", json={
            "where": [{"field": "quantity", "op": "between", "value": [1, 100000]}],
            "logic": "or"}).json()
        assert r["total"] >= 0
        r2 = client.post("/api/training/query", json={
            "where": [{"field": "participant_count", "op": "gte", "value": 0}]}).json()
        assert r2["total"] >= 0

    def test_q_like_search_for_unindexed_entities(self, client):
        h = {"X-Military-Role": "staff"}
        made = client.post("/api/unit", json={"name": "Zebra Search Unit"}, headers=h).json()["record"]
        r = client.post("/api/unit/query", json={"q": "Zebra", "page_size": 50}).json()
        assert r["total"] >= 1
        assert any(i["id"] == made["id"] for i in r["items"])

    def test_sort_order_and_paging(self, client):
        r = client.post("/api/note/query", json={
            "sort": "id", "order": "desc", "page": 1, "page_size": 3}).json()
        assert len(r["items"]) <= 3
        r2 = client.post("/api/note/query", json={
            "sort": "id", "order": "asc", "page": 1, "page_size": 3}).json()
        if r["items"] and r2["items"]:
            assert r["items"][0]["id"] >= r2["items"][0]["id"]

    def test_ref_labels_resolve_names(self, client):
        h = {"X-Military-Role": "staff"}
        u = client.post("/api/unit", json={"name": "Ref Label Unit"}, headers=h).json()["record"]
        client.post("/api/deployment", json={
            "name": "Ref Label Op", "unit_id": u["id"],
            "start_date": "2026-01-01"}, headers=h)
        r = client.post("/api/deployment/query", json={"page_size": 5}).json()
        refs = [i["_refs"]["unit_id"] for i in r["items"] if (i.get("_refs") or {}).get("unit_id")]
        assert refs
        assert not refs[0]["label"].startswith("#")

    def test_kpi_tiles(self, client):
        k = client.post("/api/training/kpi", json={}).json()
        assert k["entity"] == "training"
        assert any(t["key"] == "records" for t in k["tiles"])


class TestUnifiedExport:
    def test_all_formats_via_registry_exporter(self, client):
        for fmt in ("csv", "tsv", "json", "xlsx"):
            r = client.post("/api/export/unit", json={"format": fmt, "page_size": 100})
            assert r.status_code == 200
            assert len(r.content) > 0

    def test_export_respects_filters(self, client):
        full = client.post("/api/armament/export.csv".replace("export.csv", "query"),
                           json={"page_size": 1000}).json()["total"]
        assert full >= 0
        r = client.post("/api/export/armament", json={
            "format": "csv", "where": [{"field": "category", "op": "eq", "value": "Weapons"}]})
        assert r.status_code == 200

    def test_export_columns_selection(self, client):
        r = client.post("/api/export/commander", json={
            "format": "csv", "columns": ["full_name", "rank_title"]})
        header = r.content.decode("utf-8-sig").splitlines()[0]
        # the exporter writes human labels, exactly as for registry entities
        assert "Full Name" in header and "Rank Title" in header


class TestUnifiedFacadeWrites:
    def test_create_update_delete_round_trip(self, client):
        h = {"X-Military-Role": "staff"}
        cr = client.post("/api/classification",
                         json={"name": "Unified Facade Class"}, headers=h)
        assert cr.status_code == 200
        rid = cr.json()["record"]["id"]
        up = client.patch(f"/api/classification/{rid}",
                          json={"category": "Support"}, headers=h)
        assert up.status_code == 200 and up.json()["record"]["category"] == "Support"
        assert client.delete(f"/api/classification/{rid}", headers=h).status_code == 200
        assert client.get(f"/api/classification/{rid}").status_code == 404

    def test_rules_apply_through_the_facade(self, client):
        h = {"X-Military-Role": "staff"}
        bad = client.post("/api/mission", json={
            "name": "Facade Rule Mission", "unit_id": 999999,
            "start_date": "2026-01-01"}, headers=h)
        assert bad.status_code == 422
        assert bad.json()["detail"]["error"]["code"] == "unit_not_found"

    def test_viewer_is_blocked_on_writes(self, client):
        v = {"X-Military-Role": "viewer"}
        assert client.post("/api/armament", json={"name": "X"}, headers=v).status_code == 403
        assert client.delete("/api/armament/1", headers=v).status_code == 403

    def test_bulk_delete_counts(self, client):
        h = {"X-Military-Role": "staff"}
        u = client.post("/api/unit", json={"name": "Bulk Note Unit"}, headers=h).json()["record"]
        a = client.post("/api/note", json={
            "note_text": "bulk a", "entity_type": "unit", "target_id": u["id"],
            "author": "tester"}, headers=h).json()["record"]
        b = client.post("/api/note", json={
            "note_text": "bulk b", "entity_type": "unit", "target_id": u["id"],
            "author": "tester"}, headers=h).json()["record"]
        res = client.post("/api/note/bulk",
                          json={"ids": [a["id"], b["id"], 999999], "action": "delete"},
                          headers=h).json()
        assert res["ok"] == 2 and res["failed"] == 1

    def test_restore_rejected_for_military(self, client):
        r = client.post("/api/unit/1/restore")
        assert r.status_code == 422

    def test_next_code_and_duplicates(self, client):
        nc = client.get("/api/unit/next-code")
        assert nc.status_code == 200 and "code" in nc.json()
        dup = client.get("/api/unit/duplicates")
        assert dup.status_code == 200 and "groups" in dup.json()

    def test_saved_views_accept_military_entities(self, client):
        r = client.post("/api/saved-views",
                        json={"name": "Units", "entity_type": "unit"})
        assert r.status_code == 200
        got = client.get("/api/saved-views?entity_type=unit").json()
        assert any(v["name"] == "Units" for v in got)


class TestUnifiedWiring:
    def test_list_engine_gates_registry_only_tools(self):
        from pathlib import Path
        lst = Path("app/static/js/views/list.js").read_text()
        assert "const MIL = new Set(" in lst
        assert "isMil(entity)" in lst
        # registry-only affordances are hidden behind isMil gates
        assert '${isMil(entity) ? "" : `<button class="btn sm" data-dups>' in lst
        assert '${isMil(entity) ? "" : `\n      <button class="btn sm" data-bulk-status>' in lst

    def test_military_list_delegates_to_shared_engine(self):
        from pathlib import Path
        mil = Path("app/static/js/views/military.js").read_text()
        assert "A.views.list(" in mil
        assert "A.milImport" not in mil        # import is the shared wizard now
        assert "entityKey(" in mil

    def test_military_add_edit_ride_the_shared_form_routes(self):
        """Add and edit are the ONE shared form (recordNew/recordEdit) for
        every entity, military included — only the record *dossier* keeps its
        military layout."""
        from pathlib import Path
        app = Path("app/static/js/app.js").read_text()
        assert 're: /^\\/military\\/([\\w-]+)\\/new$/, view: "recordNew"' in app
        assert 're: /^\\/military\\/([\\w-]+)\\/(\\d+)$/, view: "recordEdit"' in app
        assert 'view: "milForm"' not in app
        assert 'view: "milDossier", keys: ["entity", "id"]' in app

    def test_every_request_carries_the_role_header(self):
        from pathlib import Path
        core = Path("app/static/js/core.js").read_text()
        assert "X-Military-Role" in core


class TestUnifiedImportPipeline:
    """One import system for the whole application: the shared wizard
    (template → mapping → preview → validate → commit, job history) serves
    registry AND military entities.  Regression from the production session:
    ``GET /api/import/template/<military>`` returned 404 because the import
    pipeline only knew registry specs."""

    def test_military_templates_no_longer_404(self, client):
        for entity in ("unit", "region", "division", "note", "training"):
            for fmt in ("xlsx", "csv", "json"):
                r = client.get(f"/api/import/template/{entity}?format={fmt}&lang=ar")
                assert r.status_code == 200, (entity, fmt, r.text)
                assert r.content
        r = client.get("/api/import/template/region?format=csv&lang=en")
        header = r.content.decode("utf-8-sig").splitlines()[0]
        assert "Docname" in header and "Name" in header   # human-label headers

    def test_preview_validate_commit_writes_through_the_service(self, client):
        csv_bytes = b"name,country\nAlpha Region,NL\nBeta Region,DE\n"
        prev = client.post("/api/import/preview", data={"entity": "region"},
                           files={"file": ("regions.csv", csv_bytes, "text/csv")})
        assert prev.status_code == 200
        body = prev.json()
        assert body["total_rows"] == 2
        mapping = body["mapping"]
        assert mapping.get("name") == "name"

        val = client.post("/api/import/validate", json={
            "entity": "region", "upload_id": body["upload_id"],
            "filename": "regions.csv", "mapping": mapping, "mode": "create"})
        rep = val.json()
        assert val.status_code == 200 and rep["total"] == 2 and rep["failed"] == 0

        com = client.post("/api/import/commit", json={
            "entity": "region", "upload_id": body["upload_id"],
            "filename": "regions.csv", "mapping": mapping, "mode": "create"})
        rep = com.json()
        assert com.status_code == 200 and rep["created"] == 2 and rep["failed"] == 0
        # rows ran through the military service: automatic document names exist
        with service.transaction() as conn:
            data = service.list_records(conn, "region", limit=50, offset=0)
        mine = [r for r in data["records"] if r["name"] in ("Alpha Region", "Beta Region")]
        assert len(mine) == 2 and all(r.get("docname") for r in mine)

    def test_import_job_history_is_recorded(self, client):
        csv_bytes = b"name\nJob Region\n"
        prev = client.post("/api/import/preview", data={"entity": "region"},
                           files={"file": ("r.csv", csv_bytes, "text/csv")}).json()
        rep = client.post("/api/import/validate", json={
            "entity": "region", "upload_id": prev["upload_id"], "filename": "r.csv",
            "mapping": prev["mapping"], "mode": "create"}).json()
        assert rep["job_id"]
        job = client.get(f"/api/import/jobs/{rep['job_id']}")
        assert job.status_code == 200
        assert job.json()["entity_type"] == "region"
        assert job.json()["dry_run"] == 1            # validate jobs never write


class TestClearAllData:
    """The production reset: wipe every record, keep static/reference data and
    the append-only ledgers, archive-aside before anything is removed."""

    def test_clear_requires_the_exact_phrase(self, client):
        assert client.post("/api/maintenance/clear-data", json={}).status_code == 422
        assert client.post("/api/maintenance/clear-data",
                           json={"confirm": "clear all data"}).status_code == 422
        assert client.post("/api/maintenance/clear-data",
                           json={"confirm": "CLEAR ALL"}).status_code == 422
        ok = client.post("/api/maintenance/clear-data", json={"confirm": "CLEAR ALL DATA"})
        assert ok.status_code == 200

    def test_clear_wipes_records_preserves_static_and_ledger(self, client, tmp_db):
        from app import db, repo, schemas
        h = {"X-Military-Role": "staff"}
        r = client.post("/api/military/regions", json={"name": "Clear Region"}, headers=h)
        assert r.status_code == 201
        conn = db.connect()
        repo.create_record(conn, schemas.ENTITIES["person"],
                           {"name_en": "Clear Person", "name_ar": "شخص"})
        conn.execute("INSERT INTO mil_meta (key, value) VALUES ('bulk_loaded', '1')")
        conn.commit()
        tables = ("lookup", "app_user", "setting", "sequence", "locale",
                  "naming_series_option", "search_doc_config")
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        seq_rows = conn.execute("SELECT COUNT(*) FROM sequence").fetchone()[0]
        conn.close()

        res = client.post("/api/maintenance/clear-data", json={"confirm": "CLEAR ALL DATA"})
        assert res.status_code == 200
        body = res.json()
        assert body["cleared_rows"] > 0

        conn = db.connect()
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        assert after == before                      # static/reference data intact
        for t in ("region", "military_unit", "person", "place", "search_doc"):
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
        seq = conn.execute("SELECT next_value FROM sequence").fetchall()
        assert len(seq) == seq_rows and all(row[0] == 1 for row in seq)  # numbering restarts
        assert conn.execute(
            "SELECT COUNT(*) FROM mil_meta WHERE key='bulk_loaded'").fetchone()[0] == 0
        # the append-only ledger recorded the clear and was not wiped
        assert conn.execute(
            "SELECT COUNT(*) FROM change_log WHERE entity_code='maintenance.clear_data'"
        ).fetchone()[0] == 1
        conn.close()
        # archive-aside: the pre-clear snapshot exists next to the database
        from pathlib import Path
        assert body["archive"].endswith("-preclear.db")
        assert list(Path(tmp_db).parent.glob("*-preclear.db"))

    def test_clear_is_idempotent(self, client):
        first = client.post("/api/maintenance/clear-data", json={"confirm": "CLEAR ALL DATA"})
        again = client.post("/api/maintenance/clear-data", json={"confirm": "CLEAR ALL DATA"})
        assert first.status_code == again.status_code == 200
        assert again.json()["cleared_rows"] == 0

    def test_clear_survives_foreign_key_order(self, client):
        """Regression (found live): the military schema declares real foreign
        keys, and an alphabetical wipe deleted parents (classification) before
        children (military_unit) — the whole request 500'd.  A wipe must be
        order-independent."""
        h = {"X-Military-Role": "staff"}
        cls = client.post("/api/military/classifications",
                          json={"name": "FK Class"}, headers=h).json()["record"]
        reg = client.post("/api/military/regions",
                          json={"name": "FK Region"}, headers=h).json()["record"]
        r = client.post("/api/military/units",
                        json={"name": "FK Unit", "classification_id": cls["id"],
                              "region_id": reg["id"]}, headers=h)
        assert r.status_code == 201
        res = client.post("/api/maintenance/clear-data", json={"confirm": "CLEAR ALL DATA"})
        assert res.status_code == 200
        from app import db
        conn = db.connect()
        for t in ("classification", "region", "military_unit"):
            assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0, t
        conn.close()


class TestProductionReadiness:
    """The interface must present no test-data tooling; demo seeding is opt-in;
    linked-field quick-create must work against the strict military validator."""

    def test_quickcreate_meta_keys_do_not_break_military_create(self, client):
        """Regression: A.quickCreate sends `_reason` (and `actor`) with every
        inline create; the strict military validator 422'd on unknown keys."""
        h = {"X-Military-Role": "staff"}
        r = client.post("/api/region", json={"name": "Quick Region",
                                             "_reason": "created inline from a related field",
                                             "actor": "someone"}, headers=h)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["name"] == "Quick Region" and rec["docname"]

    def test_specs_required_flags_match_the_service(self):
        from app.military.specs import MIL_SPECS
        must = {
            "division": ["region_id"], "mission": ["start_date"],
            "holding": ["quantity"],
            "training": ["end_date", "duration_days", "participant_count"],
            "assignment": ["assigned_date"],
            "note": ["entity_type", "target_id", "note_text", "author"],
        }
        for ent, keys in must.items():
            for k in keys:
                f = MIL_SPECS[ent].field(k)
                assert f is not None and f.required, (ent, k)

    def test_demo_seeding_is_opt_in_not_default(self):
        from pathlib import Path
        assert 'SIRAJ_SEED_DEMO", "0"' in Path("app/server/api.py").read_text()
        assert "args.demo if args.demo is not None else False" \
            in Path("app/cli.py").read_text()

    def test_no_sample_data_buttons_or_locales_remain(self):
        import json
        from pathlib import Path
        mil = Path("app/static/js/views/military.js").read_text()
        assert "milSample" not in mil and "loadSample" not in mil
        assert "/sample" not in mil                 # no test-data API calls in the UI
        for lang in ("en", "ar"):
            loc = json.loads(Path(f"app/static/js/locales/{lang}.json").read_text())
            for k in ("mil.action.loadSample", "mil.action.resetSample",
                      "mil.action.clearSample"):
                assert k not in loc

    def test_clear_data_exposed_once_with_phrase_gate(self):
        from pathlib import Path
        src = Path("app/server/api.py").read_text()
        assert src.count('"/api/maintenance/clear-data"') == 1   # one endpoint
        assert "CLEAR_CONFIRM_PHRASE" in src
        core = Path("app/static/js/core.js").read_text()
        assert "requirePhrase" in core              # typed-phrase confirm dialog
        admin = Path("app/static/js/views/admin.js").read_text()
        assert admin.count("doClearData") == 2      # one card, one handler

    def test_note_dossier_never_collects_notes_on_notes(self):
        from pathlib import Path
        mil = Path("app/static/js/views/military.js").read_text()
        assert 'entity === "note" ? { records: [], total: 0 }' in mil

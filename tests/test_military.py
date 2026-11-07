"""Military Organization — test suite (self-contained module).

Isolated from the SIRAJ registry: every test runs against a temporary
``military.db``.  Covers the rule catalogue (§8), the naming engine (§11.2),
the audit trail (§12.3), role enforcement (§8.9) and the sample dataset.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.military import api as military_api
from app.military import dbm, naming, rules, seed, service
from app.military.rules import RuleViolation
from app.military.service import ServiceError


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the module at a throwaway database and reset lazy init."""
    db_path = tmp_path / "military.db"
    monkeypatch.setattr(dbm, "MIL_DB_PATH", db_path)
    monkeypatch.setattr(dbm, "_initialised", False)
    return db_path


@pytest.fixture()
def conn(tmp_db):
    with service.transaction() as c:
        yield c


@pytest.fixture()
def client(tmp_db):
    app = FastAPI()
    app.include_router(military_api.router)
    with TestClient(app) as tc:
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
def test_schema_initialises_and_seeds_19_series(conn):
    naming.seed_options(conn)
    count = conn.execute("SELECT COUNT(*) AS n FROM naming_series_option").fetchone()["n"]
    assert count == 19


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
    assert "10/10 checks passed" in out
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
    for view in ("military", "milList", "milForm", "milTree", "milForce",
                 "milHoldings", "milNaming", "milAudit"):
        assert f"A.views.{view}" in js, view
    app_js = Path("app/static/js/app.js").read_text(encoding="utf-8")
    assert "/military" in app_js
    # the parallel standalone app is gone: one structure only
    assert not Path("app/military/ui").exists()

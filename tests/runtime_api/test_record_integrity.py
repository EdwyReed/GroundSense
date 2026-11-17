"""Exercise record-write invariants through HTTP against a real SQL database."""
from concurrent.futures import ThreadPoolExecutor
import threading
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDSENSE_DATABASE_URL", f"sqlite:///{tmp_path}/records.db")
    monkeypatch.setenv("GROUNDSENSE_DATA_DIR", str(tmp_path / "artifacts"))
    from apps.api.main import create_app

    with TestClient(create_app(data_mode="synthetic"), base_url="https://testserver") as value:
        yield value


def bootstrap(client):
    state = client.get("/api/v1/bootstrap").json()
    return state, {"Origin": "https://testserver", "X-CSRF-Token": state["csrf_token"]}


@pytest.mark.parametrize("version", [{}, {"expected_version": None}, {"expected_version": True},
                                     {"expected_version": 1.0}, {"expected_version": "1"},
                                     {"expected_version": 0}, {"expected_version": -1}])
@pytest.mark.parametrize("adjudication", [False, True])
def test_revision_requires_explicit_positive_integer_version(client, version, adjudication):
    _, headers = bootstrap(client)
    if adjudication:
        record = client.post("/api/v1/observations", json={"note": "Синтетичний запис"}, headers=headers).json()
        path = f"/api/v1/observations/{record['id']}/adjudications"
        response = client.post(path, json={"decision": "accepted", "reason": "Перевірка", **version}, headers=headers)
        read_path = f"/api/v1/observations/{record['id']}"
    else:
        read_path = "/api/v1/protocols/protocol-moisture"
        response = client.patch(read_path, json={"name": "Змінено без належної версії", **version}, headers=headers)
    assert response.status_code == 422, response.text
    assert client.get(read_path).json()["version"] == 1


@pytest.mark.parametrize("adjudication", [False, True])
def test_concurrent_revisions_have_one_winner_and_one_revision(client, adjudication):
    from apps.api.main import Revision

    state, headers = bootstrap(client)
    kind = "observations" if adjudication else "protocols"
    if adjudication:
        ident = client.post("/api/v1/observations", json={"note": "Синтетичний запис"}, headers=headers).json()["id"]
    else:
        ident = "protocol-moisture"
    path = f"/api/v1/{kind}/{ident}"
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    reads = 0

    def align_reads(connection, cursor, statement, parameters, context, executemany):
        # Freeze both real SELECTs at the same database version, not at an
        # arbitrary sleep. This deterministically exposes lost-update writes.
        nonlocal reads
        if not statement.lstrip().startswith("SELECT") or "resources.logical_id" not in statement or ident not in parameters:
            return
        with lock:
            pause = reads < 2
            reads += 1
        if pause:
            barrier.wait(timeout=5)

    def revise(writer):
        if adjudication:
            return client.post(path + "/adjudications", json={"decision": "accepted", "reason": writer, "expected_version": 1}, headers=headers)
        return client.patch(path, json={"name": writer, "expected_version": 1}, headers=headers)

    with client.app.state.factory() as database:
        engine = database.get_bind()
    event.listen(engine, "after_cursor_execute", align_reads)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(revise, ["writer-a", "writer-b"]))
    finally:
        event.remove(engine, "after_cursor_execute", align_reads)
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    stored = client.get(path).json()
    assert stored["version"] == 2
    assert (stored["adjudication"]["reason"] if adjudication else stored["name"]) in {"writer-a", "writer-b"}
    with client.app.state.factory() as database:
        revisions = database.scalars(select(Revision).where(Revision.workspace_id == state["workspace"]["id"], Revision.kind == kind, Revision.logical_id == ident, Revision.version == 2)).all()
        assert len(revisions) == 1
    actions = client.get("/api/v1/audit").json()["items"]
    assert len([r for r in actions if r["target"] == f"{kind}/{ident}" and r["action"] == ("adjudicate" if adjudication else "revise")]) == 1


@pytest.mark.parametrize("kind,forged", [
    ("observations", {"adjudication": {"decision": "accepted", "reason": "Підміна"}}),
    ("observations", {"adjudication": None}),
    ("models", {"status": "approved"}),
    ("models", {"status": {"approved": True}}),
    ("models", {"calibrated": True}),
    ("models", {"model_approval": True}),
    ("models", {"production_eligible": True}),
])
@pytest.mark.parametrize("edit", [False, True])
def test_generic_writes_cannot_forge_review_or_model_approval(client, kind, forged, edit):
    _, headers = bootstrap(client)
    original = {"id": "WRITE-INTEGRITY", "name": "Синтетичний запис"}
    path = f"/api/v1/{kind}/{original['id']}"
    if edit:
        stored = client.post(f"/api/v1/{kind}", json=original, headers=headers).json()
        response = client.patch(path, json={**forged, "expected_version": 1}, headers=headers)
    else:
        response = client.post(f"/api/v1/{kind}", json={**original, **forged}, headers=headers)
    assert response.status_code == 422, response.text
    if edit:
        assert client.get(path).json() == stored
    else:
        assert client.get(path).status_code == 404


@pytest.mark.parametrize("kind,forged", [
    ("observations", {"adjudication": {"decision": "accepted"}}),
    ("models", {"status": "approved"}),
])
def test_import_preview_cannot_bypass_review_or_model_approval(client, kind, forged):
    import json

    _, headers = bootstrap(client)
    record = {"id": "IMPORT-INTEGRITY", "name": "Синтетичний запис", **forged}
    preview = client.post("/api/v1/imports", json={"resource": kind, "format": "json", "data": json.dumps([record])}, headers=headers)
    assert preview.status_code == 201
    assert preview.json()["errors"]
    committed = client.post(f"/api/v1/imports/{preview.json()['id']}/commit", json={}, headers=headers)
    assert committed.status_code == 409
    assert client.get(f"/api/v1/{kind}/{record['id']}").status_code == 404


def test_readonly_source_catalog_cannot_be_deleted_even_by_demo_admin(client):
    state, headers = bootstrap(client)
    assert client.post("/api/v1/demo/role", json={"role": "admin"}, headers=headers).status_code == 200
    state, headers = bootstrap(client)
    path = f"/api/v1/sources/{state['sources'][0]['id']}"
    original = client.get(path).json()
    response = client.delete(path, headers=headers)
    assert response.status_code == 404
    assert client.get(path).json() == original


def admin_headers(client):
    _, headers = bootstrap(client)
    assert client.post("/api/v1/demo/role", json={"role": "admin"}, headers=headers).status_code == 200
    return bootstrap(client)


@pytest.mark.parametrize("version", [{}, {"expected_version": None}, {"expected_version": True},
                                     {"expected_version": 1.0}, {"expected_version": "1"},
                                     {"expected_version": 0}, {"expected_version": -1}])
def test_delete_requires_explicit_positive_integer_version(client, version):
    _, headers = admin_headers(client)
    path = "/api/v1/protocols/protocol-moisture"
    response = client.request("DELETE", path, json=version, headers=headers)
    assert response.status_code == 422
    assert client.get(path).json()["version"] == 1


def test_stale_delete_conflicts_and_current_delete_appends_tombstone_revision(client):
    from apps.api.main import Resource, Revision

    state, headers = admin_headers(client)
    path = "/api/v1/protocols/protocol-moisture"
    assert client.patch(path, json={"name": "Оновлений протокол", "expected_version": 1}, headers=headers).status_code == 200
    assert client.request("DELETE", path, json={"expected_version": 1}, headers=headers).status_code == 409
    assert client.get(path).json()["version"] == 2
    deleted = client.request("DELETE", path, json={"expected_version": 2}, headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"id": "protocol-moisture", "version": 3, "tombstoned": True}
    assert client.get(path).status_code == 404
    with client.app.state.factory() as database:
        row = database.scalar(select(Resource).where(Resource.workspace_id == state["workspace"]["id"], Resource.kind == "protocols", Resource.logical_id == "protocol-moisture"))
        assert row.tombstoned == 1 and row.version == 3
        revisions = database.scalars(select(Revision).where(Revision.workspace_id == state["workspace"]["id"], Revision.kind == "protocols", Revision.logical_id == "protocol-moisture").order_by(Revision.version)).all()
        assert [r.version for r in revisions] == [1, 2, 3]
        assert json.loads(revisions[-1].data)["name"] == "Оновлений протокол"
        assert json.loads(revisions[-1].data)["tombstoned"] is True
    event_row = next(r for r in client.get("/api/v1/audit").json()["items"] if r["action"] == "tombstone")
    assert event_row["details"] == {"version": 3, "tombstoned": True}


@pytest.mark.parametrize("version,status", [(9007199254740991, 409), (9007199254740992, 422), (10**100, 422)])
def test_delete_respects_interoperable_json_integer_range(client, version, status):
    _, headers = admin_headers(client)
    path = "/api/v1/protocols/protocol-moisture"
    response = client.request("DELETE", path, json={"expected_version": version}, headers=headers)
    assert response.status_code == status
    assert client.get(path).json()["version"] == 1


def test_delete_read_before_concurrent_edit_cannot_tombstone_new_version(client):
    _, headers = admin_headers(client)
    path = "/api/v1/protocols/protocol-moisture"
    reads = 0
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    release_delete = threading.Event()

    def align_reads(connection, cursor, statement, parameters, context, executemany):
        nonlocal reads
        if not statement.lstrip().startswith("SELECT") or "resources.logical_id" not in statement or "protocol-moisture" not in parameters:
            return
        with lock:
            pause = reads < 2
            reads += 1
        if pause:
            barrier.wait(timeout=5)

    def hold_delete(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("UPDATE") and any(p.get("tombstoned") == 1 for p in context.compiled_parameters):
            assert release_delete.wait(timeout=6), "Concurrent PATCH did not finish"

    with client.app.state.factory() as database:
        engine = database.get_bind()
    event.listen(engine, "after_cursor_execute", align_reads)
    event.listen(engine, "before_cursor_execute", hold_delete)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            edit = pool.submit(client.patch, path, json={"name": "Переможець", "expected_version": 1}, headers=headers)
            deletion = pool.submit(client.request, "DELETE", path, json={"expected_version": 1}, headers=headers)
            try:
                assert edit.result(timeout=5).status_code == 200
            finally:
                release_delete.set()
            assert deletion.result(timeout=5).status_code == 409
    finally:
        release_delete.set()
        event.remove(engine, "after_cursor_execute", align_reads)
        event.remove(engine, "before_cursor_execute", hold_delete)
    assert client.get(path).json()["name"] == "Переможець"


@pytest.mark.parametrize("kind", ["models", "envelopes"])
@pytest.mark.parametrize("method", ["post", "patch", "import"])
@pytest.mark.parametrize("forged", [{"approval": {"approved": True}}, {"name": {"approved": True}}, {"calibrated": True}])
def test_metadata_schema_rejects_nested_approval_and_nontext_fields(client, kind, method, forged):
    _, headers = bootstrap(client)
    original = {"id": "METADATA-INTEGRITY", "name": "Синтетичні метадані"}
    if method == "patch":
        assert client.post(f"/api/v1/{kind}", json=original, headers=headers).status_code == 201
        response = client.patch(f"/api/v1/{kind}/{original['id']}", json={**forged, "expected_version": 1}, headers=headers)
    elif method == "import":
        response = client.post("/api/v1/imports", json={"resource": kind, "format": "json", "data": json.dumps([{**original, **forged}])}, headers=headers)
        assert response.status_code == 201 and response.json()["errors"]
        return
    else:
        response = client.post(f"/api/v1/{kind}", json={**original, **forged}, headers=headers)
    assert response.status_code == 422


def test_legacy_metadata_is_read_as_unapproved_view_without_rewriting_history(client):
    from apps.api.main import Resource

    state, headers = bootstrap(client)
    assert client.post("/api/v1/models", json={"id": "LEGACY-METADATA", "name": "Старі метадані"}, headers=headers).status_code == 201
    with client.app.state.factory() as database:
        row = database.scalar(select(Resource).where(Resource.workspace_id == state["workspace"]["id"], Resource.kind == "models", Resource.logical_id == "LEGACY-METADATA"))
        row.data = json.dumps({"name": "Старі метадані", "approval": {"approved": True}, "calibrated": True, "status": "approved"})
        database.commit()
    view = client.get("/api/v1/models/LEGACY-METADATA").json()
    assert "approval" not in view and view["status"] == "blocked"
    assert view["metadata_only"] is True and view["model_approval"] is False and view["production_eligible"] is False
    assert view["calibrated"] is None
    with client.app.state.factory() as database:
        raw = database.scalar(select(Resource).where(Resource.workspace_id == state["workspace"]["id"], Resource.logical_id == "LEGACY-METADATA"))
        assert json.loads(raw.data)["approval"]["approved"] is True

import gc
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.api.routes import upstream
from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.services.upstream_client import MockUpstreamClient, RealUpstreamClient
from backend.app.services.upstream_scheduler import UpstreamScheduler
from backend.app.storage.sqlite_store import SQLiteStore


class _DummyOrchestrator:
    def add_wechat(self, lead_id, greeting, dry_run, human_approval):
        return {"job_id": "job_1", "status": "SUCCESS"}


@pytest.fixture
def mock_scheduler_env():
    tmp_dir = tempfile.TemporaryDirectory()
    db_path = Path(tmp_dir.name) / "test.db"
    store = SQLiteStore(db_path)
    store.save_upstream_config({"upstream_mode": "mock"})

    scheduler = UpstreamScheduler(
        settings=get_settings(),
        store=store,
        orchestrator_factory=lambda: _DummyOrchestrator(),
    )
    scheduler.start()

    original_scheduler = upstream.global_scheduler
    upstream.global_scheduler = scheduler
    app.dependency_overrides[deps.get_store] = lambda: store

    try:
        yield {"scheduler": scheduler, "store": store}
    finally:
        scheduler.stop()
        upstream.global_scheduler = original_scheduler
        app.dependency_overrides.pop(deps.get_store, None)
        scheduler_local = scheduler
        store_local = store
        del scheduler
        del store
        del scheduler_local
        del store_local
        gc.collect()
        tmp_dir.cleanup()


def test_seed_mock_leads_endpoint_seeds_and_triggers_fetch(mock_scheduler_env):
    client = TestClient(app)
    payload = {"leads": [
        {
            "lead_id": "seed_lead_1",
            "phone": "13800000001",
            "customer_name": "种子1",
            "greeting": "你好",
        },
        {
            "lead_id": "seed_lead_2",
            "phone": "13800000002",
            "customer_name": "种子2",
            "greeting": "你好",
        },
    ]}

    response = client.post("/api/v1/upstream/dev/seed-mock-leads", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["seeded"] == 2
    assert body["accepted_by_scheduler"] == 2
    assert body["scheduler_alive"] is True

    store = mock_scheduler_env["store"]
    assert store.get_lead("seed_lead_1") is not None
    assert store.get_lead("seed_lead_2") is not None


def test_seed_mock_leads_endpoint_reports_seeded_and_accepted_counts(mock_scheduler_env):
    client = TestClient(app)
    payload = {"leads": [
        {"lead_id": "dup_lead", "phone": "13800000010", "customer_name": "A", "greeting": "你好"},
        {"lead_id": "dup_lead", "phone": "13800000010", "customer_name": "A", "greeting": "你好"},
        {"lead_id": "fresh_lead", "phone": "13800000011", "customer_name": "B", "greeting": "你好"},
    ]}

    first = client.post("/api/v1/upstream/dev/seed-mock-leads", json=payload).json()
    second = client.post("/api/v1/upstream/dev/seed-mock-leads", json=payload).json()

    assert first["seeded"] == 2
    assert first["accepted_by_scheduler"] == 2
    assert second["seeded"] == 2
    assert second["accepted_by_scheduler"] == 0


def test_seed_mock_leads_endpoint_rejected_when_client_is_real():
    tmp_dir = tempfile.TemporaryDirectory()
    try:
        db_path = Path(tmp_dir.name) / "test.db"
        store = SQLiteStore(db_path)
        scheduler = UpstreamScheduler(
            settings=get_settings(),
            store=store,
            orchestrator_factory=lambda: _DummyOrchestrator(),
        )
        scheduler.client = RealUpstreamClient("http://example.invalid", "id", "secret")
        scheduler.lead_source = None

        original_scheduler = upstream.global_scheduler
        upstream.global_scheduler = scheduler
        app.dependency_overrides[deps.get_store] = lambda: store

        client = TestClient(app)
        response = client.post(
            "/api/v1/upstream/dev/seed-mock-leads",
            json={"leads": [{"lead_id": "x", "phone": "1380000", "customer_name": "X", "greeting": "g"}]},
        )

        assert response.status_code == 400
        assert "mock" in response.json()["detail"].lower()
    finally:
        upstream.global_scheduler = original_scheduler
        app.dependency_overrides.pop(deps.get_store, None)
        scheduler.stop()
        del scheduler
        del store
        gc.collect()
        tmp_dir.cleanup()


def test_seed_mock_leads_endpoint_rejects_missing_required_fields(mock_scheduler_env):
    client = TestClient(app)
    response = client.post(
        "/api/v1/upstream/dev/seed-mock-leads",
        json={"leads": [{"lead_id": "x", "customer_name": "X", "greeting": "g"}]},
    )

    assert response.status_code == 422

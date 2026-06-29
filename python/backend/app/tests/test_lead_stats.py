import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.config import get_settings
from backend.app.main import app, settings
from backend.app.schemas.lead import LeadStatus
from backend.app.storage.sqlite_store import SQLiteStore


def _create_test_store() -> SQLiteStore:
    _, db_path = tempfile.mkstemp(suffix=".db")
    store = SQLiteStore(Path(db_path))
    return store


def _create_lead(store: SQLiteStore, status: str) -> str:
    """Helper to create a lead with given status"""
    import uuid
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    lead_id = f"lead_{uuid.uuid4().hex[:12]}"
    lead = {
        "lead_id": lead_id,
        "customer_name": "Test",
        "company": "Test",
        "phone": "13800000000",
        "sales_id": "sales_demo_001",
        "status": status,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    store.create_lead(lead)
    return lead_id


def test_empty_db_stats():
    """Test stats on empty database: all counts 0, all 15 statuses present in by_status"""
    store = _create_test_store()
    # Override store, so that lead_service uses our test store
    app.dependency_overrides[deps.get_store] = lambda: store
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/leads/stats",
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["success"] == 0
        assert data["running"] == 0
        assert data["failure"] == 0
        # Check all 15 statuses are present in by_status
        assert len(data["by_status"]) == 15
        for status in LeadStatus:
            assert data["by_status"][status.value] == 0
        # Check ts exists
        assert "ts" in data
    finally:
        app.dependency_overrides.pop(deps.get_store, None)


def test_single_status_stats():
    """Test stats with all leads in single status (NEW_LEAD)"""
    store = _create_test_store()
    _create_lead(store, LeadStatus.NEW_LEAD.value)
    _create_lead(store, LeadStatus.NEW_LEAD.value)
    _create_lead(store, LeadStatus.NEW_LEAD.value)

    app.dependency_overrides[deps.get_store] = lambda: store
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/leads/stats",
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["success"] == 0
        assert data["running"] == 0
        assert data["failure"] == 0
        assert data["by_status"][LeadStatus.NEW_LEAD.value] == 3
        # Check all other statuses are 0
        for status in LeadStatus:
            if status != LeadStatus.NEW_LEAD:
                assert data["by_status"][status.value] == 0
    finally:
        app.dependency_overrides.pop(deps.get_store, None)


def test_mixed_status_stats():
    """Test stats with mixed statuses"""
    store = _create_test_store()
    # Create 2x WECHAT_ACCEPTED (success)
    _create_lead(store, LeadStatus.WECHAT_ACCEPTED.value)
    _create_lead(store, LeadStatus.WECHAT_ACCEPTED.value)
    # Create 3x failure states (1 each)
    _create_lead(store, LeadStatus.RPA_FAILED.value)
    _create_lead(store, LeadStatus.WECHAT_ADD_REJECTED.value)
    _create_lead(store, LeadStatus.WECHAT_TARGET_NOT_FOUND.value)
    # Create 1x running state
    _create_lead(store, LeadStatus.RPA_EXECUTING.value)

    app.dependency_overrides[deps.get_store] = lambda: store
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/leads/stats",
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 6
        assert data["success"] == 2
        assert data["running"] == 1
        assert data["failure"] == 3
        # Check individual status counts
        assert data["by_status"][LeadStatus.WECHAT_ACCEPTED.value] == 2
        assert data["by_status"][LeadStatus.RPA_FAILED.value] == 1
        assert data["by_status"][LeadStatus.WECHAT_ADD_REJECTED.value] == 1
        assert data["by_status"][LeadStatus.WECHAT_TARGET_NOT_FOUND.value] == 1
        assert data["by_status"][LeadStatus.RPA_EXECUTING.value] == 1
    finally:
        app.dependency_overrides.pop(deps.get_store, None)


def test_all_statuses_once():
    """Test stats with all 15 statuses appearing exactly once"""
    store = _create_test_store()
    for status in LeadStatus:
        _create_lead(store, status.value)

    app.dependency_overrides[deps.get_store] = lambda: store
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/leads/stats",
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 15
        # Check success: only WECHAT_ACCEPTED
        assert data["success"] == 1
        # Check running: 6 states (CALLING, INTENT_CONFIRMED, RPA_PENDING_APPROVAL, RPA_SIMULATED, RPA_EXECUTING, WECHAT_ADD_REQUESTED)
        assert data["running"] == 6
        # Check failure: 6 states
        assert data["failure"] == 6
        # Check each status appears exactly once
        for status in LeadStatus:
            assert data["by_status"][status.value] == 1
    finally:
        app.dependency_overrides.pop(deps.get_store, None)


def test_stats_unauthorized():
    """Test stats endpoint without auth token returns 401"""
    client = TestClient(app)
    response = client.get("/api/v1/leads/stats")
    assert response.status_code == 401

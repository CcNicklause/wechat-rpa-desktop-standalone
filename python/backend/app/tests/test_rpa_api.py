from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.errors import AppError
from backend.app.main import app, settings


class _BusyOrchestrator:
    def add_wechat(self, lead_id, greeting, dry_run, human_approval):
        raise AppError("RPA_LEAD_BUSY", "该客户已有进行中的 RPA 任务，请勿重复触发", 409)


class _JobsOrchestrator:
    def list_jobs_by_lead(self, lead_id, limit):
        assert lead_id == "lead_1"
        assert limit == 50
        return [
            {
                "job_id": "job_new",
                "lead_id": "lead_1",
                "status": "REAL_COMPLETED",
                "rpa_mode": "real",
                "dry_run": False,
                "human_approval": False,
                "greeting": "hello",
                "steps": ["STEP_1", "STEP_2"],
                "error_code": None,
                "error_message": None,
                "outcome_type": "success",
                "created_at": "2026-06-28T00:00:00+00:00",
                "updated_at": "2026-06-28T00:02:00+00:00",
            }
        ]


def test_add_wechat_route_returns_409_when_lead_is_busy():
    app.dependency_overrides[deps.get_rpa_orchestrator] = lambda: _BusyOrchestrator()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/rpa/add-wechat",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            json={
                "lead_id": "lead_busy",
                "greeting": "你好",
                "dry_run": False,
                "human_approval": False,
            },
        )
    finally:
        app.dependency_overrides.pop(deps.get_rpa_orchestrator, None)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RPA_LEAD_BUSY"


def test_list_jobs_route_returns_jobs_for_lead():
    app.dependency_overrides[deps.get_rpa_orchestrator] = lambda: _JobsOrchestrator()
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/rpa/jobs",
            headers={"Authorization": f"Bearer {settings.api_token}"},
            params={"lead_id": "lead_1", "limit": 50},
        )
    finally:
        app.dependency_overrides.pop(deps.get_rpa_orchestrator, None)

    assert response.status_code == 200
    assert response.json()[0]["job_id"] == "job_new"
    assert response.json()[0]["steps"] == ["STEP_1", "STEP_2"]

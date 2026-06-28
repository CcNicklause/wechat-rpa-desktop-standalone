from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.core.errors import AppError
from backend.app.main import app, settings


class _BusyOrchestrator:
    def add_wechat(self, lead_id, greeting, dry_run, human_approval):
        raise AppError("RPA_LEAD_BUSY", "该客户已有进行中的 RPA 任务，请勿重复触发", 409)


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

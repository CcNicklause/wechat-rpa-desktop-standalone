from backend.app.services.upstream_client import MockUpstreamClient


def test_mock_client_behavior():
    client = MockUpstreamClient()
    assert client.login() is True
    assert client.send_heartbeat("IDLE", True, {}) is True
    leads = client.fetch_leads()
    assert len(leads) == 1
    assert leads[0]["phone"] == "13800000001"
    # 第二次应该为空
    assert len(client.fetch_leads()) == 0

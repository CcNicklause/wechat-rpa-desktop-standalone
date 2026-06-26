from backend.app.services.upstream_client import MockUpstreamClient


def test_mock_client_fetch_returns_empty_when_pool_is_empty():
    client = MockUpstreamClient()
    assert client.login() is True
    assert client.send_heartbeat("IDLE", True, {}) is True
    assert client.fetch_leads() == []


def test_mock_client_seed_then_fetch_drains_pool_once():
    client = MockUpstreamClient()
    seeded = client.seed_leads([
        {
            "lead_id": "mock_seed_1",
            "phone": "13800000001",
            "customer_name": "种子1",
            "greeting": "你好",
        },
        {
            "lead_id": "mock_seed_2",
            "phone": "13800000002",
            "customer_name": "种子2",
            "greeting": "你好",
        },
    ])

    first = client.fetch_leads()
    second = client.fetch_leads()

    assert seeded == 2
    assert [item["lead_id"] for item in first] == ["mock_seed_1", "mock_seed_2"]
    assert second == []


def test_mock_client_seed_dedupes_within_same_batch():
    client = MockUpstreamClient()
    seeded = client.seed_leads([
        {"lead_id": "dup", "phone": "138", "customer_name": "A", "greeting": "g"},
        {"lead_id": "dup", "phone": "138", "customer_name": "A", "greeting": "g"},
        {"lead_id": "fresh", "phone": "139", "customer_name": "B", "greeting": "g"},
    ])

    drained = client.fetch_leads()

    assert seeded == 2
    assert [item["lead_id"] for item in drained] == ["dup", "fresh"]


def test_mock_client_report_lead_status_and_friend_check_still_succeed():
    client = MockUpstreamClient()
    assert client.report_lead_status("mock_lead_1", "REAL_SENT", "remark", None) is True
    assert client.report_friend_check("mock_lead_1", True) is True

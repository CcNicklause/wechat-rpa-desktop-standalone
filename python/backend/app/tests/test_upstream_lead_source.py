import threading

from backend.app.services.upstream_lead_source import PollingLeadSource


class FakeClient:
    def __init__(self, leads):
        self.leads = leads

    def fetch_leads(self):
        return self.leads


def test_polling_fetch_once_enqueues_each_remote_lead():
    leads = [
        {
            "lead_id": "lead_a",
            "phone": "13800000001",
            "customer_name": "张三",
            "greeting": "你好，请通过。",
        },
        {
            "lead_id": "lead_b",
            "phone": "13800000002",
            "customer_name": "李四",
            "greeting": "你好，请通过。",
        },
    ]
    enqueued = []
    logs = []
    source = PollingLeadSource(
        client=FakeClient(leads),
        enqueue_lead=lambda item: enqueued.append(item) or True,
        interval_seconds=60,
        log=logs.append,
    )

    count = source.fetch_once()

    assert count == 2
    assert [item["lead_id"] for item in enqueued] == ["lead_a", "lead_b"]
    assert logs == ["正在尝试拉取待添加线索...", "📥 成功拉取到 2 个线索"]


def test_polling_fetch_once_logs_empty_result():
    logs = []
    source = PollingLeadSource(
        client=FakeClient([]),
        enqueue_lead=lambda item: True,
        interval_seconds=60,
        log=logs.append,
    )

    count = source.fetch_once()

    assert count == 0
    assert logs == ["正在尝试拉取待添加线索...", "暂无待加微线索"]


def test_polling_run_stops_when_stop_event_is_set():
    calls = []
    stop_event = threading.Event()

    class OneShotClient:
        def fetch_leads(self):
            stop_event.set()
            return [
                {
                    "lead_id": "lead_once",
                    "phone": "13800000003",
                    "customer_name": "王五",
                    "greeting": "你好，请通过。",
                }
            ]

    source = PollingLeadSource(
        client=OneShotClient(),
        enqueue_lead=lambda item: calls.append(item["lead_id"]) or True,
        interval_seconds=60,
        log=lambda message: None,
    )

    source.run(stop_event)

    assert calls == ["lead_once"]

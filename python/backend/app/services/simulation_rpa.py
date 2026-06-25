import time
from collections.abc import Callable


SIMULATION_STEPS = [
    'validate_input: 已校验单个客户与合规确认',
    'simulate_open_wechat: 模拟定位微信窗口（未触发真实桌面操作）',
    'simulate_search_phone: 模拟搜索客户手机号/微信号',
    'simulate_type_greeting: 模拟逐字输入验证语',
    'simulate_send_request: 模拟点击发送好友申请',
    'complete: 模拟 RPA 加微流程完成',
]


def execute_simulation(update: Callable[[str], None]) -> list[str]:
    completed: list[str] = []
    for step in SIMULATION_STEPS:
        time.sleep(0.15)
        completed.append(step)
        update(step)
    return completed

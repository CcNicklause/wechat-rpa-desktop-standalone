# 微信 RPA 桌面端与上游系统对接设计规约 (2026-06-26)

本规约旨在定义桌面端自动加微工具与上游中央业务管理系统对接的技术架构、接口通信协议、后台调度队列以及前端调试交互逻辑。

---

## 1. 架构定位：混合托管模式 (Hybrid Core)

为了保证微信 RPA 任务的稳定性（防系统挂起）以及多任务执行的绝对串行性，系统采用**“前端管理凭证，后端托管调度”**的架构设计：

* **前端 (React/Tauri)**：负责登录、下发配置凭证、提供可视化的状态看板、实时日志调试控制台，以及 Mock 模式开关。
* **后端 (Python FastAPI + 守护线程)**：负责将配置持久化至本地 SQLite、维持独立的心跳线程与 RPA 串行执行队列线程、定时自动拉取并消费线索、计算防风控延迟、将执行过程通过 SSE (Server-Sent Events) 实时推送给前端。

---

## 2. API 接口定义

### 2.1 本地前后端交互 API (FastAPI 提供)

#### 1) 接收前端配置
* **接口**：`POST /api/v1/upstream/config`
* **请求体**：
  ```json
  {
    "upstream_mode": "mock", 
    "upstream_api_url": "http://localhost:8000/api/v1/upstream",
    "client_id": "client-001",
    "client_secret": "secret-xyz123"
  }
  ```
* **响应**：`{ "status": "configured", "scheduler_alive": true }`

#### 2) 获取当前配置
* **接口**：`GET /api/v1/upstream/config`
* **响应**：
  ```json
  {
    "upstream_mode": "mock",
    "upstream_api_url": "http://localhost:8000/api/v1/upstream",
    "client_id": "client-001"
  }
  ```

#### 3) 查询调度器状态
* **接口**：`GET /api/v1/upstream/status`
* **响应**：
  ```json
  {
    "scheduler_alive": true,
    "wechat_online": true,
    "state": "IDLE",            // IDLE (空闲) / BUSY (执行中) / COOLDOWN (风控冷却中)
    "queue_remaining": 0
  }
  ```

#### 4) 实时日志事件流 (SSE)
* **接口**：`GET /api/v1/upstream/logs`
* **响应头**：`Content-Type: text/event-stream`
* **消息格式**：`data: [10:30:00] 后台心跳发送成功\n\n`

#### 5) 开发调试触发器
* **接口**：`POST /api/v1/upstream/dev/trigger-fetch`
  * **作用**：立即拉取一次线索。
* **接口**：`POST /api/v1/upstream/dev/trigger-heartbeat`
  * **作用**：立即发一次心跳。
* **接口**：`POST /api/v1/upstream/dev/clear-queue`
  * **作用**：清空本地任务队列。

---

## 2.2 外部（上游）接口调用契约 (Upstream API)

无论是 Mock 模式还是 Real 模式，后端与外部系统的通信均遵循以下契约：

#### 1) 登录换取 Token
* **接口**：`POST /login`
* **请求体**：`{ "client_id": "...", "client_secret": "..." }`
* **响应**：`{ "access_token": "jwt-bearer-token-abc", "expires_in": 3600 }`

#### 2) 定时心跳
* **接口**：`POST /heartbeat`
* **请求体**：
  ```json
  {
    "client_id": "client-001",
    "status": "IDLE",              // IDLE / BUSY / COOLDOWN
    "wechat_online": true,
    "hostname": "DESKTOP-ABC",
    "ip": "192.168.1.100",
    "mac": "00:11:22:33:44:55",
    "timestamp": "2026-06-26T10:30:00Z"
  }
  ```

#### 3) 拉取线索队列
* **接口**：`GET /leads/pending`
* **响应**：
  ```json
  [
    {
      "lead_id": "lead_99217",
      "phone": "13800000000",
      "customer_name": "张三",
      "greeting": "您好，我是销售顾问，请求通过。"
    }
  ]
  ```

#### 4) 汇报 RPA 执行首期状态
* **接口**：`POST /leads/report`
* **请求体**：
  ```json
  {
    "lead_id": "lead_99217",
    "status": "REAL_SENT",       // REAL_SENT / BIZ_ALREADY_FRIEND / BIZ_TARGET_NOT_FOUND / BIZ_RISK_CONTROL
    "remark": "13800000000=张三",
    "error_details": null
  }
  ```

#### 5) 汇报对账成功（双向好友确认）
* **接口**：`POST /leads/friend-check`
* **请求体**：
  ```json
  {
    "lead_id": "lead_99217",
    "is_friend": true,
    "checked_at": "2026-06-26T10:35:00Z"
  }
  ```

---

## 3. 后端线程模型与调度机制

### 3.1 串行消费队列 (Worker Thread)
为了绝对避免微信前台窗口被两个任务并发抢占，后端维护一个线程安全的本地阻塞队列 `queue.Queue`：
1. **入队**：定时或触发从上游拉取的线索，在本地 SQLite `leads` 表中做去重落盘（确保状态同步），随后推入队列。
2. **消费**：常驻消费线程逐条取出线索，将全局状态标记为 `BUSY`，调用 RPA。
3. **完成与汇报**：RPA 拿到最终执行状态后，由消费线程调用 `report_lead_status` 接口实时汇报。
4. **风控等待**：消费线程计算防风控延迟（优先提取线索中上游配置的延迟，若无则使用本地配置的随机间隔，例如 120 ~ 300 秒），并强行 `sleep`。此时全局状态置为 `COOLDOWN`。
5. **恢复空闲**：等待结束后，状态重新置为 `IDLE`。

### 3.2 心跳发送线程 (Heartbeat Thread)
1. 独立于消费线程，确保不会因为 RPA操作的卡顿或风控挂起而阻碍心跳。
2. 每 30 秒自动运行，检测 `Weixin.exe` 进程，读取全局状态及硬件网卡信息，定时向上游发送。

---

## 4. 前端 UI 与调试卡片设计

在左侧 `Sidebar` 中新增 **“上游对接”** 导航菜单（配置路由 `/upstream`）：

1. **Card A：参数配置区**
   - 包含 Mock / Real API 的模式单选框。
   - API 地址、Client ID 和密文 Client Secret 密码框的保存和连接校验。
2. **Card B：状态监控仪表盘**
   - 四个直观指示灯/徽章：`调度服务 (Running/Stopped)`、`微信客户端 (Online/Offline)`、`机器状态 (Idle/Busy/Cooldown)`、`排队任务数`。
3. **Card C：滚动日志控制台**
   - 通过 React 连接后端的 `/api/v1/upstream/logs` 长连接。
   - 下方提供一排调试动作按钮（“触发拉取”、“强制心跳”、“清空队列”）。

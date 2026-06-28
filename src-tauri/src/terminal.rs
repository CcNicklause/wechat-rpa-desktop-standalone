// RPA 终端上报模块
//
// 设计依据：docs/tasks/rpa-terminal-reporting/plan.md
// - P0-1 心跳：Rust 侧 tokio 单例，30s 固定间隔。
// - P0-2 失败处理：record 由心跳前补 1 次；heartbeat 不退避；status/change 不重试。
// - P0-3 退出 offline：由调用方设置整体 timeout（logout 2s / app exit 1.5s）。
// - P0-4 tenant_id：仅从内存 PortalSession 读取，缺失即不发送 record/status。
// - P0-5 identity 文件：app_data_dir / terminal-identity.json，schema_version=1。

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sysinfo::System;
use tauri::{AppHandle, Manager};
use tokio::sync::Mutex as AsyncMutex;
use tokio::task::JoinHandle;
use tokio::time::interval;

const SCHEMA_VERSION: u32 = 1;
const HEARTBEAT_INTERVAL_SECS: u64 = 30;
/// record 自动补偿的最小间隔：避免心跳前每次都重试形成风暴。
const RECORD_RETRY_MIN_INTERVAL_SECS: u64 = 60;
/// heartbeat 连续失败超过此次数后日志升级。
const HEARTBEAT_ERROR_LOG_THRESHOLD: u32 = 6;

// ---------- identity 持久化 ----------

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TerminalIdentity {
    pub schema_version: u32,
    pub terminal_id: String,
    pub device_id: String,
    pub created_at: u64,
}

impl TerminalIdentity {
    fn new_random() -> Self {
        let id = uuid::Uuid::new_v4().to_string();
        Self {
            schema_version: SCHEMA_VERSION,
            terminal_id: id.clone(),
            device_id: id,
            created_at: now_seconds(),
        }
    }
}

fn now_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn identity_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|err| format!("无法定位 app data 目录: {err}"))?;
    fs::create_dir_all(&dir).map_err(|err| format!("无法创建 app data 目录: {err}"))?;
    Ok(dir.join("terminal-identity.json"))
}

/// 加载或创建 identity。
/// 解析失败 / schema 不识别：覆盖重建（本轮不做迁移）。
/// IO 失败：返回内存随机 identity 作为 fallback，调用方自行决定是否落盘。
pub fn load_or_create_identity(app: &AppHandle) -> TerminalIdentity {
    let path = match identity_path(app) {
        Ok(p) => p,
        Err(err) => {
            eprintln!("[terminal] identity_path 失败，使用内存 fallback: {err}");
            return TerminalIdentity::new_random();
        }
    };

    if path.exists() {
        match fs::read_to_string(&path) {
            Ok(content) => match serde_json::from_str::<TerminalIdentity>(&content) {
                Ok(identity) if identity.schema_version == SCHEMA_VERSION => return identity,
                Ok(identity) => {
                    eprintln!(
                        "[terminal] identity schema_version={} 不识别，覆盖重建",
                        identity.schema_version
                    );
                }
                Err(err) => {
                    eprintln!("[terminal] identity 解析失败，覆盖重建: {err}");
                }
            },
            Err(err) => {
                eprintln!("[terminal] identity 读取失败，使用内存 fallback: {err}");
                return TerminalIdentity::new_random();
            }
        }
    }

    let identity = TerminalIdentity::new_random();
    if let Ok(payload) = serde_json::to_string_pretty(&identity) {
        if let Err(err) = fs::write(&path, payload) {
            eprintln!("[terminal] identity 写盘失败，本次使用内存值: {err}");
        }
    }
    identity
}

// ---------- 设备信息采集 ----------

#[derive(Debug, Serialize, Clone)]
pub struct TerminalDeviceInfo {
    pub name: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub ip_address: String,
    pub mac_address: String,
    pub os_name: String,
    pub os_version: String,
    pub cpu_info: String,
    pub memory_gb: i32,
    pub disk_gb: i32,
    pub screen_resolution: String,
}

impl TerminalDeviceInfo {
    pub fn collect() -> Self {
        let mut sys = System::new_all();
        sys.refresh_all();

        let host = System::host_name().unwrap_or_else(|| "unknown-host".to_string());
        let os_name = System::name().unwrap_or_else(|| "Windows".to_string());
        let os_version = System::os_version().unwrap_or_else(|| "unknown".to_string());

        let cpu_info = sys
            .cpus()
            .first()
            .map(|c| format!("{} @ {}MHz x{}", c.brand().trim(), c.frequency(), sys.cpus().len()))
            .unwrap_or_else(|| "unknown".to_string());

        let memory_gb = bytes_to_gb_i32(sys.total_memory());

        let disks = sysinfo::Disks::new_with_refreshed_list();
        let disk_total: u64 = disks.iter().map(|d| d.total_space()).sum();
        let disk_gb = bytes_to_gb_i32(disk_total);

        // MAC / IP 采集尽力而为，失败填空串（P1-B）。
        let (ip, mac) = collect_ip_mac().unwrap_or_default();
        let resolution = collect_screen_resolution().unwrap_or_default();

        let kind = if cfg!(target_os = "windows") {
            "windows"
        } else if cfg!(target_os = "macos") {
            "macos"
        } else {
            "linux"
        }
        .to_string();

        Self {
            name: host,
            kind,
            ip_address: ip,
            mac_address: mac,
            os_name,
            os_version,
            cpu_info,
            memory_gb,
            disk_gb,
            screen_resolution: resolution,
        }
    }
}

fn bytes_to_gb_i32(bytes: u64) -> i32 {
    let gb = bytes / (1024 * 1024 * 1024);
    gb.try_into().unwrap_or(i32::MAX)
}

/// 通过 sysinfo::Networks 抓第一张非回环、有 MAC 的网卡。
fn collect_ip_mac() -> Option<(String, String)> {
    let networks = sysinfo::Networks::new_with_refreshed_list();
    for (name, data) in &networks {
        if name.to_lowercase().contains("loopback") {
            continue;
        }
        let mac = data.mac_address().to_string();
        if mac == "00:00:00:00:00:00" {
            continue;
        }
        let ip = data
            .ip_networks()
            .iter()
            .find(|net| net.addr.is_ipv4())
            .map(|net| net.addr.to_string())
            .unwrap_or_default();
        return Some((ip, mac));
    }
    None
}

#[cfg(target_os = "windows")]
fn collect_screen_resolution() -> Option<String> {
    // 暂用环境变量/兜底；引入 winapi 成本高，留 P1 升级。
    Some("unknown".to_string())
}

#[cfg(not(target_os = "windows"))]
fn collect_screen_resolution() -> Option<String> {
    Some("unknown".to_string())
}

// ---------- MGR 上报 client ----------

#[derive(Debug, Clone)]
pub struct MgrClient {
    base: String,
    http: reqwest::Client,
}

impl MgrClient {
    pub fn new(portal_api_base: String) -> Result<Self, String> {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(|err| format!("构建 MGR http client 失败: {err}"))?;
        Ok(Self {
            base: portal_api_base.trim_end_matches('/').to_string(),
            http,
        })
    }

    fn url(&self, path: &str) -> String {
        format!("{}/mgr/{}", self.base, path.trim_start_matches('/'))
    }

    async fn post_with_token(&self, path: &str, token: &str, body: serde_json::Value) -> Result<(), String> {
        let response = self
            .http
            .post(self.url(path))
            .bearer_auth(token)
            .json(&body)
            .send()
            .await
            .map_err(|err| format!("网络错误: {err}"))?;
        let status = response.status();
        if status.is_success() {
            return Ok(());
        }
        let text = response.text().await.unwrap_or_default();
        Err(format!("HTTP {} body={}", status.as_u16(), text))
    }

    pub async fn record(
        &self,
        token: &str,
        tenant_id: i64,
        identity: &TerminalIdentity,
        info: &TerminalDeviceInfo,
    ) -> Result<(), String> {
        let mut payload = serde_json::to_value(info)
            .map_err(|err| format!("device info 序列化失败: {err}"))?;
        if let serde_json::Value::Object(ref mut map) = payload {
            map.insert("tenantId".into(), serde_json::json!(tenant_id));
            map.insert("terminalId".into(), serde_json::json!(identity.terminal_id));
            map.insert("deviceId".into(), serde_json::json!(identity.device_id));
            // 字段名 osName/ipAddress/... 已通过 sysinfo serde rename 调整，但 i32 字段名是 snake_case，需转一下：
            // 重新映射 snake_case 到 camelCase。
            remap_snake_to_camel(map);
        }
        self.post_with_token("rpa-terminal/record", token, payload).await
    }

    pub async fn heartbeat(&self, token: &str, terminal_id: &str) -> Result<(), String> {
        self.post_with_token(
            "rpa-terminal/heartbeat",
            token,
            serde_json::json!({ "terminalId": terminal_id }),
        )
        .await
    }

    pub async fn status_change(
        &self,
        token: &str,
        tenant_id: i64,
        terminal_id: &str,
        status: &str,
        reason: &str,
    ) -> Result<(), String> {
        self.post_with_token(
            "rpa-terminal/status/change",
            token,
            serde_json::json!({
                "tenantId": tenant_id,
                "terminalId": terminal_id,
                "status": status,
                "reason": reason,
            }),
        )
        .await
    }
}

/// 把 serde 自动生成的 snake_case 字段名（ip_address/mac_address/os_name/...）
/// 改为 MGR 期望的 camelCase。type 字段已经是单词，无需转。
fn remap_snake_to_camel(map: &mut serde_json::Map<String, serde_json::Value>) {
    let mappings = [
        ("ip_address", "ipAddress"),
        ("mac_address", "macAddress"),
        ("os_name", "osName"),
        ("os_version", "osVersion"),
        ("cpu_info", "cpuInfo"),
        ("memory_gb", "memoryGb"),
        ("disk_gb", "diskGb"),
        ("screen_resolution", "screenResolution"),
    ];
    for (from, to) in mappings {
        if let Some(value) = map.remove(from) {
            map.insert(to.to_string(), value);
        }
    }
}

// ---------- 运行时状态 ----------

#[derive(Debug, Default, Clone)]
pub struct TerminalRuntimeState {
    pub last_record_ok_at: Option<u64>,
    pub last_record_error: Option<String>,
    pub last_record_attempt_at: Option<u64>,
    pub last_heartbeat_ok_at: Option<u64>,
    pub last_heartbeat_error: Option<String>,
    pub consecutive_heartbeat_failures: u32,
    pub last_status_reported: Option<String>,
}

// ---------- 管理器（单例） ----------

pub struct TerminalManager {
    pub identity: TerminalIdentity,
    client: MgrClient,
    state: AsyncMutex<TerminalRuntimeState>,
    heartbeat_task: AsyncMutex<Option<JoinHandle<()>>>,
}

impl TerminalManager {
    pub fn new(identity: TerminalIdentity, client: MgrClient) -> Self {
        Self {
            identity,
            client,
            state: AsyncMutex::new(TerminalRuntimeState::default()),
            heartbeat_task: AsyncMutex::new(None),
        }
    }

    /// 用最新的 (token, tenant_id) 做一次 record + status=online，然后启动 heartbeat。
    /// 失败不返回 Err（不阻塞登录），仅写入 runtime state。
    pub async fn initialize(self: &Arc<Self>, token: String, tenant_id: i64) {
        eprintln!(
            "[terminal] initialize 开始 tenant_id={} terminal_id={}",
            tenant_id, self.identity.terminal_id
        );
        // 1. record
        self.try_record(&token, tenant_id).await;

        // 2. status=online
        match self
            .client
            .status_change(&token, tenant_id, &self.identity.terminal_id, "online", "login")
            .await
        {
            Ok(()) => eprintln!("[terminal] status=online 上报成功 reason=login"),
            Err(err) => eprintln!("[terminal] status=online 上报失败: {err}"),
        }
        {
            let mut st = self.state.lock().await;
            st.last_status_reported = Some("online".into());
        }

        // 3. start heartbeat
        self.start_heartbeat(token.clone(), tenant_id).await;
        eprintln!(
            "[terminal] heartbeat 已启动 interval={}s",
            HEARTBEAT_INTERVAL_SECS
        );
    }

    async fn try_record(&self, token: &str, tenant_id: i64) {
        let now = now_seconds();
        {
            let mut st = self.state.lock().await;
            st.last_record_attempt_at = Some(now);
        }
        let info = TerminalDeviceInfo::collect();
        eprintln!(
            "[terminal] record 发起 tenant_id={} terminal_id={} host={}",
            tenant_id, self.identity.terminal_id, info.name
        );
        match self.client.record(token, tenant_id, &self.identity, &info).await {
            Ok(()) => {
                eprintln!(
                    "[terminal] record 成功 tenant_id={} terminal_id={}",
                    tenant_id, self.identity.terminal_id
                );
                let mut st = self.state.lock().await;
                st.last_record_ok_at = Some(now);
                st.last_record_error = None;
            }
            Err(err) => {
                eprintln!("[terminal] record 失败: {err}");
                let mut st = self.state.lock().await;
                st.last_record_error = Some(err);
            }
        }
    }

    async fn start_heartbeat(self: &Arc<Self>, token: String, tenant_id: i64) {
        // 先 abort 旧任务
        {
            let mut guard = self.heartbeat_task.lock().await;
            if let Some(handle) = guard.take() {
                handle.abort();
            }
        }

        let me = Arc::clone(self);
        let handle = tokio::spawn(async move {
            let mut ticker = interval(Duration::from_secs(HEARTBEAT_INTERVAL_SECS));
            // 首拍立刻发，方便联调观察
            ticker.tick().await;
            loop {
                ticker.tick().await;
                me.tick_once(&token, tenant_id).await;
            }
        });

        let mut guard = self.heartbeat_task.lock().await;
        *guard = Some(handle);
    }

    async fn tick_once(&self, token: &str, tenant_id: i64) {
        // 如果 record 还没成功，且距离上次尝试 ≥ RECORD_RETRY_MIN_INTERVAL_SECS，则补一次。
        let need_record_retry = {
            let st = self.state.lock().await;
            st.last_record_ok_at.is_none()
                && st
                    .last_record_attempt_at
                    .map(|t| now_seconds().saturating_sub(t) >= RECORD_RETRY_MIN_INTERVAL_SECS)
                    .unwrap_or(true)
        };
        if need_record_retry {
            self.try_record(token, tenant_id).await;
        }

        // heartbeat
        match self.client.heartbeat(token, &self.identity.terminal_id).await {
            Ok(()) => {
                eprintln!(
                    "[terminal] heartbeat 成功 terminal_id={}",
                    self.identity.terminal_id
                );
                let mut st = self.state.lock().await;
                st.last_heartbeat_ok_at = Some(now_seconds());
                st.last_heartbeat_error = None;
                st.consecutive_heartbeat_failures = 0;
            }
            Err(err) => {
                let mut st = self.state.lock().await;
                st.consecutive_heartbeat_failures = st.consecutive_heartbeat_failures.saturating_add(1);
                let level_error = st.consecutive_heartbeat_failures >= HEARTBEAT_ERROR_LOG_THRESHOLD;
                let count = st.consecutive_heartbeat_failures;
                st.last_heartbeat_error = Some(err.clone());
                drop(st);
                if level_error {
                    eprintln!(
                        "[terminal] heartbeat 连续失败 {} 次 (≥{}): {err}",
                        count, HEARTBEAT_ERROR_LOG_THRESHOLD
                    );
                } else {
                    eprintln!("[terminal] heartbeat 失败 (第 {} 次): {err}", count);
                }
            }
        }
    }

    /// 上报 offline 并 abort heartbeat。整体超时由调用方控制（tokio::time::timeout）。
    pub async fn shutdown(&self, token: String, tenant_id: i64, reason: &'static str) {
        eprintln!(
            "[terminal] shutdown 开始 reason={} terminal_id={}",
            reason, self.identity.terminal_id
        );
        match self
            .client
            .status_change(&token, tenant_id, &self.identity.terminal_id, "offline", reason)
            .await
        {
            Ok(()) => eprintln!("[terminal] status=offline 上报成功 reason={}", reason),
            Err(err) => eprintln!("[terminal] status=offline 上报失败 ({}): {}", reason, err),
        }
        {
            let mut st = self.state.lock().await;
            st.last_status_reported = Some("offline".into());
        }
        self.abort_heartbeat().await;
        eprintln!("[terminal] heartbeat 已 abort reason={}", reason);
    }

    pub async fn abort_heartbeat(&self) {
        let mut guard = self.heartbeat_task.lock().await;
        if let Some(handle) = guard.take() {
            handle.abort();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identity_round_trip() {
        let id = TerminalIdentity::new_random();
        let json = serde_json::to_string(&id).unwrap();
        let back: TerminalIdentity = serde_json::from_str(&json).unwrap();
        assert_eq!(id.schema_version, back.schema_version);
        assert_eq!(id.terminal_id, back.terminal_id);
        assert_eq!(id.device_id, back.device_id);
        assert_eq!(id.schema_version, SCHEMA_VERSION);
    }

    #[test]
    fn remap_snake_to_camel_keys() {
        let mut map = serde_json::Map::new();
        map.insert("ip_address".into(), serde_json::json!("1.2.3.4"));
        map.insert("os_name".into(), serde_json::json!("Windows"));
        map.insert("memory_gb".into(), serde_json::json!(16));
        remap_snake_to_camel(&mut map);
        assert!(map.contains_key("ipAddress"));
        assert!(map.contains_key("osName"));
        assert!(map.contains_key("memoryGb"));
        assert!(!map.contains_key("ip_address"));
    }

    #[test]
    fn device_info_collect_does_not_panic() {
        let info = TerminalDeviceInfo::collect();
        assert!(!info.os_name.is_empty());
        assert!(info.memory_gb >= 0);
    }

    #[test]
    fn bytes_to_gb_clamps_to_i32_max() {
        // 大于 i32::MAX GB 的字节数应饱和而不是 panic
        let huge = (i32::MAX as u64).saturating_mul(1024 * 1024 * 1024).saturating_add(1024 * 1024 * 1024);
        let gb = bytes_to_gb_i32(huge);
        assert!(gb >= 0);
    }
}

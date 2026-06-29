import { invoke } from "@tauri-apps/api/core";

let cachedToken: string | null = null;
let cachedApiBase: string | null = null;

export type SidecarStatus = {
  phase: "starting" | "running" | "restarting" | "failed" | "stopped" | string;
  restart_count: number;
  max_restarts: number;
  last_exit: string | null;
  api_base: string;
  log_dir: string | null;
};

async function getLocalToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  if (typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__) {
    try {
      cachedToken = await invoke<string>("get_security_token");
      return cachedToken;
    } catch (err) {
      console.warn("Using fallback security token 'dev-local-token'", err);
    }
  }
  cachedToken = "dev-local-token";
  return cachedToken;
}

// 暴露给需要直接构造请求（如 fetch-based SSE）的调用方。
// 浏览器的 EventSource 不能带 Authorization header，必须用 fetch 流式读取。
export async function getLocalApiToken(): Promise<string> {
  return getLocalToken();
}

export async function getLocalApiBase(): Promise<string> {
  if (cachedApiBase) return cachedApiBase;
  if (typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__) {
    try {
      cachedApiBase = await invoke<string>("get_local_api_base");
      return cachedApiBase;
    } catch (err) {
      console.warn("Using fallback local API base 'http://127.0.0.1:8000'", err);
    }
  }
  cachedApiBase = "http://127.0.0.1:8000";
  return cachedApiBase;
}

export async function getSidecarStatus(): Promise<SidecarStatus | null> {
  if (typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__) {
    try {
      return await invoke<SidecarStatus>("get_sidecar_status");
    } catch (err) {
      console.warn("Unable to read sidecar status", err);
    }
  }
  return null;
}

export async function requestLocalApi<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = await getLocalToken();
  const apiBase = await getLocalApiBase();
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    ...options.headers,
  };

  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    cachedToken = null;
  }

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API Error ${response.status}: ${errorText}`);
  }

  return response.json() as Promise<T>;
}

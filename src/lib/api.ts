import { invoke } from "@tauri-apps/api/core";

let cachedToken: string | null = null;

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

export const LOCAL_API_BASE = "http://127.0.0.1:8000";

export async function requestLocalApi<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = await getLocalToken();
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    ...options.headers,
  };

  const response = await fetch(`${LOCAL_API_BASE}${path}`, {
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

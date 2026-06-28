import { invoke } from '@tauri-apps/api/core';
import { create } from 'zustand';

export interface User {
  id: string;
  user_id: string;
  email?: string | null;
  phone: string;
  name: string;
  role: string;
  tenant_id: number;
}

interface PortalSession {
  access_token: string;
  user: User;
  saved_at: number;
}

interface PortalError {
  status?: number;
  code?: string;
  message?: string;
}

type AuthStatus = 'checking' | 'anonymous' | 'authenticated';

interface AuthState {
  user: User | null;
  status: AuthStatus;
  isAuthenticated: boolean;
  error: string | null;
  initialize: () => Promise<void>;
  loginPassword: (phone: string, password: string) => Promise<void>;
  loginSms: (phone: string, code: string) => Promise<void>;
  sendLoginCode: (phone: string) => Promise<void>;
  logout: () => Promise<void>;
}

function toAuthError(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const candidate = error as PortalError;
    if (candidate.message) return candidate.message;
  }
  return '登录服务暂时不可用，请稍后重试';
}

function normalizeLoginError(error: unknown): string {
  const message = toAuthError(error);
  if (message.includes('该手机号未注册')) {
    return '该手机号尚未注册，请先前往 Web Portal 完成注册';
  }
  return message;
}

/**
 * 已为当前 access_token 调用过 terminal_initialize 的标记，避免 React StrictMode
 * 或 session 恢复链路把 record/status=online 重复发到 MGR。
 * 同一 token + 同一 tenant_id 视为同一会话；token 变化（重新登录、刷新）会再次触发。
 */
let lastInitializedToken: string | null = null;

function applySession(set: (partial: Partial<AuthState>) => void, session: PortalSession) {
  set({
    user: session.user,
    status: 'authenticated',
    isAuthenticated: true,
    error: null,
  });
  // 终端上报初始化：fire-and-forget，失败不阻断登录链路。
  // 同 token 去重：StrictMode 双跑 effect / 同步登录态时不会重复打 record/status。
  if (lastInitializedToken === session.access_token) {
    return;
  }
  lastInitializedToken = session.access_token;
  void invoke('terminal_initialize', { session }).catch((error) => {
    // eslint-disable-next-line no-console
    console.warn('[terminal_initialize] 调用失败', error);
    // 失败时清掉去重标记，让下一次 applySession 可重试。
    lastInitializedToken = null;
  });
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: 'checking',
  isAuthenticated: false,
  error: null,

  initialize: async () => {
    set({ status: 'checking', error: null });
    try {
      const session = await invoke<PortalSession | null>('portal_get_session');
      if (session) {
        applySession(set, session);
        return;
      }
      set({ user: null, status: 'anonymous', isAuthenticated: false });
    } catch (error) {
      set({
        user: null,
        status: 'anonymous',
        isAuthenticated: false,
        error: toAuthError(error),
      });
    }
  },

  loginPassword: async (phone, password) => {
    set({ error: null });
    try {
      const session = await invoke<PortalSession>('portal_login_password', {
        phone,
        password,
      });
      applySession(set, session);
    } catch (error) {
      const message = normalizeLoginError(error);
      set({ error: message, user: null, status: 'anonymous', isAuthenticated: false });
      throw new Error(message);
    }
  },

  loginSms: async (phone, code) => {
    set({ error: null });
    try {
      const session = await invoke<PortalSession>('portal_login_sms', {
        phone,
        code,
      });
      applySession(set, session);
    } catch (error) {
      const message = normalizeLoginError(error);
      set({ error: message, user: null, status: 'anonymous', isAuthenticated: false });
      throw new Error(message);
    }
  },

  sendLoginCode: async (phone) => {
    set({ error: null });
    try {
      await invoke('portal_send_sms_code', { phone });
    } catch (error) {
      const message = toAuthError(error);
      set({ error: message });
      throw new Error(message);
    }
  },

  logout: async () => {
    try {
      await invoke('portal_logout');
    } finally {
      lastInitializedToken = null;
      set({ user: null, status: 'anonymous', isAuthenticated: false, error: null });
    }
  },
}));

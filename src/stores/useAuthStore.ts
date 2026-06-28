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

function applySession(set: (partial: Partial<AuthState>) => void, session: PortalSession) {
  set({
    user: session.user,
    status: 'authenticated',
    isAuthenticated: true,
    error: null,
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
      set({ user: null, status: 'anonymous', isAuthenticated: false, error: null });
    }
  },
}));

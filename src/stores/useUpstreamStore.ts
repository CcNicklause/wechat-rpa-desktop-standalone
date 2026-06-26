import { create } from 'zustand';

export interface UpstreamConfig {
  upstream_mode: 'mock' | 'real';
  upstream_api_url: string;
  client_id: string;
  client_secret: string;
}

export interface UpstreamStatus {
  scheduler_alive: boolean;
  wechat_online: boolean;
  state: 'IDLE' | 'BUSY' | 'COOLDOWN';
  queue_remaining: number;
}

interface UpstreamStoreState {
  config: UpstreamConfig;
  status: UpstreamStatus;
  logs: string[];
  isConnecting: boolean;

  // actions
  fetchConfig(): Promise<void>;
  saveConfig(cfg: Partial<UpstreamConfig>): Promise<void>;
  fetchStatus(): Promise<void>;
  triggerFetch(): Promise<void>;
  triggerHeartbeat(): Promise<void>;
  clearQueue(): Promise<void>;
  addLog(log: string): void;
  clearLogs(): void;
}

const BACKEND_URL = 'http://127.0.0.1:8000/api/v1/upstream';

export const useUpstreamStore = create<UpstreamStoreState>((set, get) => ({
  config: {
    upstream_mode: 'mock',
    upstream_api_url: '',
    client_id: '',
    client_secret: '',
  },
  status: {
    scheduler_alive: false,
    wechat_online: false,
    state: 'IDLE',
    queue_remaining: 0,
  },
  logs: [],
  isConnecting: false,

  fetchConfig: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/config`);
      if (res.ok) {
        const data = await res.json();
        set({ config: { ...get().config, ...data } });
      }
    } catch (e) {
      console.error(e);
    }
  },

  saveConfig: async (cfg) => {
    set({ isConnecting: true });
    try {
      const body = { ...get().config, ...cfg };
      const res = await fetch(`${BACKEND_URL}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const data = await res.json();
        set({
          config: body,
          status: { ...get().status, scheduler_alive: data.scheduler_alive },
        });
      }
    } catch (e) {
      console.error(e);
    } finally {
      set({ isConnecting: false });
    }
  },

  fetchStatus: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/status`);
      if (res.ok) {
        const data = await res.json();
        set({ status: data });
      }
    } catch (e) {
      // 后端未启动时静默失败
    }
  },

  triggerFetch: async () => {
    await fetch(`${BACKEND_URL}/dev/trigger-fetch`, { method: 'POST' });
  },

  triggerHeartbeat: async () => {
    await fetch(`${BACKEND_URL}/dev/trigger-heartbeat`, { method: 'POST' });
  },

  clearQueue: async () => {
    await fetch(`${BACKEND_URL}/dev/clear-queue`, { method: 'POST' });
  },

  addLog: (log) =>
    set((state) => ({
      logs: [...state.logs.slice(-199), log],
    })),

  clearLogs: () => set({ logs: [] }),
}));

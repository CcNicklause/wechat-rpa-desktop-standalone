import { create } from 'zustand';
import { requestLocalApi } from '@/lib/api';

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
      const data = await requestLocalApi<Partial<UpstreamConfig>>('/api/v1/upstream/config');
      set({ config: { ...get().config, ...data } });
    } catch (e) {
      console.error(e);
    }
  },

  saveConfig: async (cfg) => {
    set({ isConnecting: true });
    try {
      const body = { ...get().config, ...cfg };
      const data = await requestLocalApi<{ scheduler_alive: boolean }>('/api/v1/upstream/config', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      set({
        config: body,
        status: { ...get().status, scheduler_alive: data.scheduler_alive },
      });
    } catch (e) {
      console.error(e);
    } finally {
      set({ isConnecting: false });
    }
  },

  fetchStatus: async () => {
    try {
      const data = await requestLocalApi<UpstreamStatus>('/api/v1/upstream/status');
      set({ status: data });
    } catch (e) {
      // 后端未启动时静默失败
    }
  },

  triggerFetch: async () => {
    await requestLocalApi('/api/v1/upstream/dev/trigger-fetch', { method: 'POST' });
  },

  triggerHeartbeat: async () => {
    await requestLocalApi('/api/v1/upstream/dev/trigger-heartbeat', { method: 'POST' });
  },

  clearQueue: async () => {
    await requestLocalApi('/api/v1/upstream/dev/clear-queue', { method: 'POST' });
  },

  addLog: (log) =>
    set((state) => ({
      logs: [...state.logs.slice(-199), log],
    })),

  clearLogs: () => set({ logs: [] }),
}));

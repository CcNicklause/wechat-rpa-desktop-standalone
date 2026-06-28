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

  // 三个开发触发按钮都在 UI 上以 onClick 直接挂 store action，
  // 而 requestLocalApi 在非 2xx 时会抛错（比如调度器未就绪返回 400）。
  // 如果不在这里 catch，就会变成 unhandled promise rejection，
  // 用户点了按钮看不到任何反馈。统一把异常转成本地日志，让调试控制台能看到。
  triggerFetch: async () => {
    try {
      await requestLocalApi('/api/v1/upstream/dev/trigger-fetch', { method: 'POST' });
      get().addLog('[dev] trigger-fetch 已发送');
    } catch (e) {
      get().addLog(`[dev] trigger-fetch 失败: ${(e as Error).message}`);
    }
  },

  triggerHeartbeat: async () => {
    try {
      await requestLocalApi('/api/v1/upstream/dev/trigger-heartbeat', { method: 'POST' });
      get().addLog('[dev] trigger-heartbeat 已发送');
    } catch (e) {
      get().addLog(`[dev] trigger-heartbeat 失败: ${(e as Error).message}`);
    }
  },

  clearQueue: async () => {
    try {
      await requestLocalApi('/api/v1/upstream/dev/clear-queue', { method: 'POST' });
      get().addLog('[dev] clear-queue 已发送');
    } catch (e) {
      get().addLog(`[dev] clear-queue 失败: ${(e as Error).message}`);
    }
  },

  addLog: (log) =>
    set((state) => ({
      logs: [...state.logs.slice(-199), log],
    })),

  clearLogs: () => set({ logs: [] }),
}));

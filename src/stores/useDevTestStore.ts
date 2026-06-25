import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// 后端 /api/v1/rpa/jobs/:id/events SSE 推送的完整 job 形状。
// 写在 store 里是为了跨页面刷新 / Tauri webview reload 也能立刻恢复展示，
// 不必再等 SSE 重新拉一次（如果 SSE 由于服务重启已经断了，至少最后一份快照还在）。
export interface JobSnapshot {
  job_id: string;
  lead_id: string;
  status: string;
  rpa_mode: string;
  dry_run: boolean;
  steps: string[];
  error_code: string | null;
  error_message: string | null;
  outcome_type: string | null;
}

export interface DevTestFormDraft {
  phone: string;
  greeting: string;
  dryRun: boolean;
}

interface DevTestState {
  // 当前/上一次开发测试任务的 ID。null 表示没跑过。
  testJobId: string | null;
  // 该任务自动创建的 lead，用于按 lead_id 过滤审计流
  testLeadId: string | null;
  // 是否已经收到终态。终态后保留显示，不卸载日志卡片。
  jobFinished: boolean;
  // SSE 最近一次推送的完整 job 对象。reload 后即便 SSE 还没重连成功，
  // 也能立刻把上一次的步骤流水原样画出来。
  lastSnapshot: JobSnapshot | null;
  // 表单草稿，方便刷新后表单值不丢
  formDraft: DevTestFormDraft;

  // actions
  startJob(input: { jobId: string; leadId: string; form: DevTestFormDraft }): void;
  setSnapshot(snap: JobSnapshot): void;
  markFinished(): void;
  clearJob(): void;
  setFormDraft(draft: Partial<DevTestFormDraft>): void;
}

const DEFAULT_FORM: DevTestFormDraft = {
  phone: '',
  greeting: '您好，我是销售顾问，收到了您的微信申请。',
  dryRun: true,
};

export const useDevTestStore = create<DevTestState>()(
  persist(
    (set) => ({
      testJobId: null,
      testLeadId: null,
      jobFinished: false,
      lastSnapshot: null,
      formDraft: DEFAULT_FORM,

      startJob: ({ jobId, leadId, form }) =>
        set({
          testJobId: jobId,
          testLeadId: leadId,
          jobFinished: false,
          lastSnapshot: null,
          formDraft: form,
        }),

      setSnapshot: (snap) => set({ lastSnapshot: snap }),

      markFinished: () => set({ jobFinished: true }),

      clearJob: () =>
        set({
          testJobId: null,
          testLeadId: null,
          jobFinished: false,
          lastSnapshot: null,
        }),

      setFormDraft: (draft) =>
        set((state) => ({ formDraft: { ...state.formDraft, ...draft } })),
    }),
    {
      name: 'wechat_rpa_dev_test',
      // 仅持久化我们需要恢复的状态字段。SSE 句柄、网络错误等不写盘。
      partialize: (state) => ({
        testJobId: state.testJobId,
        testLeadId: state.testLeadId,
        jobFinished: state.jobFinished,
        lastSnapshot: state.lastSnapshot,
        formDraft: state.formDraft,
      }),
      version: 1,
    },
  ),
);

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { JobSnapshot } from '@/stores/useDevTestStore';

export interface JobMeta {
  jobId: string;
  leadId: string;
  lastStatus: string;
  lastTimestamp: number;
  stepCount: number;
  lastStep?: string;
  errorCode?: string;
}

interface LeadJobsState {
  // leadId -> jobIds[] 映射
  leadToJobs: Record<string, string[]>;
  // jobId -> JobMeta 缓存
  jobMeta: Record<string, JobMeta>;
  // jobId -> JobSnapshot 完整快照缓存
  snapshots: Record<string, JobSnapshot>;

  // actions
  appendJob(leadId: string, jobId: string): void;
  updateJobMeta(jobId: string, meta: Partial<JobMeta>): void;
  setSnapshot(snapshot: JobSnapshot): void;
}

// 模块级 selector 函数
const EMPTY_JOBS: JobMeta[] = [];

export function selectLeadJobs(state: LeadJobsState, leadId: string): JobMeta[] {
  if (!leadId) return EMPTY_JOBS;
  const ids = state.leadToJobs[leadId];
  if (!ids || ids.length === 0) return EMPTY_JOBS;
  return ids.map(id => state.jobMeta[id]).filter(Boolean) as JobMeta[];
}

export function selectLatestJob(state: LeadJobsState, leadId: string): JobMeta | null {
  if (!leadId) return null;
  const ids = state.leadToJobs[leadId];
  if (!ids || ids.length === 0) return null;
  return state.jobMeta[ids[0]] ?? null;
}

export function selectSnapshot(state: LeadJobsState, jobId: string): JobSnapshot | undefined {
  if (!jobId) return undefined;
  return state.snapshots[jobId];
}

// 只保留最近 5 个 job 的完整 snapshot，避免 localStorage 膨胀
const MAX_SNAPSHOTS_PER_LEAD = 5;

export function registerJobStarted(leadId: string, jobId: string): void {
  const state = useLeadJobsStore.getState();
  state.appendJob(leadId, jobId);
  state.updateJobMeta(jobId, {
    lastStatus: 'QUEUED',
    lastTimestamp: Date.now(),
    stepCount: 0,
  });
}

export const useLeadJobsStore = create<LeadJobsState>()(
  persist(
    (set) => ({
      leadToJobs: {},
      jobMeta: {},
      snapshots: {},

      appendJob: (leadId: string, jobId: string) =>
        set((state) => {
          const existingJobs = state.leadToJobs[leadId] || [];
          // 避免重复添加
          if (existingJobs.includes(jobId)) return state;

          const newJobIds = [jobId, ...existingJobs];
          const newLeadToJobs = {
            ...state.leadToJobs,
            [leadId]: newJobIds,
          };

          // 创建初始 meta
          const newJobMeta = {
            ...state.jobMeta,
            [jobId]: {
              jobId,
              leadId,
              lastStatus: 'QUEUED',
              lastTimestamp: Date.now(),
              stepCount: 0,
            },
          };

          // 清理旧 snapshot：只保留最近 MAX_SNAPSHOTS_PER_LEAD 个
          const jobIdsToKeep = newJobIds.slice(0, MAX_SNAPSHOTS_PER_LEAD);
          const newSnapshots = { ...state.snapshots };
          Object.keys(newSnapshots).forEach((id) => {
            if (!jobIdsToKeep.includes(id)) {
              delete newSnapshots[id];
            }
          });

          return {
            leadToJobs: newLeadToJobs,
            jobMeta: newJobMeta,
            snapshots: newSnapshots,
          };
        }),

      updateJobMeta: (jobId: string, meta: Partial<JobMeta>) =>
        set((state) => {
          const existing = state.jobMeta[jobId];
          if (!existing) return state;
          return {
            jobMeta: {
              ...state.jobMeta,
              [jobId]: { ...existing, ...meta },
            },
          };
        }),

      setSnapshot: (snapshot: JobSnapshot) =>
        set((state) => {
          const { job_id, lead_id, status, steps, error_code } = snapshot;

          // 确保该 job 在 leadToJobs 中有记录
          const leadJobs = state.leadToJobs[lead_id] || [];
          let newLeadToJobs = state.leadToJobs;
          if (!leadJobs.includes(job_id)) {
            newLeadToJobs = {
              ...state.leadToJobs,
              [lead_id]: [job_id, ...leadJobs],
            };
          }

          // 更新 meta
          const lastStep = steps.length > 0 ? steps[steps.length - 1] : undefined;

          const newJobMeta = {
            ...state.jobMeta,
            [job_id]: {
              jobId: job_id,
              leadId: lead_id,
              lastStatus: status,
              lastTimestamp: Date.now(),
              stepCount: steps.length,
              lastStep,
              errorCode: error_code || undefined,
            },
          };

          return {
            leadToJobs: newLeadToJobs,
            jobMeta: newJobMeta,
            snapshots: {
              ...state.snapshots,
              [job_id]: snapshot,
            },
          };
        }),
    }),
    {
      name: 'wechat_rpa_lead_jobs',
      version: 1,
    },
  ),
);

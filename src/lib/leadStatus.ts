import type { Lead } from '@/hooks/useLeads';

/** 后端 LeadStatus 枚举值（全量 15 个） */
export const LEAD_STATUS = {
  NEW_LEAD: 'NEW_LEAD',
  CALLING: 'CALLING',
  INTENT_CONFIRMED: 'INTENT_CONFIRMED',
  RPA_PENDING_APPROVAL: 'RPA_PENDING_APPROVAL',
  RPA_SIMULATED: 'RPA_SIMULATED',
  RPA_EXECUTING: 'RPA_EXECUTING',
  WECHAT_ADD_REQUESTED: 'WECHAT_ADD_REQUESTED',
  WECHAT_ACCEPTED: 'WECHAT_ACCEPTED',
  RPA_BLOCKED: 'RPA_BLOCKED',
  RPA_FAILED: 'RPA_FAILED',
  WECHAT_TARGET_NOT_FOUND: 'WECHAT_TARGET_NOT_FOUND',
  WECHAT_ALREADY_FRIEND: 'WECHAT_ALREADY_FRIEND',
  WECHAT_ADD_REJECTED: 'WECHAT_ADD_REJECTED',
  WECHAT_RISK_CONTROL: 'WECHAT_RISK_CONTROL',
  WECHAT_ACCEPTANCE_EXHAUSTED: 'WECHAT_ACCEPTANCE_EXHAUSTED',
} as const;

export type LeadStatus = (typeof LEAD_STATUS)[keyof typeof LEAD_STATUS];

/** 状态分组（与后端 stats 返回对齐） */
export const LEAD_STATUS_GROUPS = {
  SUCCESS: new Set([LEAD_STATUS.WECHAT_ACCEPTED]),
  RUNNING: new Set([
    LEAD_STATUS.CALLING,
    LEAD_STATUS.INTENT_CONFIRMED,
    LEAD_STATUS.RPA_PENDING_APPROVAL,
    LEAD_STATUS.RPA_SIMULATED,
    LEAD_STATUS.RPA_EXECUTING,
    LEAD_STATUS.WECHAT_ADD_REQUESTED,
  ]),
  FAILURE: new Set([
    LEAD_STATUS.RPA_FAILED,
    LEAD_STATUS.RPA_BLOCKED,
    LEAD_STATUS.WECHAT_RISK_CONTROL,
    LEAD_STATUS.WECHAT_ADD_REJECTED,
    LEAD_STATUS.WECHAT_TARGET_NOT_FOUND,
    LEAD_STATUS.WECHAT_ACCEPTANCE_EXHAUSTED,
  ]),
  NEUTRAL: new Set([LEAD_STATUS.NEW_LEAD, LEAD_STATUS.WECHAT_ALREADY_FRIEND]),
} as const;

/** 判定函数（纯函数，无副作用） */
export function isSuccess(status: string): boolean {
  return LEAD_STATUS_GROUPS.SUCCESS.has(status as LeadStatus);
}

export function isRunning(status: string): boolean {
  return LEAD_STATUS_GROUPS.RUNNING.has(status as LeadStatus);
}

export function isFailure(status: string): boolean {
  return LEAD_STATUS_GROUPS.FAILURE.has(status as LeadStatus);
}

export function isNeutral(status: string): boolean {
  return LEAD_STATUS_GROUPS.NEUTRAL.has(status as LeadStatus);
}

/** 统计一组 leads */
export function countLeadsByStatus(leads: Pick<Lead, 'status'>[]): {
  success: number;
  running: number;
  failure: number;
  total: number;
} {
  let success = 0;
  let running = 0;
  let failure = 0;
  for (const lead of leads) {
    const status = lead.status;
    if (isSuccess(status)) success++;
    else if (isRunning(status)) running++;
    else if (isFailure(status)) failure++;
    // NEUTRAL 不计入统计值，仅计入总数
  }
  return { success, running, failure, total: leads.length };
}

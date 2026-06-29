const STATUS_LABELS: Record<string, string> = {
  success: '成功',
  started: '已开始',
  approved: '已确认',
  accepted: '已接受',
  completed: '已完成',
  pending: '等待中',
  queued: '排队中',
  business_outcome: '业务结果',
  failed: '失败',
  blocked: '已阻断',

  QUEUED: '排队中',
  REAL_QUEUED: '排队中',
  REAL_RUNNING: '执行中',
  SIMULATION_QUEUED: '模拟排队',
  SIMULATION_RUNNING: '模拟执行中',
  SIMULATION_COMPLETED: '模拟完成',
  REAL_COMPLETED: '执行完成',
  FAILED: '失败',
  ERROR: '异常',

  NEW_LEAD: '新线索',
  CALLING: '沟通中',
  INTENT_CONFIRMED: '意向确认',
  RPA_PENDING_APPROVAL: '待确认',
  RPA_SIMULATED: '模拟完成',
  RPA_EXECUTING: '执行中',
  WECHAT_ADD_REQUESTED: '已发送申请',
  WECHAT_ACCEPTED: '已添加',
  RPA_BLOCKED: '加微受阻',
  RPA_FAILED: '执行失败',
  WECHAT_TARGET_NOT_FOUND: '未找到账号',
  WECHAT_ALREADY_FRIEND: '已是好友',
  WECHAT_ADD_REJECTED: '对方拒绝',
  WECHAT_RISK_CONTROL: '风控限制',
  WECHAT_ACCEPTANCE_EXHAUSTED: '复查已停止',

  IDLE: '空闲',
  BUSY: '忙碌',
  COOLDOWN: '冷却中',
  PENDING: '待发送',
  SENT: '已发送',

  TARGET_NOT_FOUND: '未找到账号',
  ALREADY_FRIEND: '已是好友',
  ALREADY_ACCEPTED: '已接受',
  WECHAT_ADDED: '已添加',
};

export function statusDisplayLabel(status?: string | null): string {
  if (!status) return '-';
  const direct = STATUS_LABELS[status];
  if (direct) return direct;
  if (status.startsWith('REAL_BIZ_')) {
    if (status === 'REAL_BIZ_ALREADY_FRIEND') return '已是好友';
    if (status === 'REAL_BIZ_TARGET_NOT_FOUND') return '未找到账号';
    if (status === 'REAL_BIZ_ADD_REJECTED') return '对方拒绝';
    if (status === 'REAL_BIZ_RISK_CONTROL') return '风控限制';
    return '业务结果';
  }
  return status;
}

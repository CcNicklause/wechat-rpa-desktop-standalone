import { Badge, type BadgeProps } from '../ui/badge';

type BadgeVariant = NonNullable<BadgeProps['variant']>;

interface StatusBadgeProps {
  status?: string | null;
  label?: string;
  className?: string;
  showDot?: boolean;
}

// 单一映射：状态字符串 → Badge variant。
// 覆盖范围：
// - 审计 result：success/started/approved/pending/failed/queued/accepted/business_outcome/blocked
//   （见 python/backend/app/services/*.py）
// - LeadStatus 全部值（见 python/backend/app/schemas/lead.py）
// - RPA job status：QUEUED / REAL_RUNNING / SIMULATION_RUNNING / *_COMPLETED / FAILED / REAL_BIZ_*
// - 上游调度器 state：IDLE / BUSY / COOLDOWN
// - 好友对账上报 outbox status：PENDING / SENT / FAILED
const STATUS_VARIANT: Record<string, BadgeVariant> = {
  // 审计 result（小写）
  success: 'success',
  started: 'success',
  approved: 'success',
  accepted: 'success',
  completed: 'success',
  pending: 'pending',
  queued: 'pending',
  business_outcome: 'secondary',
  failed: 'failed',
  blocked: 'failed',

  // RPA job status
  QUEUED: 'pending',
  REAL_QUEUED: 'pending',
  REAL_RUNNING: 'pending',
  SIMULATION_QUEUED: 'pending',
  SIMULATION_RUNNING: 'pending',
  SIMULATION_COMPLETED: 'success',
  REAL_COMPLETED: 'success',
  FAILED: 'failed',
  RPA_FAILED: 'failed',
  ERROR: 'failed',

  // LeadStatus（python/backend/app/schemas/lead.py）
  NEW_LEAD: 'secondary',
  CALLING: 'pending',
  INTENT_CONFIRMED: 'secondary',
  RPA_PENDING_APPROVAL: 'secondary',
  RPA_SIMULATED: 'success',
  RPA_EXECUTING: 'pending',
  WECHAT_ADD_REQUESTED: 'pending',
  WECHAT_ACCEPTED: 'success',
  RPA_BLOCKED: 'failed',
  WECHAT_TARGET_NOT_FOUND: 'failed',
  WECHAT_ALREADY_FRIEND: 'success',
  WECHAT_ADD_REJECTED: 'failed',
  WECHAT_RISK_CONTROL: 'failed',

  // 上游调度器 state
  IDLE: 'success',
  BUSY: 'pending',
  COOLDOWN: 'secondary',

  // 好友对账 outbox
  PENDING: 'pending',
  SENT: 'success',

  // 旧版兼容（少量历史调用方）
  TARGET_NOT_FOUND: 'failed',
  ALREADY_FRIEND: 'success',
  ALREADY_ACCEPTED: 'success',
  WECHAT_ADDED: 'success',
};

// REAL_BIZ_* 是 RPA 业务终态前缀（REAL_BIZ_TARGET_NOT_FOUND / ALREADY_FRIEND / ADD_REJECTED / RISK_CONTROL）。
// 终态而非进行中，统一走 secondary（中性）而不是 pending（在途/动效）。
export function statusBadgeVariant(status?: string | null): BadgeVariant {
  if (!status) return 'outline';
  const direct = STATUS_VARIANT[status];
  if (direct) return direct;
  if (status.startsWith('REAL_BIZ_')) {
    if (status === 'REAL_BIZ_ALREADY_FRIEND') return 'success';
    return 'secondary';
  }
  return 'outline';
}

export function StatusBadge({
  status,
  label,
  className,
  showDot = false,
}: StatusBadgeProps) {
  // 使用 || 而不是 ??：空字符串也应该回退到 status / '-'，避免渲染空 Badge。
  const display = label || status || '-';

  return (
    <Badge variant={statusBadgeVariant(status)} className={className} showDot={showDot}>
      {display}
    </Badge>
  );
}

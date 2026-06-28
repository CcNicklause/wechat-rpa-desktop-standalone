import { Badge, type BadgeProps } from '@/components/ui/badge';

type BadgeVariant = NonNullable<BadgeProps['variant']>;

interface StatusBadgeProps {
  status?: string | null;
  label?: string;
  className?: string;
  showDot?: boolean;
}

const SUCCESS_STATUSES = new Set([
  'success',
  'started',
  'approved',
  'completed',
  'SIMULATION_COMPLETED',
  'REAL_COMPLETED',
  'IDLE',
  'SENT',
  'ALREADY_ACCEPTED',
  'ALREADY_FRIEND',
  'WECHAT_ACCEPTED',
]);

const FAILED_STATUSES = new Set([
  'failed',
  'FAILED',
  'RPA_FAILED',
  'ERROR',
  'TARGET_NOT_FOUND',
]);

const PENDING_STATUSES = new Set([
  'pending',
  'PENDING',
  'BUSY',
  'QUEUED',
  'REAL_QUEUED',
  'REAL_RUNNING',
  'SIMULATION_QUEUED',
  'SIMULATION_RUNNING',
  'RPA_EXECUTING',
  'WECHAT_ADD_REQUESTED',
]);

const SECONDARY_STATUSES = new Set([
  'COOLDOWN',
  'NEW_LEAD',
  'INTENT_CONFIRMED',
  'RPA_PENDING_APPROVAL',
]);

export function statusBadgeVariant(status?: string | null): BadgeVariant {
  if (!status) return 'outline';
  if (SUCCESS_STATUSES.has(status)) return 'success';
  if (FAILED_STATUSES.has(status)) return 'failed';
  if (PENDING_STATUSES.has(status)) return 'pending';
  if (SECONDARY_STATUSES.has(status)) return 'secondary';
  if (status.startsWith('REAL_BIZ_')) return 'pending';
  return 'outline';
}

export function StatusBadge({
  status,
  label,
  className,
  showDot = false,
}: StatusBadgeProps) {
  const display = label ?? status ?? '-';

  return (
    <Badge variant={statusBadgeVariant(status)} className={className} showDot={showDot}>
      {display}
    </Badge>
  );
}

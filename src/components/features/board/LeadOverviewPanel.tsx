import type { ReactNode } from 'react';
import { StatusBadge } from '@/components/common/StatusBadge';
import { Lead } from '@/hooks/useLeads';
import type { JobMeta } from '@/hooks/useLeadJobs';
import { getLeadDisplay } from '@/lib/leadDisplay';
import { leadVerificationText } from '@/lib/leadOverviewCopy';
import { statusDisplayLabel } from '@/lib/statusDisplay';
import { cn } from '@/lib/utils';

interface LeadOverviewPanelProps {
  lead: Lead | null;
  latestJob: JobMeta | null;
  className?: string;
}

export function LeadOverviewPanel({ lead, latestJob, className }: LeadOverviewPanelProps) {
  if (!lead) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-muted-foreground text-sm', className)}>
        请选择一个线索查看概览
      </div>
    );
  }

  const display = getLeadDisplay(lead);

  return (
    <div className={cn('space-y-5 text-sm', className)}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <InfoBlock label="目标账号" value={display.account} mono />
        <InfoBlock label="当前状态" value={<StatusBadge status={lead.status} showDot />} />
        <InfoBlock label="备注" value={display.remark || '暂无备注'} />
        <InfoBlock label="验证语" value={leadVerificationText(lead)} />
        <InfoBlock
          label="最近执行"
          value={latestJob ? statusDisplayLabel(latestJob.lastStatus) : '暂无执行记录'}
        />
      </div>

      <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2">
        <p className="text-xs font-semibold text-foreground">下一步建议</p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          {nextActionText(lead.status, latestJob)}
        </p>
      </div>

      {latestJob?.lastStep && (
        <div className="rounded-lg border border-border p-3 space-y-2">
          <p className="text-xs font-semibold text-foreground">最近进展</p>
          <p className="text-xs text-muted-foreground leading-relaxed break-all">{latestJob.lastStep}</p>
        </div>
      )}
    </div>
  );
}

function InfoBlock({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border p-3 min-w-0">
      <p className="text-[11px] text-muted-foreground mb-1">{label}</p>
      <div className={cn('text-sm font-medium text-foreground truncate', mono && 'font-mono')}>{value}</div>
    </div>
  );
}

function nextActionText(status: string, latestJob: JobMeta | null): string {
  if (status === 'WECHAT_ACCEPTED' || status === 'WECHAT_ALREADY_FRIEND') {
    return '线索已完成加友，无需继续执行。';
  }
  if (status === 'RPA_BLOCKED' || status === 'WECHAT_RISK_CONTROL') {
    return '当前链路受阻，建议先检查风控或客户端状态，再决定是否重试。';
  }
  if (status === 'RPA_FAILED') {
    return '最近执行失败，建议查看过程并确认失败原因后再重跑。';
  }
  if (!latestJob) {
    return '暂无执行记录，可在确认信息无误后发起加微。';
  }
  return '可查看过程了解最近执行进展。';
}

import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/common/StatusBadge';
import { Lead } from '@/hooks/useLeads';
import { getLeadDisplay } from '@/lib/leadDisplay';
import { cn } from '@/lib/utils';

interface LeadHeaderProps {
  lead: Lead | null;
  onTriggerJob?: (leadId: string) => void;
  className?: string;
}

export function LeadHeader({ lead, onTriggerJob, className }: LeadHeaderProps) {
  if (!lead) return null;

  const display = getLeadDisplay(lead);

  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="space-y-1 min-w-0">
        <h2 className="text-lg font-semibold text-foreground font-mono truncate">{display.account}</h2>
        {display.remark && (
          <p className="text-xs text-muted-foreground truncate">备注：{display.remark}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <StatusBadge status={lead.status} showDot />
        {onTriggerJob && (
          <Button
            size="sm"
            onClick={() => onTriggerJob(lead.id)}
          >
            重跑
          </Button>
        )}
      </div>
    </div>
  );
}

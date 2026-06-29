import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/common/StatusBadge';
import { Lead } from '@/hooks/useLeads';

interface LeadHeaderProps {
  lead: Lead | null;
  onTriggerJob: (leadId: string) => void;
  className?: string;
}

export function LeadHeader({ lead, onTriggerJob, className }: LeadHeaderProps) {
  if (!lead) return null;

  return (
    <div className={cn('flex items-center justify-between', className)}>
      <div className="space-y-1">
        <h2 className="text-lg font-semibold text-foreground">{lead.name}</h2>
        <p className="text-xs text-muted-foreground font-mono">{lead.phone}</p>
      </div>
      <div className="flex items-center gap-3">
        <StatusBadge status={lead.status} showDot />
        <Button
          size="sm"
          onClick={() => onTriggerJob(lead.id)}
        >
          重跑
        </Button>
      </div>
    </div>
  );
}

import { cn } from '@/lib/utils';

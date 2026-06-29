import { AuditLog, maskPhone, useLeadAudits } from '@/hooks/useAudits';
import { Lead } from '@/hooks/useLeads';
import { AuditList } from './AuditList';

interface LeadTimelinePanelProps {
  lead: Lead | null;
  audits: AuditLog[];
  className?: string;
}

export function LeadTimelinePanel({ lead, audits, className }: LeadTimelinePanelProps) {
  const filteredAudits = useLeadAudits(audits, lead?.phone || '');

  if (!lead) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-muted-foreground text-sm', className)}>
        请选择一个线索查看审计记录
      </div>
    );
  }

  return (
    <div className={cn('flex flex-col h-full', className)}>
      <AuditList audits={filteredAudits} />
    </div>
  );
}

import { cn } from '@/lib/utils';

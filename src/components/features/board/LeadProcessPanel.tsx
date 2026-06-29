import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';
import { LeadStepsPanel } from './LeadStepsPanel';
import { LeadTimelinePanel } from './LeadTimelinePanel';
import { cn } from '@/lib/utils';

interface LeadProcessPanelProps {
  lead: Lead | null;
  audits: AuditLog[];
  jobId: string | null;
  className?: string;
}

export function LeadProcessPanel({ lead, audits, jobId, className }: LeadProcessPanelProps) {
  return (
    <div className={cn('flex flex-col gap-4 h-full min-h-0', className)}>
      <section className="min-h-[160px] max-h-[240px] overflow-hidden">
        <SectionTitle title="关键日志" />
        <div className="h-[calc(100%-24px)] overflow-hidden">
          <LeadTimelinePanel lead={lead} audits={audits} />
        </div>
      </section>

      <section className="flex-1 min-h-0">
        <SectionTitle title="执行步骤" />
        <LeadStepsPanel jobId={jobId} className="h-[calc(100%-24px)]" />
      </section>
    </div>
  );
}

function SectionTitle({ title }: { title: string }) {
  return <h3 className="text-xs font-semibold text-foreground mb-2">{title}</h3>;
}

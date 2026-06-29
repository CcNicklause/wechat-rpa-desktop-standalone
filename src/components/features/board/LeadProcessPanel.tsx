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
    <div className={cn('space-y-5 pb-2', className)}>
      <section className="min-w-0">
        <SectionTitle title="关键日志" />
        <div className="min-w-0">
          <LeadTimelinePanel lead={lead} audits={audits} />
        </div>
      </section>

      <section className="min-w-0">
        <SectionTitle title="执行步骤" />
        <LeadStepsPanel jobId={jobId} />
      </section>
    </div>
  );
}

function SectionTitle({ title }: { title: string }) {
  return <h3 className="text-xs font-semibold text-foreground mb-2">{title}</h3>;
}

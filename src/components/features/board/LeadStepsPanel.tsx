import { StatusBadge } from '@/components/common/StatusBadge';
import { useJobSnapshot, TERMINAL_STATUSES } from '@/hooks/useJobSnapshot';
import { useLeadJobsStore } from '@/hooks/useLeadJobs';
import { JobStepsView } from './JobStepsView';
import { cn } from '@/lib/utils';

interface LeadStepsPanelProps {
  jobId: string | null;
  className?: string;
}

export function LeadStepsPanel({ jobId, className }: LeadStepsPanelProps) {
  const { snapshot, error, isTerminal } = useJobSnapshot(jobId);
  const jobMeta = useLeadJobsStore((s) => jobId ? s.jobMeta[jobId] : null);

  if (!jobId) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-muted-foreground text-sm', className)}>
        请选择一个任务查看步骤
      </div>
    );
  }

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[10px] text-muted-foreground font-mono">
            {jobId.slice(0, 12)}...
          </span>
          {!isTerminal && (
            <span className="relative inline-flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
            </span>
          )}
        </div>
        {snapshot && <StatusBadge status={snapshot.status} />}
      </div>

      <JobStepsView snapshot={snapshot} error={error} className="flex-1" />

      {snapshot && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted-foreground">
          <span>
            共 {snapshot.steps.length} 步 · {snapshot.rpa_mode === 'real' ? '真实模式' : '模拟模式'}
          </span>
          <span className="break-all font-semibold text-foreground">{snapshot.status}</span>
        </div>
      )}
    </div>
  );
}

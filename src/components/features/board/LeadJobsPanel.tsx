import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/common/StatusBadge';
import { useLeadJobsStore, selectLeadJobs, type JobMeta } from '@/hooks/useLeadJobs';
import { useShallow } from 'zustand/react/shallow';
import { cn } from '@/lib/utils';

interface LeadJobsPanelProps {
  leadId: string;
  selectedJobId: string | null;
  onSelectJob: (jobId: string) => void;
  className?: string;
}

export function LeadJobsPanel({ leadId, selectedJobId, onSelectJob, className }: LeadJobsPanelProps) {
  const jobs = useLeadJobsStore(useShallow((s) => selectLeadJobs(s, leadId)));

  if (jobs.length === 0) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-muted-foreground text-sm', className)}>
        暂无历史执行记录
      </div>
    );
  }

  return (
    <div className={cn('space-y-2', className)}>
      {jobs.map((job) => (
        <div
          key={job.jobId}
          className={cn(
            'p-3 rounded-lg border transition-colors cursor-pointer',
            selectedJobId === job.jobId
              ? 'border-primary bg-primary/5'
              : 'border-border hover:bg-muted/50'
          )}
          onClick={() => onSelectJob(job.jobId)}
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] font-mono text-muted-foreground">
              {job.jobId.slice(0, 12)}...
            </span>
            <StatusBadge status={job.lastStatus} />
          </div>
          {job.lastStep && (
            <p className="text-[10px] text-muted-foreground truncate">
              {job.lastStep}
            </p>
          )}
          <div className="flex items-center justify-between mt-1 text-[9px] text-muted-foreground">
            <span>{new Date(job.lastTimestamp).toLocaleString()}</span>
            <span>{job.stepCount} 步</span>
          </div>
        </div>
      ))}
    </div>
  );
}

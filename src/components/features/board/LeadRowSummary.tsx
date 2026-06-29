import { useLeadJobsStore, selectLatestJob, type JobMeta } from '@/hooks/useLeadJobs';
import { cn } from '@/lib/utils';

interface LeadRowSummaryProps {
  leadId: number;
  className?: string;
}

export function LeadRowSummary({ leadId, className }: LeadRowSummaryProps) {
  const latestJob = useLeadJobsStore((s) => selectLatestJob(s, String(leadId)));

  if (!latestJob) return null;

  // 计算重试次数
  const retryCount = extractRetryCount(latestJob);

  return (
    <p className={cn('text-[9px] text-muted-foreground', className)}>
      {latestJob.lastStep && (
        <span className="truncate max-w-[200px] inline-block">
          {latestJob.lastStep}
        </span>
      )}
      {retryCount > 0 && (
        <span className="ml-2 text-amber-600">
          ({retryCount} 次重试)
        </span>
      )}
    </p>
  );
}

function extractRetryCount(job: JobMeta): number {
  if (!job.lastStep) return 0;
  // 简单实现：从 lastStep 中查找重试相关的关键字
  // 后续可以优化为从完整 snapshot 的 steps 中统计
  const retryKeywords = ['SYS_ERROR_RETRY', 'RETRY'];
  let count = 0;
  for (const keyword of retryKeywords) {
    if (job.lastStep.includes(keyword)) {
      count++;
    }
  }
  return count;
}

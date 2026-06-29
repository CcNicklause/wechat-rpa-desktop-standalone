import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useLeadJobsStore, selectSnapshot } from '@/hooks/useLeadJobs';
import { cn } from '@/lib/utils';

interface LeadRawPanelProps {
  jobId: string | null;
  className?: string;
}

export function LeadRawPanel({ jobId, className }: LeadRawPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const snapshot = useLeadJobsStore((s) => selectSnapshot(s, jobId));

  if (!jobId) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-muted-foreground text-sm', className)}>
        请选择一个任务查看原始数据
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className={cn('flex items-center justify-center h-32 text-muted-foreground text-sm', className)}>
        暂无快照数据
      </div>
    );
  }

  const rawJson = JSON.stringify(snapshot, null, 2);

  return (
    <div className={cn('flex flex-col h-full', className)}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] text-muted-foreground font-mono">
          {jobId.slice(0, 12)}... 原始数据
        </span>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? '收起' : '展开'}
        </Button>
      </div>

      <div className="flex-1 overflow-auto">
        <pre className={cn(
          'text-[10px] font-mono bg-muted/30 p-3 rounded-lg border border-border',
          !expanded && 'line-clamp-20'
        )}>
          {rawJson}
        </pre>
      </div>
    </div>
  );
}

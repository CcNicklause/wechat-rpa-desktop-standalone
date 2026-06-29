import { useEffect, useRef } from 'react';
import { StatusBadge } from '@/components/common/StatusBadge';
import { useJobSnapshot, TERMINAL_STATUSES } from '@/hooks/useJobSnapshot';
import { JobStepsView } from './board/JobStepsView';

interface JobProgressProps {
  jobId: string;
  onComplete: () => void;
}

export function JobProgress({ jobId, onComplete }: JobProgressProps) {
  const { snapshot, error, isTerminal } = useJobSnapshot(jobId, { onComplete });
  const stepListRef = useRef<HTMLDivElement | null>(null);

  // 自动滚动到最新一步
  useEffect(() => {
    const el = stepListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [snapshot?.steps?.length]);

  const steps = snapshot?.steps ?? [];
  const status = snapshot?.status ?? 'QUEUED';
  const finished = isTerminal;

  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm space-y-3 flex flex-col flex-1 min-h-0">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-xs text-foreground tracking-wider">
          {finished ? '✅ RPA 任务流水' : '⚡ RPA 引擎运行中'}
        </h3>
        <div className="flex items-center gap-2">
          <StatusBadge status={status} />
          {!finished && (
            <span className="relative inline-flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
            </span>
          )}
        </div>
      </div>

      <div className="text-[10px] text-muted-foreground flex justify-between font-mono">
        <span>任务ID</span>
        <span>{jobId.slice(0, 12)}…</span>
      </div>

      <JobStepsView snapshot={snapshot} error={error} />

      {finished && (
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>
            共 {steps.length} 步 · {snapshot?.rpa_mode === 'real' ? '真实模式' : '模拟模式'}
          </span>
          <span className="font-semibold text-foreground">{status}</span>
        </div>
      )}
    </div>
  );
}

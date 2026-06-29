import { type JobSnapshot } from '@/stores/useDevTestStore';

interface JobStepsViewProps {
  snapshot: JobSnapshot | null;
  error: string | null;
  className?: string;
}

export function JobStepsView({ snapshot, error, className }: JobStepsViewProps) {
  const steps = snapshot?.steps ?? [];

  return (
    <div className={cn('flex flex-col flex-1 min-h-0', className)}>
      {snapshot?.error_code && (
        <div className="border border-rose-500/40 bg-rose-500/10 text-rose-600 rounded-lg p-2 text-[11px] space-y-0.5 mb-2">
          <p className="font-semibold">❌ {snapshot.error_code}</p>
          {snapshot.error_message && <p className="leading-snug">{snapshot.error_message}</p>}
        </div>
      )}

      {error && (
        <div className="border border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400 rounded-lg p-2 text-[10.5px] mb-2">
          ⚠️ 事件流断开：{error}（已根据上次快照展示）
        </div>
      )}

      <div className="flex-1 overflow-y-auto border border-border rounded-lg bg-muted/20 p-2 space-y-1 text-[10.5px] leading-relaxed font-mono">
        {steps.length === 0 ? (
          <p className="text-muted-foreground text-center py-4">等待第一条 step…</p>
        ) : (
          steps.map((step, idx) => <StepLine key={`${idx}-${step.slice(0, 24)}`} index={idx} step={step} />)
        )}
      </div>
    </div>
  );
}

// 单条 step 行，按前缀染色
function StepLine({ index, step }: { index: number; step: string }) {
  const tone = stepTone(step);
  const colonAt = step.indexOf(':');
  const tag = colonAt > 0 ? step.slice(0, colonAt) : '';
  const text = colonAt > 0 ? step.slice(colonAt + 1).trim() : step;
  const palette = STEP_TONE_PALETTE[tone];

  return (
    <div className={`flex gap-2 items-start ${palette.row}`}>
      <span className="text-muted-foreground select-none w-5 text-right shrink-0">{index + 1}.</span>
      {tag ? (
        <>
          <span className={`px-1.5 py-px rounded text-[9.5px] font-bold shrink-0 ${palette.tag}`}>{tag}</span>
          <span className="break-all">{text}</span>
        </>
      ) : (
        <span className="break-all">{text}</span>
      )}
    </div>
  );
}

type StepTone = 'success' | 'fail' | 'warn' | 'default';

const STEP_TONE_PALETTE: Record<StepTone, { row: string; tag: string }> = {
  success: {
    row: 'text-emerald-700 dark:text-emerald-400',
    tag: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
  },
  fail: {
    row: 'text-rose-600 dark:text-rose-400',
    tag: 'bg-rose-500/15 text-rose-600 dark:text-rose-400',
  },
  warn: {
    row: 'text-amber-600 dark:text-amber-400',
    tag: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
  },
  default: {
    row: 'text-foreground/80',
    tag: 'bg-muted text-muted-foreground',
  },
};

function stepTone(step: string): StepTone {
  if (/^(SYS_ERROR_RETRY|SYS_RPA_TIMEOUT|.*_NOT_FOUND|.*_MISS|.*_BLOCKED|.*_RISK|.*_REJECT|.*_FAILED)/i.test(step)) {
    if (/^.*_NOT_FOUND/i.test(step) && !/SYS_ERROR_RETRY/i.test(step)) return 'fail';
    if (/SYS_ERROR_RETRY|SYS_RPA_TIMEOUT|.*_BLOCKED|.*_RISK|.*_REJECT|.*_FAILED/i.test(step)) return 'fail';
    return 'warn';
  }
  if (/(_COMPLETED|_OK|_FOUND|_HIT|_CONFIRMED|_OPENED|_FILLED|_TYPED|_CLICKED|ACCEPTED)/i.test(step)) {
    return 'success';
  }
  if (/(safety_delay|POST_PASTE_WAIT|CLEANUP_)/i.test(step)) return 'warn';
  return 'default';
}

import { cn } from '@/lib/utils';

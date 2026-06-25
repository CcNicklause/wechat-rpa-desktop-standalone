import { useEffect, useRef, useState } from 'react';
import { useDevTestStore, type JobSnapshot } from '@/stores/useDevTestStore';
import { getLocalApiToken, LOCAL_API_BASE, requestLocalApi } from '@/lib/api';

interface JobProgressProps {
  jobId: string;
  onComplete: () => void;
}

const TERMINAL_STATUSES = new Set([
  'SIMULATION_COMPLETED',
  'REAL_COMPLETED',
  'FAILED',
  // 业务终态（rpa_orchestrator._finalize_business_outcome）
  'REAL_BIZ_TARGET_NOT_FOUND',
  'REAL_BIZ_ALREADY_FRIEND',
  'REAL_BIZ_ADD_REJECTED',
  'REAL_BIZ_RISK_CONTROL',
]);

export function JobProgress({ jobId, onComplete }: JobProgressProps) {
  // 直接从 store 读上一次的快照——这样即便组件因为 Tauri webview 刷新而重挂载，
  // localStorage 里的快照能立刻把整条流水画出来，不用等 SSE 重新拉一遍。
  const snapshot = useDevTestStore((s) =>
    s.lastSnapshot && s.lastSnapshot.job_id === jobId ? s.lastSnapshot : null,
  );
  const setSnapshot = useDevTestStore((s) => s.setSnapshot);

  const stepListRef = useRef<HTMLDivElement | null>(null);
  // 避免一次任务里反复触发 onComplete（SSE 终态会持续把同一份 payload 推过来）
  const completedRef = useRef(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  useEffect(() => {
    completedRef.current = false;
    setStreamError(null);

    // 浏览器 EventSource 不能带 Authorization header，而后端 /api/v1/rpa 强制 Bearer 鉴权
    // (rpa.py:12 -> require_auth)。所以原来直接 new EventSource 会被 401 拒绝，永远
    // 收不到 onmessage，UI 卡在"等待第一条 step…"。
    // 这里改用 fetch + ReadableStream 手动解 SSE 帧，并在 header 里带上本地 token。
    const controller = new AbortController();

    // 1) 先做一次"现状兜底"：即便任务已经跑完（甚至刚刚跑完、SSE 流刚好被服务端关闭），
    //    也能立刻把当前 job 完整 steps 列出来，不用空等 SSE 第一条。
    let cancelled = false;
    void (async () => {
      try {
        const initial = await requestLocalApi<JobSnapshot>(`/api/v1/rpa/jobs/${jobId}`);
        if (cancelled) return;
        setSnapshot(initial);
        if (TERMINAL_STATUSES.has(initial.status) && !completedRef.current) {
          completedRef.current = true;
          onComplete();
        }
      } catch (err: any) {
        // 兜底失败不要影响 SSE 主路；只在 SSE 也失败时再显示。
        console.warn('JobProgress: failed to fetch initial snapshot', err);
      }
    })();

    // 2) 真正的事件流。fetch+token 模式：
    void (async () => {
      try {
        const token = await getLocalApiToken();
        const response = await fetch(`${LOCAL_API_BASE}/api/v1/rpa/jobs/${jobId}/events`, {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'text/event-stream',
          },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`SSE HTTP ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // SSE 帧用空行分隔（rpa.py 里 `f'data: {payload}\n\n'`）。
          let sepIndex: number;
          while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sepIndex);
            buffer = buffer.slice(sepIndex + 2);
            // 一帧里可能有多行 `data: ...`，按 SSE 规范合并；这里后端始终单行 data，
            // 但稳妥起见还是做一遍合并。
            const dataLines = frame
              .split('\n')
              .filter((line) => line.startsWith('data:'))
              .map((line) => line.replace(/^data:\s?/, ''));
            if (!dataLines.length) continue;
            const payload = dataLines.join('\n');
            try {
              const parsed = JSON.parse(payload) as JobSnapshot;
              setSnapshot(parsed);
              if (TERMINAL_STATUSES.has(parsed.status) && !completedRef.current) {
                completedRef.current = true;
                onComplete();
              }
            } catch (err) {
              console.warn('JobProgress: bad SSE frame', payload, err);
            }
          }
        }
      } catch (err: any) {
        if (controller.signal.aborted) return;
        const msg = err?.message || String(err);
        // 用 store 里的快照判定：已经完成的任务流断开属于"正常关闭"，不算错误。
        if (!completedRef.current) {
          setStreamError(msg);
        }
      } finally {
        if (!completedRef.current) {
          completedRef.current = true;
          onComplete();
        }
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [jobId, onComplete, setSnapshot]);

  // 自动滚动到最新一步
  useEffect(() => {
    const el = stepListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [snapshot?.steps?.length]);

  const steps = snapshot?.steps ?? [];
  const status = snapshot?.status ?? 'QUEUED';
  const finished = TERMINAL_STATUSES.has(status);
  const statusTone = toneFromStatus(status);

  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm space-y-3 flex flex-col flex-1 min-h-0">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-xs text-foreground tracking-wider">
          {finished ? '✅ RPA 任务流水' : '⚡ RPA 引擎运行中'}
        </h3>
        <div className="flex items-center gap-2">
          <StatusBadge status={status} tone={statusTone} />
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

      {snapshot?.error_code && (
        <div className="border border-rose-500/40 bg-rose-500/10 text-rose-600 rounded-lg p-2 text-[11px] space-y-0.5">
          <p className="font-semibold">❌ {snapshot.error_code}</p>
          {snapshot.error_message && <p className="leading-snug">{snapshot.error_message}</p>}
        </div>
      )}

      {streamError && !finished && (
        <div className="border border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400 rounded-lg p-2 text-[10.5px]">
          ⚠️ 事件流断开：{streamError}（已根据上次快照展示）
        </div>
      )}

      <div
        ref={stepListRef}
        className="flex-1 overflow-y-auto border border-border rounded-lg bg-muted/20 p-2 space-y-1 text-[10.5px] leading-relaxed font-mono"
      >
        {steps.length === 0 ? (
          <p className="text-muted-foreground text-center py-4">等待第一条 step…</p>
        ) : (
          steps.map((step, idx) => <StepLine key={`${idx}-${step.slice(0, 24)}`} index={idx} step={step} />)
        )}
      </div>

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

// 单条 step 行，按前缀染色，便于扫一眼定位失败/重试节点
function StepLine({ index, step }: { index: number; step: string }) {
  const tone = stepTone(step);
  // 形如 "SYS_ERROR_RETRY: 发生系统异常 [ADD_PLUS_NOT_FOUND] ...":
  //   tag = "SYS_ERROR_RETRY", text = "发生系统异常 [...]"
  const colonAt = step.indexOf(':');
  const tag = colonAt > 0 ? step.slice(0, colonAt) : '';
  const text = colonAt > 0 ? step.slice(colonAt + 1).trim() : step;

  const toneClass =
    tone === 'success'
      ? 'text-emerald-700 dark:text-emerald-400'
      : tone === 'fail'
        ? 'text-rose-600 dark:text-rose-400'
        : tone === 'warn'
          ? 'text-amber-600 dark:text-amber-400'
          : 'text-foreground/80';

  const tagBg =
    tone === 'success'
      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
      : tone === 'fail'
        ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
        : tone === 'warn'
          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
          : 'bg-muted text-muted-foreground';

  return (
    <div className={`flex gap-2 items-start ${toneClass}`}>
      <span className="text-muted-foreground select-none w-5 text-right shrink-0">{index + 1}.</span>
      {tag ? (
        <>
          <span className={`px-1.5 py-px rounded text-[9.5px] font-bold shrink-0 ${tagBg}`}>{tag}</span>
          <span className="break-all">{text}</span>
        </>
      ) : (
        <span className="break-all">{text}</span>
      )}
    </div>
  );
}

function StatusBadge({ status, tone }: { status: string; tone: 'success' | 'fail' | 'warn' | 'default' }) {
  const toneClass =
    tone === 'success'
      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400'
      : tone === 'fail'
        ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
        : tone === 'warn'
          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
          : 'bg-muted text-muted-foreground';
  return <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${toneClass}`}>{status}</span>;
}

function toneFromStatus(status: string): 'success' | 'fail' | 'warn' | 'default' {
  if (status === 'SIMULATION_COMPLETED' || status === 'REAL_COMPLETED') return 'success';
  if (status === 'FAILED') return 'fail';
  if (status.startsWith('REAL_BIZ_')) return 'warn';
  return 'default';
}

function stepTone(step: string): 'success' | 'fail' | 'warn' | 'default' {
  // 失败/异常优先（即便后续重试成功，也希望这一行高亮，方便定位失败节点）
  if (/^(SYS_ERROR_RETRY|SYS_RPA_TIMEOUT|.*_NOT_FOUND|.*_MISS|.*_BLOCKED|.*_RISK|.*_REJECT|.*_FAILED)/i.test(step)) {
    if (/^.*_NOT_FOUND/i.test(step) && !/SYS_ERROR_RETRY/i.test(step)) return 'fail';
    if (/SYS_ERROR_RETRY|SYS_RPA_TIMEOUT|.*_BLOCKED|.*_RISK|.*_REJECT|.*_FAILED/i.test(step)) return 'fail';
    // 单步 *_MISS 仅说明本步降级，不是终态失败，给 warn
    return 'warn';
  }
  if (/(_COMPLETED|_OK|_FOUND|_HIT|_CONFIRMED|_OPENED|_FILLED|_TYPED|_CLICKED|ACCEPTED)/i.test(step)) {
    return 'success';
  }
  if (/(safety_delay|POST_PASTE_WAIT|CLEANUP_)/i.test(step)) return 'warn';
  return 'default';
}

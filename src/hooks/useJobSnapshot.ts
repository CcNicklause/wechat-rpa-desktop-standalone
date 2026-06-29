import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getLocalApiToken, LOCAL_API_BASE, requestLocalApi } from '@/lib/api';
import { useLeadJobsStore, selectSnapshot } from './useLeadJobs';
import type { JobSnapshot } from '@/stores/useDevTestStore';

export const TERMINAL_STATUSES = new Set([
  'SIMULATION_COMPLETED',
  'REAL_COMPLETED',
  'FAILED',
  'REAL_BIZ_TARGET_NOT_FOUND',
  'REAL_BIZ_ALREADY_FRIEND',
  'REAL_BIZ_ADD_REJECTED',
  'REAL_BIZ_RISK_CONTROL',
]);

// 全局单例管理：同一 jobId 只开一个 SSE 连接
const activeStreams = new Map<
  string,
  { controller: AbortController; listeners: Set<(snapshot: JobSnapshot) => void> }
>();

interface UseJobSnapshotOptions {
  onComplete?: () => void;
}

export function useJobSnapshot(
  jobId: string | null,
  options: UseJobSnapshotOptions = {},
): {
  snapshot: JobSnapshot | null;
  error: string | null;
  isTerminal: boolean;
} {
  const { onComplete } = options;
  const setSnapshot = useLeadJobsStore((s) => s.setSnapshot);
  const storedSnapshot = useLeadJobsStore((s) => selectSnapshot(s, jobId));
  const completedRef = useRef(false);
  const errorRef = useRef<string | null>(null);

  // 用 React Query 做兜底 GET，同时也用于 queryKey 去重
  const { data: initialSnapshot, error: queryError } = useQuery({
    queryKey: ['jobSnapshot', jobId],
    queryFn: async () => {
      if (!jobId) return null;
      return requestLocalApi<JobSnapshot>(`/api/v1/rpa/jobs/${jobId}`);
    },
    enabled: !!jobId,
    // 已经有 store 快照的话，不需要立即重新 fetch
    initialData: storedSnapshot || undefined,
  });

  // SSE 流式更新
  useEffect(() => {
    if (!jobId) return;

    completedRef.current = false;
    errorRef.current = null;

    // 先用初始快照（来自 store 或兜底 GET）更新 store
    if (initialSnapshot) {
      setSnapshot(initialSnapshot);
      if (TERMINAL_STATUSES.has(initialSnapshot.status) && !completedRef.current) {
        completedRef.current = true;
        onComplete?.();
      }
    }

    // 检查是否已有活跃的 stream
    let stream = activeStreams.get(jobId);
    if (!stream) {
      const controller = new AbortController();
      const listeners = new Set<(snapshot: JobSnapshot) => void>();
      stream = { controller, listeners };
      activeStreams.set(jobId, stream);

      // 启动新的 SSE 连接
      (async () => {
        try {
          const token = await getLocalApiToken();
          const response = await fetch(
            `${LOCAL_API_BASE}/api/v1/rpa/jobs/${jobId}/events`,
            {
              method: 'GET',
              headers: {
                Authorization: `Bearer ${token}`,
                Accept: 'text/event-stream',
              },
              signal: controller.signal,
            },
          );
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
            let sepIndex: number;
            while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
              const frame = buffer.slice(0, sepIndex);
              buffer = buffer.slice(sepIndex + 2);
              const dataLines = frame
                .split('\n')
                .filter((line) => line.startsWith('data:'))
                .map((line) => line.replace(/^data:\s?/, ''));
              if (!dataLines.length) continue;
              const payload = dataLines.join('\n');
              try {
                const parsed = JSON.parse(payload) as JobSnapshot;
                // 通知所有监听者
                listeners.forEach((cb) => cb(parsed));
              } catch (err) {
                console.warn('useJobSnapshot: bad SSE frame', payload, err);
              }
            }
          }
        } catch (err: any) {
          if (controller.signal.aborted) return;
          errorRef.current = err?.message || String(err);
        }
      })();
    }

    // 注册本组件的监听者
    const handleSnapshot = (parsed: JobSnapshot) => {
      setSnapshot(parsed);
      if (TERMINAL_STATUSES.has(parsed.status) && !completedRef.current) {
        completedRef.current = true;
        onComplete?.();
      }
    };
    stream.listeners.add(handleSnapshot);

    return () => {
      // 移除本组件的监听者
      stream?.listeners.delete(handleSnapshot);
      // 如果没有监听者了，关闭连接
      if (stream?.listeners.size === 0) {
        stream.controller.abort();
        activeStreams.delete(jobId);
      }
    };
  }, [jobId, onComplete, setSnapshot, initialSnapshot]);

  const snapshot = useLeadJobsStore((s) => selectSnapshot(s, jobId));
  const status = snapshot?.status ?? 'QUEUED';
  const isTerminal = TERMINAL_STATUSES.has(status);

  return {
    snapshot: snapshot || initialSnapshot || null,
    error: errorRef.current || (queryError as string) || null,
    isTerminal,
  };
}

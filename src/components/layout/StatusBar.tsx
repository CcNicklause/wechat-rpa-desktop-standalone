import { useEffect, useState } from 'react';
import { getLocalApiBase, getSidecarStatus, requestLocalApi, type SidecarStatus } from '@/lib/api';

export function StatusBar() {
  const [engineConnected, setEngineConnected] = useState(false);
  const [quota, setQuota] = useState({ used: 0, limit: 50 });
  const [apiBase, setApiBase] = useState<string | null>(null);
  const [sidecarStatus, setSidecarStatus] = useState<SidecarStatus | null>(null);

  useEffect(() => {
    const checkConnection = async () => {
      const status = await getSidecarStatus();
      setSidecarStatus(status);
      try {
        const resolvedApiBase = status?.api_base ?? await getLocalApiBase();
        setApiBase(resolvedApiBase);
        const data = await requestLocalApi<any>('/api/v1/health');
        setEngineConnected(true);
        setQuota({
          used: data.daily_used ?? 0,
          limit: data.daily_limit ?? 50
        });
      } catch {
        setEngineConnected(false);
      }
    };

    checkConnection();
    const interval = setInterval(checkConnection, 5000);
    return () => clearInterval(interval);
  }, []);

  const statusTone = engineConnected
    ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]'
    : sidecarStatus?.phase === 'starting' || sidecarStatus?.phase === 'restarting'
      ? 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.35)]'
      : 'bg-rose-500';
  const pulseTone = engineConnected
    ? 'bg-emerald-400'
    : sidecarStatus?.phase === 'starting' || sidecarStatus?.phase === 'restarting'
      ? 'bg-amber-400'
      : 'bg-rose-400';
  const engineLabel = engineConnected
    ? `已连接 (${apiBase ?? '本机端口'})`
    : sidecarStatus?.phase === 'starting'
      ? '启动中'
      : sidecarStatus?.phase === 'restarting'
        ? `重启中 ${sidecarStatus.restart_count}/${sidecarStatus.max_restarts}`
        : sidecarStatus?.phase === 'failed'
          ? '启动失败'
          : '断开连接';

  return (
    <footer className="w-full h-8 px-6 border-t border-border bg-card text-muted-foreground flex items-center justify-between text-[10px] tracking-wide relative z-10">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${pulseTone}`}></span>
          <span className={`relative inline-flex rounded-full h-2 w-2 ${statusTone}`}></span>
        </span>
        <span>RPA 引擎状态: {engineLabel}</span>
      </div>
      <div>
        <span>今日执行额度: <span className="font-semibold text-primary font-mono">{quota.used}</span> / {quota.limit}</span>
      </div>
    </footer>
  );
}

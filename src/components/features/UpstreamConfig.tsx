import { useEffect, useRef } from 'react';
import { useUpstreamStore } from '@/stores/useUpstreamStore';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/common/StatusBadge';
import { LOCAL_API_BASE } from '@/lib/api';

export function UpstreamConfig() {
  const {
    config, status, logs, isConnecting,
    fetchConfig, saveConfig, fetchStatus,
    triggerFetch, triggerHeartbeat, clearQueue,
    addLog, clearLogs,
  } = useUpstreamStore();

  const logEndRef = useRef<HTMLDivElement>(null);

  // 1. 定期刷新健康状态
  useEffect(() => {
    fetchConfig();
    fetchStatus();
    const timer = setInterval(fetchStatus, 5000);
    return () => clearInterval(timer);
  }, []);

  // 2. 初始化监听 SSE 日志流
  useEffect(() => {
    const eventSource = new EventSource(`${LOCAL_API_BASE}/api/v1/upstream/logs`);
    eventSource.onmessage = (event) => {
      addLog(event.data);
    };
    return () => {
      eventSource.close();
    };
  }, []);

  // 3. 自动滚动日志到底部
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const stateLabel = (s: string) => {
    switch (s) {
      case 'IDLE': return 'IDLE 空闲';
      case 'BUSY': return 'BUSY 繁忙';
      case 'COOLDOWN': return 'COOLDOWN 风控等待';
      default: return s;
    }
  };

  return (
    <div className="flex-1 p-6 overflow-y-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">上游接口与调度管理</h1>
          <p className="text-xs text-muted-foreground mt-1">配置与测试外部业务系统对接</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Card A: 配置 */}
        <Card className="p-6 border border-border bg-card space-y-4 lg:col-span-2">
          <h2 className="text-sm font-bold">上游参数配置</h2>

          <div className="space-y-4">
            <div className="space-y-2">
              <span className="text-xs font-semibold text-muted-foreground">运行模式</span>
              <div className="flex items-center gap-6">
                {/* 这里不能用 <Label>：Label 默认带 text-muted-foreground，
                    会把内层 span 一并染成灰色。radio 行 span 自己保持 text-foreground。 */}
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="upstream_mode"
                    value="mock"
                    checked={config.upstream_mode === 'mock'}
                    onChange={() => saveConfig({ upstream_mode: 'mock' })}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="text-xs text-foreground">Mock 本地模拟模式</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="upstream_mode"
                    value="real"
                    checked={config.upstream_mode === 'real'}
                    onChange={() => saveConfig({ upstream_mode: 'real' })}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="text-xs text-foreground">Real 真实网络模式</span>
                </label>
              </div>
            </div>

            <div className="space-y-1.5">
              <span className="text-xs font-semibold text-muted-foreground">上游 API URL</span>
              <Input
                type="text"
                defaultValue={config.upstream_api_url}
                onBlur={(e) => saveConfig({ upstream_api_url: e.target.value })}
                placeholder="http://localhost:8000/api/v1/upstream"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-muted-foreground">Client ID</span>
                <Input
                  type="text"
                  defaultValue={config.client_id}
                  onBlur={(e) => saveConfig({ client_id: e.target.value })}
                  placeholder="client-001"
                />
              </div>
              <div className="space-y-1.5">
                <span className="text-xs font-semibold text-muted-foreground">Client Secret</span>
                <Input
                  type="password"
                  defaultValue={config.client_secret}
                  onBlur={(e) => saveConfig({ client_secret: e.target.value })}
                  placeholder="••••••••••••"
                />
              </div>
            </div>

            {isConnecting && (
              <p className="text-xs text-amber-500">正在连接并应用配置...</p>
            )}
          </div>
        </Card>

        {/* Card B: 状态 */}
        <Card className="p-6 border border-border bg-card space-y-4">
          <h2 className="text-sm font-bold">系统健康度监控</h2>
          <div className="space-y-3.5 pt-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">后台守护服务</span>
              <Badge variant={status.scheduler_alive ? 'success' : 'failed'} className="text-[10px]">
                {status.scheduler_alive ? '运行中' : '已停止'}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">PC 微信状态</span>
              <Badge variant={status.wechat_online ? 'success' : 'failed'} className="text-[10px]">
                {status.wechat_online ? '微信已启动' : '未检测到进程'}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">调度器工作状态</span>
              <StatusBadge status={status.state} label={stateLabel(status.state)} className="text-[10px]" />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">队列任务数</span>
              <Badge variant="secondary" className="text-[10px]">{status.queue_remaining} 个等待中</Badge>
            </div>
          </div>
        </Card>
      </div>

      {/* Card C: 滚动日志 */}
      <Card className="p-6 border border-border bg-card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold">调试日志控制台</h2>
          <Button variant="ghost" size="sm" onClick={clearLogs} className="text-xs h-7 text-muted-foreground">
            清空日志
          </Button>
        </div>

        <div className="h-64 bg-slate-950 text-slate-100 rounded-lg p-4 font-mono text-xs overflow-y-auto space-y-1.5 border border-slate-800">
          {logs.map((log, index) => (
            <div key={index} className="leading-relaxed whitespace-pre-wrap">{log}</div>
          ))}
          {logs.length === 0 && (
            <div className="text-slate-500">等待调度事件日志流入...</div>
          )}
          <div ref={logEndRef} />
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={triggerFetch} size="sm">立即触发拉取线索</Button>
          <Button onClick={triggerHeartbeat} variant="outline" size="sm">测试发送心跳</Button>
          <Button onClick={clearQueue} variant="destructive" size="sm">清空本地等待队列</Button>
        </div>
      </Card>
    </div>
  );
}

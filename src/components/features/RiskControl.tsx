import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { EmptyState } from '@/components/common/EmptyState';
import { requestLocalApi } from '@/lib/api';
import { useToast } from '@/hooks/useToast';
import { AuditLog } from '@/hooks/useAudits';
import { formatLocalTime } from '@/lib/localTime';

interface RiskControlProps {
  audits: AuditLog[];
}

export function RiskControl({ audits }: RiskControlProps) {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dailyLimit, setDailyLimit] = useState(3);
  const [minInterval, setMinInterval] = useState(3);
  const [maxInterval, setMaxInterval] = useState(9);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const res = await requestLocalApi<any>('/api/v1/health');
        setDailyLimit(res.daily_limit || 3);
        setMinInterval(res.min_interval ?? 3);
        setMaxInterval(res.max_interval ?? 9);
        setLoading(false);
      } catch {
        setLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await requestLocalApi('/api/v1/health/settings', {
        method: 'POST',
        body: JSON.stringify({
          daily_limit: dailyLimit,
          min_interval: minInterval,
          max_interval: maxInterval,
        }),
      });
      toast({ title: '保存成功', description: '安全风控配置已被热更新保存', variant: 'success' });
    } catch (err: any) {
      toast({ title: '保存失败', description: err.message || '保存设置异常', variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  // Filter audits related to safety limit blocks or errors
  const riskAudits = audits.filter(
    (a) => a.event_type.includes('blocked') || a.result === 'failed' || a.event_type.includes('limit')
  );

  if (loading) {
    return <div className="p-6 text-xs text-muted-foreground text-center">正在加载风控参数...</div>;
  }

  return (
    <div className="flex-1 flex overflow-hidden p-6 gap-6">
      <Card className="flex-1 flex flex-col p-6 shadow-sm border border-border bg-card">
        <CardHeader className="p-0 pb-4 border-b border-border mb-4">
          <CardTitle>安全加粉规则阈值配置</CardTitle>
        </CardHeader>
        <CardContent className="p-0 space-y-5 text-xs flex-1 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="font-semibold">每日最大加粉上限: {dailyLimit} 次</span>
                <span className="text-[10px] text-muted-foreground">避免短时间内过度加人遭微信号限制</span>
              </div>
              <input
                type="range"
                min="1"
                max="15"
                value={dailyLimit}
                onChange={(e) => setDailyLimit(Number(e.target.value))}
                className="w-full h-1.5 bg-secondary rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>最小延时随机间隔 (秒)</Label>
                <Input
                  type="number"
                  min="0"
                  max="60"
                  value={minInterval}
                  onChange={(e) => setMinInterval(Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>最大延时随机间隔 (秒)</Label>
                <Input
                  type="number"
                  min="0"
                  max="60"
                  value={maxInterval}
                  onChange={(e) => setMaxInterval(Number(e.target.value))}
                />
              </div>
            </div>
          </div>

          <Button onClick={handleSave} disabled={saving} className="w-full h-9">
            {saving ? '正在保存...' : '立即应用风控规则'}
          </Button>
        </CardContent>
      </Card>

      <Card className="w-96 flex flex-col p-6 shadow-sm border border-border bg-card">
        <CardHeader className="p-0 pb-4 border-b border-border mb-4">
          <CardTitle>🛡️ 风控阻断审计流</CardTitle>
        </CardHeader>
        <div className="flex-1 overflow-y-auto space-y-4 pr-2 text-xs custom-scrollbar">
          {riskAudits.map((audit) => (
            <div key={audit.id} className="relative pl-6 pb-2 border-l border-border last:border-l-0">
              <div className="absolute -left-1.5 top-0.5 w-3 h-3 rounded-full bg-background border-2 border-rose-500 flex items-center justify-center" />
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span className="font-mono text-rose-500">
                    {formatLocalTime(audit.timestamp)}
                  </span>
                  <Badge variant="destructive">blocked</Badge>
                </div>
                <p className="text-[11px] font-semibold text-foreground">{audit.event_type}</p>
                <p className="text-[10px] text-muted-foreground leading-relaxed">
                  {audit.message || `${audit.phone_masked || ''} RPA 执行遭阻断`}
                </p>
              </div>
            </div>
          ))}
          {riskAudits.length === 0 && (
            <EmptyState title="暂无风控阻断事件" />
          )}
        </div>
      </Card>
    </div>
  );
}

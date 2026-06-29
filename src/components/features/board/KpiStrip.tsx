import { Users, UserCheck, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { Lead } from '@/hooks/useLeads';
import { countLeadsByStatus } from '@/lib/leadStatus';
import type { LeadStats } from '@/hooks/useLeadsStats';

interface KpiStripProps {
  leads: Lead[];
  stats?: LeadStats | null;
  className?: string;
}

export function KpiStrip({ leads, stats, className }: KpiStripProps) {
  const isStatsMode = !!stats;
  const { success, running, failure, total } = isStatsMode
    ? { success: stats.success, running: stats.running, failure: stats.failure, total: stats.total }
    : countLeadsByStatus(leads);

  const successRate = total > 0
    ? ((success / total) * 100).toFixed(1)
    : '0.0';

  return (
    <div className={cn('grid grid-cols-4 gap-4 shrink-0', className)}>
      <Card className="border border-border shadow-sm bg-card hover:shadow transition-shadow">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">线索总数</p>
            <h3 className="text-2xl font-bold text-foreground">{total}</h3>
            <p className="text-[9px] text-muted-foreground">
              {isStatsMode ? '全库实时计数' : `近 ${leads.length} 条样本`}
            </p>
          </div>
          <div className="p-2.5 bg-primary/10 text-primary rounded-xl">
            <Users className="h-5 w-5" />
          </div>
        </CardContent>
      </Card>

      <Card className="border border-border shadow-sm bg-card hover:shadow transition-shadow">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">加友成功率</p>
            <h3 className="text-2xl font-bold text-emerald-600 dark:text-emerald-500">{successRate}%</h3>
            <p className="text-[9px] text-muted-foreground">
              已成功添加微信好友 {success} 人
              {!isStatsMode && ` (基于 N=${leads.length} 条样本，仅供参考)`}
            </p>
          </div>
          <div className="p-2.5 bg-emerald-500/10 text-emerald-600 rounded-xl">
            <UserCheck className="h-5 w-5" />
          </div>
        </CardContent>
      </Card>

      <Card className="border border-border shadow-sm bg-card hover:shadow transition-shadow">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">RPA 执行中</p>
            <h3 className="text-2xl font-bold text-blue-600 dark:text-blue-500">{running}</h3>
            <p className="text-[9px] text-muted-foreground">客户端引擎正在操作的队列数</p>
          </div>
          <div className="p-2.5 bg-blue-500/10 text-blue-600 rounded-xl">
            <RefreshCw className="h-5 w-5 animate-spin" style={{ animationDuration: '3s' }} />
          </div>
        </CardContent>
      </Card>

      <Card className="border border-border shadow-sm bg-card hover:shadow transition-shadow">
        <CardContent className="p-4 flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">异常与限制</p>
            <h3 className="text-2xl font-bold text-rose-600 dark:text-rose-500">{failure}</h3>
            <p className="text-[9px] text-muted-foreground">包含超时、被拒或风控提示</p>
          </div>
          <div className="p-2.5 bg-rose-500/10 text-rose-600 rounded-xl">
            <AlertCircle className="h-5 w-5" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

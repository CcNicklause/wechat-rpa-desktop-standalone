import { Users, UserCheck, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { LeadsList } from './LeadsList';
import { JobProgress } from './JobProgress';
import { AuditTimeline } from './AuditTimeline';
import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';

interface LeadsDashboardProps {
  leads: Lead[];
  audits: AuditLog[];
  activeJobId: string | null;
  onTriggerJob: (leadId: number) => void;
  onJobComplete: () => void;
}

export function LeadsDashboard({
  leads,
  audits,
  activeJobId,
  onTriggerJob,
  onJobComplete,
}: LeadsDashboardProps) {
  // 1. 计算大盘数据指标
  const totalLeads = leads.length;
  const successLeads = leads.filter(l => l.status === 'WECHAT_ACCEPTED').length;
  const failedLeads = leads.filter(l => l.status === 'RPA_FAILED').length;
  
  // 执行中：非新建（NEW_LEAD）、非成功（WECHAT_ACCEPTED）、非失败（RPA_FAILED）的为进行中任务
  const progressLeads = leads.filter(l => 
    l.status !== 'NEW_LEAD' && 
    l.status !== 'WECHAT_ACCEPTED' && 
    l.status !== 'RPA_FAILED'
  ).length;

  const successRate = totalLeads > 0 
    ? ((successLeads / totalLeads) * 100).toFixed(1) 
    : '0.0';

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-6 gap-6">
      {/* 顶部总结性数据大盘 */}
      <div className="grid grid-cols-4 gap-4 shrink-0">
        <Card className="border border-border shadow-sm bg-card hover:shadow transition-shadow">
          <CardContent className="p-4 flex items-center justify-between">
            <div className="space-y-1">
              <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">线索总数</p>
              <h3 className="text-2xl font-bold text-foreground">{totalLeads}</h3>
              <p className="text-[9px] text-muted-foreground">已同步的待加友客户数量</p>
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
              <p className="text-[9px] text-muted-foreground">已成功添加微信好友 {successLeads} 人</p>
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
              <h3 className="text-2xl font-bold text-blue-600 dark:text-blue-500">{progressLeads}</h3>
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
              <h3 className="text-2xl font-bold text-rose-600 dark:text-rose-500">{failedLeads}</h3>
              <p className="text-[9px] text-muted-foreground">包含超时、被拒或风控提示</p>
            </div>
            <div className="p-2.5 bg-rose-500/10 text-rose-600 rounded-xl">
              <AlertCircle className="h-5 w-5" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 下方主要列表和 Feed 区域 */}
      <div className="flex-1 flex overflow-hidden gap-6 min-h-0">
        <LeadsList leads={leads} onTriggerJob={onTriggerJob} />
        <div className="w-96 flex flex-col gap-6 overflow-hidden min-h-0">
          {activeJobId && (
            <JobProgress jobId={activeJobId} onComplete={onJobComplete} />
          )}
          <AuditTimeline audits={audits} />
        </div>
      </div>
    </div>
  );
}

import { useState, lazy, Suspense } from 'react';
import { Sidebar, ROUTE_DEFINITIONS, type RoutePath } from './Sidebar';
import { DashboardHeader } from './DashboardHeader';

const LeadsDashboard = lazy(() => import('../features/LeadsDashboard').then(m => ({ default: m.LeadsDashboard })));
const AccountManagement = lazy(() => import('../features/AccountManagement').then(m => ({ default: m.AccountManagement })));
const RiskControl = lazy(() => import('../features/RiskControl').then(m => ({ default: m.RiskControl })));
const DevTesting = lazy(() => import('../features/DevTesting').then(m => ({ default: m.DevTesting })));
const UpstreamConfig = lazy(() => import('../features/UpstreamConfig').then(m => ({ default: m.UpstreamConfig })));


import { useLeadsQuery } from '@/hooks/useLeads';
import { useLeadsStatsQuery } from '@/hooks/useLeadsStats';
import { useAuditLogsQuery, useExecuteRpaMutation } from '@/hooks/useAudits';
import { useToast } from '@/hooks/useToast';
import { useHashRoute } from '@/hooks/useHashRoute';

export function AppShell() {

  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  // 用 hash 路由替代 useState<TabType>，桌面端 Tauri webview 友好（file:// 也能工作），
  // 浏览器刷新/前进后退/重启都能保留当前页面。
  const { route, navigate, setQuery } = useHashRoute('/dashboard');


  const { data: leads = [], refetch: refetchLeads } = useLeadsQuery(true);
  const { data: stats } = useLeadsStatsQuery();
  const { data: audits = [], refetch: refetchAudits } = useAuditLogsQuery();
  const executeRpa = useExecuteRpaMutation();
  const { toast } = useToast();

  const handleTriggerJob = (leadId: string) => {
    executeRpa.mutate(leadId, {
      onSuccess: (response) => {
        if (response.job_id) {
          setActiveJobId(response.job_id);
          toast({
            title: '任务启动成功',
            description: `微信加友任务已发出 (ID: ${response.job_id.slice(0, 8)})`,
            variant: 'success',
          });
          // 原子化更新 URL，打开抽屉并定位到用户视角概览。
          setQuery({
            lead: leadId,
            tab: 'overview',
            job: response.job_id
          });
        }
      },
      onError: (err: any) => {
        toast({
          title: '触发任务失败',
          description: err.message || '网络连接或权限异常',
          variant: 'destructive',
        });
      }
    });
  };

  const handleJobComplete = () => {
    setActiveJobId(null);
    refetchLeads();
    refetchAudits();
  };

  const known = ROUTE_DEFINITIONS.find((r) => r.path === route);
  const activePath: RoutePath = known ? known.path : '/dashboard';

  const renderRoute = () => {
    return (
      <Suspense fallback={
        <div className="flex-1 flex flex-col justify-center items-center text-muted-foreground gap-2">
          <span className="animate-spin h-5 w-5 border-2 border-slate-300 border-t-slate-800 rounded-full" />
          <span className="text-[10px] font-semibold text-slate-500">正在载入页面...</span>
        </div>
      }>
        {(() => {
          switch (activePath) {
            case '/dashboard':
              return (
                <LeadsDashboard
                  leads={leads}
                  stats={stats}
                  audits={audits}
                  activeJobId={activeJobId}
                  onTriggerJob={handleTriggerJob}
                  onJobComplete={handleJobComplete}
                />
              );
            case '/accounts':
              return <AccountManagement />;
            case '/risk':
              return <RiskControl audits={audits} />;
            case '/upstream':
              return <UpstreamConfig />;
            case '/test':
              return <DevTesting />;
            default:
              return null;
          }
        })()}
      </Suspense>
    );
  };

  return (
    <div className="relative flex flex-1 min-h-0 bg-background text-foreground overflow-hidden w-full transition-colors duration-300">
      <Sidebar
        activePath={activePath}
        onNavigate={navigate}
      />

      <main className="flex-1 min-w-0 flex flex-col overflow-hidden relative z-10 bg-muted/10">
        <DashboardHeader />
        {renderRoute()}
      </main>
    </div>
  );
}

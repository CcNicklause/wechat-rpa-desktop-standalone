import { KpiStrip } from './KpiStrip';
import { LeadsList } from '../LeadsList';
import { LeadDetailDrawer } from './LeadDetailDrawer';
import { useHashRoute } from '@/hooks/useHashRoute';
import { useLeadJobsStore, selectLatestJob } from '@/hooks/useLeadJobs';
import { useLeadsStatsQuery } from '@/hooks/useLeadsStats';
import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';
import { normalizeLeadDetailTab, type LeadDetailTab } from '@/lib/leadDetailTabs';

interface LeadsBoardProps {
  leads: Lead[];
  stats?: any;
  audits: AuditLog[];
  activeJobId: string | null;
  onTriggerJob?: (leadId: string) => void;
  onJobComplete: () => void;
}

export function LeadsBoard({
  leads,
  stats: propsStats,
  audits,
  activeJobId,
  onTriggerJob,
  onJobComplete,
}: LeadsBoardProps) {
  const { query, setQuery } = useHashRoute('/dashboard');
  const { data: internalStats } = useLeadsStatsQuery();
  const stats = propsStats ?? internalStats;

  // 从 URL 读取状态
  const selectedLeadId = query.lead || null;
  const selectedTab = normalizeLeadDetailTab(query.tab);
  const selectedJobId = query.job || null;

  // 找到选中的 lead
  const selectedLead = leads.find((l) => l.id === selectedLeadId) || null;
  const isDrawerOpen = selectedLeadId !== null;

  // 处理行点击
  const handleRowClick = (lead: Lead) => {
    const state = useLeadJobsStore.getState();
    const latestJob = selectLatestJob(state, lead.id);
    setQuery({
      lead: lead.id,
      tab: 'overview',
      job: latestJob?.jobId || null,
    });
  };

  // 处理关闭抽屉
  const handleCloseDrawer = () => {
    setQuery({
      lead: null,
      tab: null,
      job: null,
    });
  };

  // 处理 Tab 切换
  const handleTabChange = (tab: LeadDetailTab) => {
    setQuery({ tab });
  };

  // 处理 Job 切换
  const handleJobChange = (jobId: string) => {
    setQuery({ job: jobId });
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-6 gap-6">
      <KpiStrip leads={leads} stats={stats} />

      <div className="flex-1 flex overflow-hidden min-h-0">
        <LeadsList
          leads={leads}
          totalCount={stats?.total}
          selectedId={selectedLeadId}
          onSelect={handleRowClick}
        />
      </div>

      {/* 详情抽屉 */}
      <LeadDetailDrawer
        open={isDrawerOpen}
        lead={selectedLead}
        audits={audits}
        tab={selectedTab}
        jobId={selectedJobId}
        onClose={handleCloseDrawer}
        onTabChange={handleTabChange}
        onJobChange={handleJobChange}
        onTriggerJob={onTriggerJob}
      />
    </div>
  );
}

import { useEffect } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetFooter } from '@/components/ui/sheet';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { StatusBadge } from '@/components/common/StatusBadge';
import { LeadHeader } from './LeadHeader';
import { LeadOverviewPanel } from './LeadOverviewPanel';
import { LeadProcessPanel } from './LeadProcessPanel';
import { LeadJobsPanel } from './LeadJobsPanel';
import { useLeadJobsStore, selectLeadJobs, selectLatestJob } from '@/hooks/useLeadJobs';
import { useShallow } from 'zustand/react/shallow';
import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';
import { LEAD_DETAIL_TAB_LABELS, type LeadDetailTab } from '@/lib/leadDetailTabs';

interface LeadDetailDrawerProps {
  open: boolean;
  lead: Lead | null;
  audits: AuditLog[];
  tab: LeadDetailTab;
  jobId: string | null;
  onClose: () => void;
  onTabChange: (tab: LeadDetailTab) => void;
  onJobChange: (jobId: string) => void;
  onTriggerJob?: (leadId: string) => void;
}

export function LeadDetailDrawer({
  open,
  lead,
  audits,
  tab,
  jobId,
  onClose,
  onTabChange,
  onJobChange,
  onTriggerJob,
}: LeadDetailDrawerProps) {
  // 无条件调用 hooks，让 selector 处理空值
  const leadIdStr = lead ? String(lead.id) : '';
  const leadJobs = useLeadJobsStore(useShallow((s) => selectLeadJobs(s, leadIdStr)));
  const latestJob = useLeadJobsStore((s) => selectLatestJob(s, leadIdStr));
  const actualJobId = jobId || latestJob?.jobId || null;
  const currentJobMeta = useLeadJobsStore((s) => actualJobId ? s.jobMeta[actualJobId] : null);

  // 如果没有选中的 job，默认选中最新的
  useEffect(() => {
    if (open && lead && leadJobs.length > 0 && !jobId) {
      onJobChange(leadJobs[0].jobId);
    }
  }, [open, lead, leadJobs.length, jobId, onJobChange]);

  return (
    <Sheet open={open} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full sm:w-[60vw] sm:max-w-none lg:max-w-[900px] p-0 flex flex-col overflow-hidden">
        <SheetHeader className="px-4 sm:px-6 pt-5 pb-0 pr-14 shrink-0">
          <LeadHeader lead={lead} onTriggerJob={onTriggerJob} />
        </SheetHeader>

        <Tabs value={tab} onValueChange={(v) => onTabChange(v as LeadDetailTab)} className="flex-1 min-h-0 flex flex-col">
          <div className="px-4 sm:px-6 pt-3 shrink-0">
            <TabsList>
              <TabsTrigger value="overview">{LEAD_DETAIL_TAB_LABELS.overview}</TabsTrigger>
              <TabsTrigger value="process">{LEAD_DETAIL_TAB_LABELS.process}</TabsTrigger>
              <TabsTrigger value="history">{LEAD_DETAIL_TAB_LABELS.history}</TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-6 pt-2 pb-4">
            <TabsContent value="overview">
              <LeadOverviewPanel lead={lead} latestJob={latestJob} />
            </TabsContent>

            <TabsContent value="process">
              <LeadProcessPanel lead={lead} audits={audits} jobId={actualJobId} />
            </TabsContent>

            <TabsContent value="history">
              <LeadJobsPanel
                leadId={leadIdStr}
                selectedJobId={actualJobId}
                onSelectJob={onJobChange}
              />
            </TabsContent>
          </div>
        </Tabs>

        {currentJobMeta && (
          <SheetFooter className="px-4 sm:px-6 py-3 border-t border-border shrink-0">
            <div className="flex w-full flex-wrap items-center justify-between gap-2 text-[10px] text-muted-foreground">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="font-mono truncate">{currentJobMeta.jobId.slice(0, 12)}...</span>
                <StatusBadge status={currentJobMeta.lastStatus} />
              </div>
              {currentJobMeta.errorCode && (
                <span className="max-w-full break-all text-rose-600">{currentJobMeta.errorCode}</span>
              )}
            </div>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}

import { useEffect } from 'react';
import { Sheet, SheetContent, SheetHeader, SheetFooter } from '@/components/ui/sheet';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { StatusBadge } from '@/components/common/StatusBadge';
import { LeadHeader } from './LeadHeader';
import { LeadJobsPanel } from './LeadJobsPanel';
import { LeadStepsPanel } from './LeadStepsPanel';
import { LeadTimelinePanel } from './LeadTimelinePanel';
import { LeadRawPanel } from './LeadRawPanel';
import { useLeadJobsStore, selectLeadJobs, selectLatestJob } from '@/hooks/useLeadJobs';
import { useShallow } from 'zustand/react/shallow';
import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';

type TabType = 'jobs' | 'steps' | 'timeline' | 'raw';

interface LeadDetailDrawerProps {
  open: boolean;
  lead: Lead | null;
  audits: AuditLog[];
  tab: TabType;
  jobId: string | null;
  onClose: () => void;
  onTabChange: (tab: TabType) => void;
  onJobChange: (jobId: string) => void;
  onTriggerJob: (leadId: number) => void;
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
      <SheetContent side="right" className="w-full sm:w-[60vw] sm:max-w-[900px] p-0 flex flex-col">
        <SheetHeader className="p-6 pb-0">
          <LeadHeader lead={lead} onTriggerJob={onTriggerJob} />
        </SheetHeader>

        <Tabs value={tab} onValueChange={(v) => onTabChange(v as TabType)} className="flex-1 flex flex-col">
          <div className="px-6 pt-2">
            <TabsList>
              <TabsTrigger value="jobs">Jobs</TabsTrigger>
              <TabsTrigger value="steps">Steps</TabsTrigger>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
              <TabsTrigger value="raw">Raw</TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 overflow-y-auto px-6 pt-2">
            <TabsContent value="jobs">
              <LeadJobsPanel
                leadId={leadIdStr}
                selectedJobId={actualJobId}
                onSelectJob={onJobChange}
              />
            </TabsContent>

            <TabsContent value="steps" className="h-[calc(100vh-280px)]">
              <LeadStepsPanel jobId={actualJobId} />
            </TabsContent>

            <TabsContent value="timeline" className="h-[calc(100vh-280px)]">
              <LeadTimelinePanel lead={lead} audits={audits} />
            </TabsContent>

            <TabsContent value="raw" className="h-[calc(100vh-280px)]">
              <LeadRawPanel jobId={actualJobId} />
            </TabsContent>
          </div>
        </Tabs>

        {currentJobMeta && (
          <SheetFooter className="p-6 pt-3">
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <div className="flex items-center gap-2">
                <span className="font-mono">{currentJobMeta.jobId.slice(0, 12)}...</span>
                <StatusBadge status={currentJobMeta.lastStatus} />
              </div>
              {currentJobMeta.errorCode && (
                <span className="text-rose-600">{currentJobMeta.errorCode}</span>
              )}
            </div>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}

import { LeadsBoard } from './board/LeadsBoard';
import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';

interface LeadsDashboardProps {
  leads: Lead[];
  audits: AuditLog[];
  activeJobId: string | null;
  onTriggerJob: (leadId: number) => void;
  onJobComplete: () => void;
}

// 保持向后兼容，默认导出转发到 LeadsBoard
export function LeadsDashboard(props: LeadsDashboardProps) {
  return <LeadsBoard {...props} />;
}

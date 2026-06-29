import { LeadsBoard } from './board/LeadsBoard';
import { Lead } from '@/hooks/useLeads';
import { AuditLog } from '@/hooks/useAudits';
import type { LeadStats } from '@/hooks/useLeadsStats';

interface LeadsDashboardProps {
  leads: Lead[];
  stats?: LeadStats | null;
  audits: AuditLog[];
  activeJobId: string | null;
  onTriggerJob?: (leadId: string) => void;
  onJobComplete: () => void;
}

// 保持向后兼容，默认导出转发到 LeadsBoard
export function LeadsDashboard(props: LeadsDashboardProps) {
  return <LeadsBoard {...props} />;
}

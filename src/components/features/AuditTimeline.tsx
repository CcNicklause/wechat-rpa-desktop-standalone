import { Card, CardTitle } from '@/components/ui/card';
import { AuditList } from './board/AuditList';
import { AuditLog } from '@/hooks/useAudits';

interface AuditTimelineProps {
  audits: AuditLog[];
}

export function AuditTimeline({ audits }: AuditTimelineProps) {
  return (
    <Card className="flex-1 flex flex-col p-6 shadow-sm border border-border overflow-hidden min-h-0">
      <CardTitle className="mb-4 pb-3 border-b border-border">📋 审计动态 Feed 时间轴</CardTitle>
      <AuditList audits={audits} />
    </Card>
  );
}

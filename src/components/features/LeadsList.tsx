import { Card, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState } from '@/components/common/EmptyState';
import { LeadRowSummary } from './board/LeadRowSummary';
import { Lead } from '@/hooks/useLeads';

interface LeadsListProps {
  leads: Lead[];
  selectedId: string | null;
  onSelect: (lead: Lead) => void;
  onTriggerJob?: (leadId: string) => void;
}

export function LeadsList({ leads, selectedId, onSelect, onTriggerJob }: LeadsListProps) {
  return (
    <Card className="flex-1 flex flex-col p-6 shadow-sm border border-border">
      <div className="flex items-center justify-between mb-4 border-b border-border pb-3">
        <CardTitle>同步加微线索列表</CardTitle>
        <Badge variant="outline" className="font-mono">
          {leads.length} leads
        </Badge>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2.5 pr-2 custom-scrollbar">
        {leads.map((lead) => (
          <div
            key={lead.id}
            className={cn(
              'p-3.5 bg-card border rounded-xl flex items-center justify-between transition-colors shadow-sm cursor-pointer relative',
              selectedId === lead.id
                ? 'border-primary bg-primary/5 ring-1 ring-primary'
                : 'border-border hover:bg-muted/50'
            )}
            onClick={() => onSelect(lead)}
          >
            {/* 左侧选中指示器 */}
            {selectedId === lead.id && (
              <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary rounded-l-xl" />
            )}

            <div className="space-y-1 ml-1">
              <h4 className="font-semibold text-xs text-foreground">{lead.name}</h4>
              <p className="text-[10px] text-muted-foreground font-mono">{lead.phone}</p>
              <LeadRowSummary leadId={lead.id} />
            </div>

            <div className="flex items-center gap-4">
              <StatusBadge status={lead.status} showDot />
            </div>
          </div>
        ))}
        {leads.length === 0 && (
          <EmptyState
            icon={<span className="animate-bounce inline-block">📥</span>}
            title="暂无本地线索"
            description="系统正同步本地引擎数据，您可在“开发测试”中发起人工模拟测试线索"
          />
        )}
      </div>
    </Card>
  );
}

import { cn } from '@/lib/utils';

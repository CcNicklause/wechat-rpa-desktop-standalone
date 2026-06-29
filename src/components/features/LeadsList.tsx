import { Card, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState } from '@/components/common/EmptyState';
import { LeadRowSummary } from './board/LeadRowSummary';
import { Lead } from '@/hooks/useLeads';
import { leadListCountText, LEAD_LIST_HINT } from '@/lib/leadListCopy';
import { getLeadDisplay } from '@/lib/leadDisplay';
import { cn } from '@/lib/utils';

interface LeadsListProps {
  leads: Lead[];
  totalCount?: number | null;
  selectedId: string | null;
  onSelect: (lead: Lead) => void;
}

export function LeadsList({ leads, totalCount, selectedId, onSelect }: LeadsListProps) {
  return (
    <Card className="flex-1 flex flex-col p-6 shadow-sm border border-border">
      <div className="flex items-start justify-between gap-4 mb-4 border-b border-border pb-3">
        <div className="space-y-1">
          <CardTitle>同步加微线索列表</CardTitle>
          <p className="text-[11px] text-muted-foreground">{LEAD_LIST_HINT}</p>
        </div>
        <Badge variant="outline" className="font-mono">
          {leadListCountText(leads.length, totalCount)}
        </Badge>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2.5 pr-2 custom-scrollbar">
        {leads.map((lead) => {
          const display = getLeadDisplay(lead);

          return (
            <div
              key={lead.id}
              className={cn(
                'p-3.5 bg-card border rounded-xl flex items-center justify-between transition-colors shadow-sm cursor-pointer relative',
                selectedId === lead.id
                  ? 'border-primary/40 bg-primary/5 shadow-none'
                  : 'border-border hover:bg-muted/50'
              )}
              onClick={() => onSelect(lead)}
            >
              {selectedId === lead.id && (
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary rounded-l-xl" />
              )}

              <div className="space-y-1 ml-1 min-w-0">
                <h4 className="font-semibold text-xs text-foreground font-mono truncate">
                  {display.account}
                </h4>
                {display.remark && (
                  <p className="text-[10px] text-muted-foreground truncate">
                    备注：{display.remark}
                  </p>
                )}
                <LeadRowSummary leadId={lead.id} />
              </div>

              <div className="flex items-center justify-end gap-4 pl-3 shrink-0">
                <StatusBadge status={lead.status} showDot />
              </div>
            </div>
          );
        })}
        {leads.length === 0 && (
          <EmptyState
            title="暂无本地线索"
            description="系统正同步本地引擎数据，您可在开发测试中发起人工模拟测试线索"
          />
        )}
      </div>
    </Card>
  );
}

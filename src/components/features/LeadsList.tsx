import { Card, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Lead } from '@/hooks/useLeads';

interface LeadsListProps {
  leads: Lead[];
  onTriggerJob: (leadId: number) => void;
}

export function LeadsList({ leads, onTriggerJob }: LeadsListProps) {
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
          <div key={lead.id} className="p-3.5 bg-card border border-border hover:bg-muted/50 rounded-xl flex items-center justify-between transition-colors shadow-sm">
            <div className="space-y-1">
              <h4 className="font-semibold text-xs text-foreground">{lead.name}</h4>
              <p className="text-[10px] text-muted-foreground font-mono">{lead.phone}</p>
            </div>
            <div className="flex items-center gap-4">
              <Badge
                variant={
                  lead.status === 'success' || lead.status === 'completed'
                    ? 'success'
                    : lead.status === 'failed'
                    ? 'failed'
                    : 'pending'
                }
                showDot
              >
                {lead.status}
              </Badge>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onTriggerJob(lead.id)}
              >
                立即执行
              </Button>
            </div>
          </div>
        ))}
        {leads.length === 0 && (
          <div className="text-center py-16 space-y-2">
            <span className="text-3xl block animate-bounce">📥</span>
            <p className="text-xs text-muted-foreground">暂无本地线索</p>
            <p className="text-[10px] text-muted-foreground">系统正同步本地引擎数据，您可在“开发测试”中发起人工模拟测试线索</p>
          </div>
        )}
      </div>
    </Card>
  );
}

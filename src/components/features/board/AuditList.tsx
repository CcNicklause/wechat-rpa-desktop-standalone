import { StatusBadge } from '@/components/common/StatusBadge';
import { EmptyState } from '@/components/common/EmptyState';
import { AuditLog } from '@/hooks/useAudits';
import { translateAuditLog } from '@/lib/auditTranslate';

interface AuditListProps {
  audits: AuditLog[];
  className?: string;
}

export function AuditList({ audits, className }: AuditListProps) {
  return (
    <div className={cn('space-y-4 pr-1 sm:pr-2 text-xs custom-scrollbar', className)}>
      {audits.map((audit) => {
        const { displayTitle, displayMessage, displayResult } = translateAuditLog(audit);
        return (
          <div key={audit.id} className="relative pl-6 pb-2 border-l border-border last:border-l-0">
            {/* Flat Slate point */}
            <div className="absolute -left-1.5 top-0.5 w-3 h-3 rounded-full bg-background border-2 border-primary flex items-center justify-center" />

            <div className="space-y-1">
              <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-muted-foreground">
                <span className="font-mono text-primary">
                  {audit.timestamp ? audit.timestamp.slice(11, 19) : '00:00:00'}
                </span>
                <StatusBadge status={audit.result} label={displayResult} />
              </div>
              <p className="text-[11px] font-semibold text-foreground">{displayTitle}</p>
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                {displayMessage}
              </p>
            </div>
          </div>
        );
      })}
      {audits.length === 0 && <EmptyState title="暂无审计事件" />}
    </div>
  );
}

// 需要导入 cn
import { cn } from '@/lib/utils';

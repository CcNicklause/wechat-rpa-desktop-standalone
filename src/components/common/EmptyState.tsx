import * as React from 'react';
import { cn } from '../../lib/utils';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  className?: string;
  /**
   * 部分父容器是 flex-1，需要 EmptyState 自己撑高居中；
   * 其他列表式空态只需要居中 + padding。
   */
  variant?: 'block' | 'fill';
}

// 列表/面板空态统一外观，覆盖：
// - LeadsList、AuditTimeline、RiskControl 列表
// - DevTesting 测试进程 / 审计事件占位
export function EmptyState({
  icon,
  title,
  description,
  className,
  variant = 'block',
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'text-center text-muted-foreground space-y-2',
        variant === 'fill'
          ? 'flex-1 flex flex-col justify-center items-center py-10'
          : 'py-16',
        className,
      )}
    >
      {icon && <span className="text-3xl block">{icon}</span>}
      <p className="text-xs">{title}</p>
      {description && <p className="text-[10px] leading-relaxed">{description}</p>}
    </div>
  );
}

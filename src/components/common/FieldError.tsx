import * as React from 'react';
import { cn } from '../../lib/utils';

interface FieldErrorProps {
  children?: React.ReactNode;
  className?: string;
}

// 统一表单错误文案样式，避免每个页面重复写
// `text-[10px] text-rose-500 font-semibold`。
export function FieldError({ children, className }: FieldErrorProps) {
  if (!children) return null;
  return (
    <p className={cn('text-[10px] text-rose-500 font-semibold', className)}>
      {children}
    </p>
  );
}

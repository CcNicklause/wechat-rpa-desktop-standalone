import { type VariantProps, cva } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground hover:bg-primary/80',
        secondary:
          'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
        destructive:
          'border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80',
        outline: 'text-foreground',
        success:
          'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300 shadow-[0_0_10px_rgba(16,185,129,0.15)] [&>span]:bg-emerald-400 [&>span]:animate-pulse',
        pending:
          'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-300 shadow-[0_0_10px_rgba(245,158,11,0.15)] [&>span]:bg-amber-400 [&>span]:animate-pulse',
        failed:
          'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-300 shadow-[0_0_10px_rgba(244,63,94,0.15)] [&>span]:bg-rose-400 [&>span]:animate-pulse',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  showDot?: boolean;
}

function Badge({ className, variant, showDot = false, children, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {showDot && <span className="w-1.5 h-1.5 rounded-full inline-block" />}
      {children}
    </div>
  );
}

export { Badge, badgeVariants };

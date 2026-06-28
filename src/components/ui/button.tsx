import { Slot } from '@radix-ui/react-slot';
import { type VariantProps, cva } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  [
    'inline-flex items-center gap-1 justify-center whitespace-nowrap rounded-lg text-xs font-bold ring-offset-background transition',
    'cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none active:shadow-inner',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-0',
    'hover:enabled:opacity-90',
  ],
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground',
        outline:
          'border border-input text-foreground active:enabled:bg-accent active:enabled:border-transparent hover:enabled:opacity-100 hover:enabled:bg-accent hover:enabled:text-accent-foreground',
        secondary:
          'bg-secondary text-secondary-foreground active:bg-secondary hover:enabled:bg-secondary/80',
        ghost: 'hover:enabled:bg-accent hover:enabled:text-accent-foreground focus-visible:ring-0 text-foreground',
        link: 'whitespace-normal text-left font-normal text-primary underline-offset-4 hover:enabled:underline active:shadow-none',
        'text-action': 'font-normal hover:enabled:text-primary active:shadow-none',
        default: 'bg-primary text-primary-foreground',
        destructive: 'text-destructive',
      },
      tone: {
        primary: '',
        destructive: 'text-destructive',
        success: 'text-emerald-600 dark:text-emerald-400',
      },
      size: {
        default: 'h-7 px-3',
        sm: 'h-6 px-2',
        lg: 'h-8 px-3 text-sm',
        xl: 'h-11 px-4 text-base',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'primary',
      tone: 'primary',
      size: 'default',
    },
    compoundVariants: [
      {
        variant: 'link',
        class: 'h-auto p-0 focus-visible:ring-0',
      },
      {
        variant: 'text-action',
        class: 'h-auto p-0',
      },
      {
        variant: 'primary',
        tone: 'destructive',
        class: 'bg-destructive text-white',
      },
      {
        variant: 'primary',
        tone: 'success',
        class: 'bg-emerald-600 dark:bg-emerald-500 text-white',
      },
      {
        variant: 'destructive',
        class: 'bg-destructive text-white',
      },
    ],
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  iconOnly?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      tone,
      size,
      asChild = false,
      iconOnly = false,
      ...props
    },
    ref,
  ) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        className={cn(
          buttonVariants({ variant, tone, size }),
          {
            'px-1.5 w-7': size === 'default' && iconOnly,
            'px-1 w-6': size === 'sm' && iconOnly,
            'px-1.5 w-8': size === 'lg' && iconOnly,
          },
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };

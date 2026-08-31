import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const VARIANT_CLASSES = {
  primary:
    "bg-accent text-bg hover:bg-accent-dim active:bg-accent-strong shadow-glow",
  secondary:
    "bg-bg-raised text-text border border-border hover:border-border-strong hover:bg-bg-surface",
  ghost: "text-text-muted hover:text-text hover:bg-bg-raised",
  danger: "bg-danger/10 text-danger border border-danger/30 hover:bg-danger/20",
} as const;

const VARIANT_ACTIVE_SCALE = "active:scale-[0.98]";

const SIZE_CLASSES = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2",
} as const;

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof VARIANT_CLASSES;
  size?: keyof typeof SIZE_CLASSES;
  isLoading?: boolean;
  loadingText?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      isLoading = false,
      loadingText,
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        aria-busy={isLoading}
        className={cn(
          "inline-flex items-center justify-center rounded-md font-medium",
          "transition-[background-color,border-color,color,transform] duration-150",
          "disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
          VARIANT_CLASSES[variant],
          VARIANT_ACTIVE_SCALE,
          SIZE_CLASSES[size],
          className,
        )}
        {...props}
      >
        {isLoading && (
          <Loader2
            className="h-4 w-4 animate-spin"
            aria-hidden="true"
          />
        )}
        {isLoading && loadingText ? loadingText : children}
      </button>
    );
  },
);

Button.displayName = "Button";
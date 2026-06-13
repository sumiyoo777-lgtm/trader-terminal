"use client";
// Small shadcn-style primitives used across the terminal.
import { ReactNode } from "react";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  title,
  right,
  children,
  className,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border border-zinc-800 bg-zinc-900/60 shadow-sm",
        className,
      )}
    >
      {(title || right) && (
        <header className="flex items-center justify-between gap-2 border-b border-zinc-800/80 px-3 py-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
            {title}
          </h3>
          <div className="flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}

export function Badge({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        className ?? "border-zinc-600/50 bg-zinc-700/20 text-zinc-300",
      )}
    >
      {children}
    </span>
  );
}

export function Tooltip({
  text,
  children,
  wide,
}: {
  text: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <span className="group relative inline-flex cursor-help">
      {children}
      <span
        className={cn(
          "pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 rounded-md border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-[11px] font-normal normal-case leading-snug text-zinc-200 opacity-0 shadow-xl transition-opacity duration-150 group-hover:opacity-100",
          wide ? "w-80" : "w-56",
        )}
      >
        {text}
      </span>
    </span>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  variant = "default",
  className,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "default" | "primary" | "danger";
  className?: string;
  title?: string;
}) {
  const styles = {
    default: "border-zinc-700 bg-zinc-800/80 text-zinc-200 hover:bg-zinc-700/80",
    primary: "border-sky-600/60 bg-sky-600/20 text-sky-300 hover:bg-sky-600/30",
    danger: "border-red-600/60 bg-red-600/20 text-red-300 hover:bg-red-600/30",
  }[variant];
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded border px-2 py-1 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        styles,
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block h-3 w-3 animate-spin rounded-full border border-zinc-500 border-t-transparent",
        className,
      )}
    />
  );
}

export function StatusDot({ ok, pulse }: { ok: boolean | null | undefined; pulse?: boolean }) {
  return (
    <span
      className={cn(
        "inline-block h-1.5 w-1.5 rounded-full",
        ok == null ? "bg-zinc-600" : ok ? "bg-emerald-400" : "bg-red-400",
        pulse && ok && "animate-pulse",
      )}
    />
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-20 items-center justify-center rounded border border-dashed border-zinc-800 p-4 text-center text-xs text-zinc-500">
      {children}
    </div>
  );
}

export function ErrorState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded border border-red-900/60 bg-red-950/30 p-3 text-xs text-red-300">
      {children}
    </div>
  );
}

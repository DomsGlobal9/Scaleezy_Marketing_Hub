import type { LucideIcon } from "lucide-react";
import { Facebook, Instagram, Linkedin, MapPin, Music2, Twitter, Youtube } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { AccountStatus, Platform, StatusTone } from "@/lib/marketing-data";
import { statusTone } from "@/lib/marketing-data";

const PLATFORM_ICONS: Record<Platform, LucideIcon> = {
  facebook: Facebook,
  instagram: Instagram,
  linkedin: Linkedin,
  x: Twitter,
  tiktok: Music2,
  youtube: Youtube,
  "google-business": MapPin,
};

export function PlatformIcon({
  platform,
  className,
}: {
  platform: Platform | string;
  className?: string;
}) {
  const Icon =
    PLATFORM_ICONS[platform as Platform] ?? PLATFORM_ICONS[platform.toLowerCase() as Platform];
  if (!Icon) return null;
  return (
    <span
      className={cn(
        "grid size-10 shrink-0 place-items-center rounded-xl border border-border bg-secondary text-foreground",
        className,
      )}
    >
      <Icon className="size-5" strokeWidth={1.75} />
    </span>
  );
}

const TONE_CLASS: Record<StatusTone, string> = {
  success: "border-success/25 bg-success/10 text-success",
  warning: "border-gold/30 bg-gold/12 text-gold-foreground",
  danger: "border-destructive/25 bg-destructive/10 text-destructive",
  neutral: "border-border bg-secondary text-muted-foreground",
};

export function StatusBadge({
  status,
  tone,
  className,
}: {
  status: string;
  tone?: StatusTone;
  className?: string;
}) {
  const resolved = tone ?? statusTone(status as AccountStatus);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONE_CLASS[resolved],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  backTo,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  actions?: ReactNode;
  backTo?: string;
}) {
  return (
    <header className="mb-8 grid gap-5 sm:mb-10 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
      <div className="min-w-0">
        {backTo && (
          <Link
            to={backTo}
            className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            Back
          </Link>
        )}
        <p className="label-eyebrow">{eyebrow}</p>
        <h1 className="mt-2 text-4xl leading-[1.02] font-bold tracking-[-0.045em] text-foreground sm:text-5xl">
          {title}
        </h1>
        <p className="mt-3 max-w-3xl text-base leading-7 text-muted-foreground">{subtitle}</p>
      </div>
      {actions ? (
        <div className="flex flex-wrap gap-2 sm:justify-start lg:justify-end">{actions}</div>
      ) : null}
    </header>
  );
}

export function SectionTitle({
  label,
  title,
  description,
  action,
}: {
  label?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
      <div className="min-w-0">
        {label ? <p className="label-eyebrow">{label}</p> : null}
        <h2 className="mt-1 text-2xl font-bold tracking-[-0.025em] text-foreground">{title}</h2>
        {description ? (
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  accent = "purple",
  loading,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  accent?: "purple" | "gold";
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="surface-card p-5">
        <Skeleton className="size-9 rounded-lg" />
        <Skeleton className="mt-4 h-7 w-20" />
        <Skeleton className="mt-2 h-3 w-28" />
      </div>
    );
  }
  return (
    <div className="surface-card p-5 transition-colors duration-200 hover:border-foreground/30">
      <div className="flex items-start justify-between gap-3">
        <span
          className={cn(
            "grid size-9 place-items-center rounded-lg",
            accent === "purple" ? "bg-primary/10 text-primary" : "bg-gold/15 text-gold",
          )}
        >
          <Icon className="size-4.5" strokeWidth={1.75} />
        </span>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </div>
      <p className="mt-4 text-2xl font-semibold tracking-tight text-foreground">{value}</p>
      <p className="mt-1 text-xs tracking-wide text-muted-foreground uppercase">{label}</p>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="surface-card flex flex-col items-center px-6 py-14 text-center">
      <span className="grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
        <Icon className="size-6" strokeWidth={1.5} />
      </span>
      <h3 className="mt-4 text-lg font-semibold text-foreground">{title}</h3>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

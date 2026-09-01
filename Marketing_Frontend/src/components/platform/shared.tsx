/**
 * Pieces every console page shares: the confirm step each mutation goes
 * through, an honest error line, status/flag chips, and a table that renders
 * whatever rows the server sent without pretending to know their shape.
 */
import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorText, formatDateTime } from "@/lib/platform";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ confirm */

export interface ConfirmRequest {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  /** Ask for a reason; it is passed to `run`. Required reasons block confirm. */
  reason?: { label: string; required?: boolean; placeholder?: string };
  run: (reason: string) => Promise<void>;
}

/**
 * One dialog per page, driven by a request object. Stays open on failure and
 * shows the server's message verbatim — the operator must never have to guess
 * whether a control "took".
 */
export function ConfirmDialog({
  request,
  onClose,
}: {
  request: ConfirmRequest | null;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReason("");
    setBusy(false);
    setError(null);
  }, [request]);

  const needsReason = !!request?.reason?.required && !reason.trim();

  const confirm = async () => {
    if (!request) return;
    setBusy(true);
    setError(null);
    try {
      await request.run(reason.trim());
      onClose();
    } catch (e: unknown) {
      setError(errorText(e, "The server refused this change."));
      setBusy(false);
    }
  };

  return (
    <AlertDialog open={!!request} onOpenChange={(open) => (!open && !busy ? onClose() : null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{request?.title}</AlertDialogTitle>
          {request?.description ? (
            <AlertDialogDescription asChild>
              <div className="text-sm text-muted-foreground">{request.description}</div>
            </AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>

        {request?.reason ? (
          <div>
            <Label htmlFor="confirm-reason" className="text-xs tracking-wide uppercase">
              {request.reason.label}
              {request.reason.required ? " (required)" : ""}
            </Label>
            <Textarea
              id="confirm-reason"
              className="mt-1.5"
              rows={3}
              value={reason}
              placeholder={request.reason.placeholder ?? ""}
              onChange={(e) => setReason(e.target.value)}
              disabled={busy}
            />
          </div>
        ) : null}

        <ErrorNote message={error} />

        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <Button
            variant={request?.destructive ? "destructive" : "default"}
            onClick={() => void confirm()}
            disabled={busy || needsReason}
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : null}
            {request?.confirmLabel ?? "Confirm"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/* -------------------------------------------------------------------- notes */

export function ErrorNote({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0">{message}</span>
    </p>
  );
}

export function MutedNote({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}

/* -------------------------------------------------------------------- chips */

const STATUS_TONE: Record<string, string> = {
  ACTIVE: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  PUBLISHED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  COMPLETED: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  PENDING: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  DRAFT: "border-border bg-muted/60 text-muted-foreground",
  IN_PROGRESS: "border-primary/30 bg-primary/10 text-foreground",
  SUSPENDED: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  ARCHIVED: "border-border bg-muted/60 text-muted-foreground",
  RETIRED: "border-border bg-muted/60 text-muted-foreground",
  REVOKED: "border-border bg-muted/60 text-muted-foreground",
};

export function StatusPill({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  const text = value || "—";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[0.6875rem] font-medium whitespace-nowrap",
        STATUS_TONE[text] ?? "border-border bg-secondary text-foreground",
        className,
      )}
    >
      {text.replaceAll("_", " ")}
    </span>
  );
}

const FLAG_TONE: Record<string, string> = {
  PENDING_APPROVAL: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  NO_AI_ROUTING: "border-destructive/30 bg-destructive/10 text-destructive",
  OVER_QUOTA: "border-destructive/30 bg-destructive/10 text-destructive",
  SPEND_CAP_REACHED: "border-destructive/30 bg-destructive/10 text-destructive",
  FAILING_PUBLISHES: "border-destructive/30 bg-destructive/10 text-destructive",
  NEVER_GENERATED: "border-primary/30 bg-primary/10 text-foreground",
  INACTIVE: "border-border bg-muted/60 text-muted-foreground",
  SUSPENDED: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  ARCHIVED: "border-border bg-muted/60 text-muted-foreground",
  BRAIN_STALE: "border-amber-500/30 bg-amber-500/10 text-amber-700",
};

export function FlagChips({ flags }: { flags: string[] }) {
  if (!flags.length) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {flags.map((flag) => (
        <span
          key={flag}
          className={cn(
            "rounded-full border px-2 py-0.5 text-[0.625rem] font-semibold tracking-wide uppercase whitespace-nowrap",
            FLAG_TONE[flag] ?? "border-border bg-secondary text-foreground",
          )}
        >
          {flag.replaceAll("_", " ")}
        </span>
      ))}
    </span>
  );
}

/* ------------------------------------------------------------------- tables */

function looksLikeDate(key: string, value: unknown): value is string {
  return (
    typeof value === "string" &&
    /(_at|_on|date|timestamp)$/i.test(key) &&
    !Number.isNaN(new Date(value).getTime())
  );
}

export function renderCell(key: string, value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (looksLikeDate(key, value)) return formatDateTime(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.length
      ? value.map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ")
      : "—";
  }
  return <code className="text-[0.6875rem] break-all">{JSON.stringify(value)}</code>;
}

/**
 * Renders rows whose exact columns the server decides. The header is the
 * union of keys across the rows; a missing cell shows a dash. Used for the
 * recent-activity lists on the client detail page, where the honest thing is
 * to show the record as it is rather than a hand-picked subset that can drift.
 */
export function RecordTable({
  rows,
  empty,
  maxRows = 25,
  hide = [],
}: {
  rows: Array<Record<string, unknown>>;
  empty: string;
  maxRows?: number;
  hide?: string[];
}) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  const columns: string[] = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!columns.includes(key) && !hide.includes(key)) columns.push(key);
    }
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-xs">
        <thead className="bg-muted/50 text-[0.625rem] tracking-wide text-muted-foreground uppercase">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 font-semibold whitespace-nowrap">
                {column.replaceAll("_", " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, maxRows).map((row, index) => (
            <tr key={index} className="border-t border-border align-top">
              {columns.map((column) => (
                <td key={column} className="max-w-[28rem] px-3 py-2 break-words">
                  {renderCell(column, row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows ? (
        <p className="border-t border-border px-3 py-2 text-[0.6875rem] text-muted-foreground">
          Showing {maxRows} of {rows.length}.
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------- layout */

export function Panel({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("surface-card p-5", className)}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight text-foreground">{title}</h2>
          {description ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-0">
      <span className="shrink-0 text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 text-right text-foreground">{value}</span>
    </div>
  );
}

export function PlatformPageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
      <div className="min-w-0">
        <p className="text-xs font-semibold tracking-[0.13em] text-slate-600 uppercase">
          {eyebrow}
        </p>
        <h1 className="mt-1 text-4xl leading-[1.02] font-bold tracking-[-0.045em] text-foreground sm:text-5xl">
          {title}
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">
          {subtitle}
        </p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

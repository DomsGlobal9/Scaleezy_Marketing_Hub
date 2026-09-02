/**
 * Approval queue — every brand that signed up and is waiting on Scaleezy.
 *
 * Approve is the one moment name and website can be corrected (the client
 * cannot edit them), so the dialog offers both plus an optional plan key.
 * Reject asks for a reason and archives; attach-user is the remedy for a
 * colleague blocked by the duplicate-enrolment guard.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { Check, Loader2, RefreshCw, UserPlus, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ConfirmDialog,
  ErrorNote,
  PlatformPageHeader,
  StatusPill,
  type ConfirmRequest,
} from "@/components/platform/shared";
import {
  approveSignup,
  attachUserToClient,
  errorText,
  fetchSignups,
  formatDateTime,
  rejectSignup,
  type BrandStatus,
  type SignupQueue,
  type SignupRow,
} from "@/lib/platform";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/platform/signups")({
  head: () => ({ meta: [{ title: "Signups — Scaleezy Platform Console" }] }),
  component: SignupsPage,
});

const STATUSES: Array<{ value: BrandStatus; label: string }> = [
  { value: "PENDING", label: "Pending" },
  { value: "ACTIVE", label: "Approved" },
  { value: "ARCHIVED", label: "Rejected / archived" },
];

const ROLES = ["OWNER", "ADMIN", "MANAGER", "EDITOR", "VIEWER"] as const;

/* ------------------------------------------------------------------ approve */

function ApproveDialog({
  row,
  onClose,
  onDone,
}: {
  row: SignupRow | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [plan, setPlan] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(row?.name ?? "");
    setWebsite(row?.website ?? "");
    setPlan("");
    setConfirming(false);
    setBusy(false);
    setError(null);
  }, [row]);

  const submit = async () => {
    if (!row) return;
    setBusy(true);
    setError(null);
    try {
      const body: { name?: string; website?: string; plan?: string } = {};
      if (name.trim() && name.trim() !== row.name) body.name = name.trim();
      if (website.trim() && website.trim() !== row.website) body.website = website.trim();
      if (plan.trim()) body.plan = plan.trim();
      await approveSignup(row.brand_id, body);
      toast.success(`${body.name ?? row.name} approved.`);
      onDone();
      onClose();
    } catch (e: unknown) {
      setError(errorText(e, "Approval was refused."));
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <Dialog open={!!row} onOpenChange={(open) => (!open && !busy ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Approve {row?.name}</DialogTitle>
          <DialogDescription>
            Approval unlocks calibration and generation for this client. Name and website can be
            corrected here — the client cannot change them later.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="approve-name" className="text-xs tracking-wide uppercase">
              Brand name
            </Label>
            <Input
              id="approve-name"
              className="mt-1.5"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            />
          </div>
          <div>
            <Label htmlFor="approve-website" className="text-xs tracking-wide uppercase">
              Website
            </Label>
            <Input
              id="approve-website"
              className="mt-1.5"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
              placeholder="https://"
              disabled={busy}
            />
          </div>
          <div>
            <Label htmlFor="approve-plan" className="text-xs tracking-wide uppercase">
              Plan key (optional)
            </Label>
            <Input
              id="approve-plan"
              className="mt-1.5"
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              placeholder="Leave blank to keep the default plan"
              disabled={busy}
            />
            <p className="mt-1 text-[0.6875rem] text-muted-foreground">
              Must match a Plan.key on the server; an unknown key is refused, not guessed.
            </p>
          </div>
          <ErrorNote message={error} />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          {confirming ? (
            <Button onClick={() => void submit()} disabled={busy || !name.trim()}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
              Yes, approve
            </Button>
          ) : (
            <Button onClick={() => setConfirming(true)} disabled={!name.trim()}>
              <Check className="size-4" /> Approve…
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------- attach user */

function AttachUserForm({ row, onDone }: { row: SignupRow; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<string>("EDITOR");
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  return (
    <>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const name = username.trim();
          if (!name) return;
          setConfirm({
            title: `Attach ${name} to ${row.name}?`,
            description: `They join ${row.client_code} as ${role}. The server re-checks the user exists and the role is allowed.`,
            confirmLabel: "Attach",
            run: async () => {
              const result = await attachUserToClient(row.workspace_id, name, role);
              toast.success(`${name} attached as ${result.role}.`);
              setUsername("");
              onDone();
            },
          });
        }}
      >
        <div>
          <Label htmlFor={`attach-${row.brand_id}`} className="text-[0.625rem] tracking-wide uppercase">
            Attach user
          </Label>
          <Input
            id={`attach-${row.brand_id}`}
            className="mt-1 h-8 w-44 text-xs"
            placeholder="username or email"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <Select value={role} onValueChange={setRole}>
          <SelectTrigger className="h-8 w-28 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROLES.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button type="submit" size="sm" variant="outline" disabled={!username.trim()}>
          <UserPlus className="size-3.5" /> Attach
        </Button>
      </form>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  );
}

/* --------------------------------------------------------------------- page */

function SignupsPage() {
  const [status, setStatus] = useState<BrandStatus>("PENDING");
  const [queue, setQueue] = useState<SignupQueue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState<SignupRow | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);

  const load = useCallback(async (wanted: BrandStatus) => {
    setLoading(true);
    setError(null);
    try {
      setQueue(await fetchSignups(wanted));
    } catch (e: unknown) {
      setError(errorText(e, "Could not load the approval queue."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(status);
  }, [load, status]);

  const reload = () => void load(status);

  const reject = (row: SignupRow) =>
    setConfirm({
      title: `Reject ${row.name}?`,
      description:
        "The brand is archived and the client sees the reason. Reversible from the archived list.",
      confirmLabel: "Reject",
      destructive: true,
      reason: { label: "Reason", required: true, placeholder: "Why this signup is not a fit" },
      run: async (reason) => {
        await rejectSignup(row.brand_id, reason);
        toast.success(`${row.name} rejected.`);
        reload();
      },
    });

  return (
    <div>
      <PlatformPageHeader
        eyebrow="Platform"
        title="Signups"
        subtitle="New clients wait here until Scaleezy approves them. Calibration and generation stay locked until then."
        actions={
          <Button variant="outline" size="sm" onClick={reload} disabled={loading}>
            <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Refresh
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <button
            key={s.value}
            type="button"
            onClick={() => setStatus(s.value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              status === s.value
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-border bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            {s.label}
            {s.value === "PENDING" && queue ? ` · ${queue.pending_total}` : ""}
          </button>
        ))}
        {queue ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {queue.count} shown{queue.count >= 200 ? " (first 200)" : ""}
          </span>
        ) : null}
      </div>

      <ErrorNote message={error} />

      {loading && !queue ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : queue && queue.signups.length === 0 ? (
        <div className="surface-card p-10 text-center">
          <p className="font-medium text-foreground">Nothing {status === "PENDING" ? "waiting" : "here"}.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {status === "PENDING"
              ? "Every signup has been reviewed."
              : "No brands with this status."}
          </p>
        </div>
      ) : queue ? (
        <div className="overflow-x-auto rounded-xl border border-border bg-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-[0.625rem] tracking-wide text-muted-foreground uppercase">
              <tr>
                <th className="px-3 py-2 font-semibold">Client</th>
                <th className="px-3 py-2 font-semibold">Website / industry</th>
                <th className="px-3 py-2 font-semibold">Signed up</th>
                <th className="px-3 py-2 font-semibold">Built so far</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {queue.signups.map((row) => (
                <tr key={row.brand_id} className="border-t border-border align-top">
                  <td className="px-3 py-3">
                    <Link
                      to="/platform/clients/$workspaceId"
                      params={{ workspaceId: row.workspace_id }}
                      className="font-medium text-foreground hover:underline"
                    >
                      {row.name || "Unnamed brand"}
                    </Link>
                    <p className="font-mono text-[0.6875rem] text-muted-foreground">{row.client_code}</p>
                    {row.legal_name && row.legal_name !== row.name ? (
                      <p className="text-xs text-muted-foreground">{row.legal_name}</p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-xs">
                    {row.website ? (
                      <a
                        href={row.website}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="break-all text-foreground underline-offset-2 hover:underline"
                      >
                        {row.website}
                      </a>
                    ) : (
                      <span className="text-muted-foreground">No website</span>
                    )}
                    <p className="text-muted-foreground">
                      {[row.industry || "No industry", row.location].filter(Boolean).join(" · ")}
                    </p>
                  </td>
                  <td className="px-3 py-3 text-xs">
                    <p>{formatDateTime(row.signed_up_at)}</p>
                    <p className="text-muted-foreground">by {row.signed_up_by || "—"}</p>
                    {row.contact_person || row.contact_phone ? (
                      <p className="text-muted-foreground">
                        {[row.contact_person, row.contact_phone].filter(Boolean).join(" · ")}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 text-xs text-muted-foreground">
                    <p>{row.knowledge_sources} knowledge source{row.knowledge_sources === 1 ? "" : "s"}</p>
                    <p>{row.inspirations} inspiration{row.inspirations === 1 ? "" : "s"}</p>
                    <p>{row.team_size} on the team</p>
                  </td>
                  <td className="px-3 py-3 text-xs">
                    <StatusPill value={row.status} />
                    {row.reviewed_at ? (
                      <p className="mt-1 text-muted-foreground">
                        {formatDateTime(row.reviewed_at)}
                        {row.reviewed_by ? ` · ${row.reviewed_by}` : ""}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-col gap-2">
                      {row.status === "PENDING" ? (
                        <div className="flex flex-wrap gap-2">
                          <Button size="sm" onClick={() => setApproving(row)}>
                            <Check className="size-3.5" /> Approve
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => reject(row)}>
                            <X className="size-3.5" /> Reject
                          </Button>
                        </div>
                      ) : null}
                      <AttachUserForm row={row} onDone={reload} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <ApproveDialog row={approving} onClose={() => setApproving(null)} onDone={reload} />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}

/**
 * Add Client — create a tenant and land inside it, in one gesture.
 *
 * One atomic POST creates the workspace, OWNER membership, requested default
 * brand and usable AI routes. Only after that succeeds does the selector load
 * the new client and open onboarding, so retries cannot strand partial clients.
 */
import { Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";

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
import { api } from "@/lib/api";
import { loadWorkspaces, readSelectedWorkspaceId } from "@/lib/workspace";

interface WorkspaceDto {
  id: string;
  workspace_name: string;
}

const localTimezone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
};

export function AddClientDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `selectWorkspace` — persists the id and replaces the document. */
  onCreated: (workspaceId: string) => void;
}) {
  const [clientName, setClientName] = useState("");
  const [brandName, setBrandName] = useState("");
  const [brandTouched, setBrandTouched] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) return;
    setClientName("");
    setBrandName("");
    setBrandTouched(false);
    setError(null);
    setBusy(null);
  }, [open]);

  const effectiveBrandName = (brandTouched ? brandName : clientName).trim();
  const canSubmit = !!clientName.trim() && !!effectiveBrandName && busy === null;

  const create = async () => {
    setError(null);
    try {
      setBusy("Creating the client…");
      const workspace = await api<WorkspaceDto>("/api/marketing/workspaces/", {
        method: "POST",
        body: {
          workspace_name: clientName.trim(),
          brand_name: effectiveBrandName,
          timezone: localTimezone(),
          default_language: "en",
        },
      });
      if (!workspace?.id) throw new Error("The client was created without an id.");
      const id = workspace.id;

      // The switcher only addresses ids the server has confirmed, so the
      // membership list has to be re-read before the new client is selectable.
      setBusy("Opening your new client…");
      await loadWorkspaces({ force: true });

      // A first client auto-selects during that reload — there is nothing else
      // to address — and `selectWorkspace` is then a no-op, reload included.
      // Checked before the switch so the page still turns over in that case.
      const alreadyAddressed = readSelectedWorkspaceId() === id;

      // Rewrites the address bar without rendering anything, so the reload
      // `onCreated` triggers lands on onboarding directly. Navigating with the
      // router first would mount the wizard against the OLD client for a beat,
      // and that first render calls /brands/current/ — which creates a brand as
      // a side effect. Nothing gets to render in between this way.
      window.history.replaceState(null, "", "/onboarding");
      onCreated(id);
      if (alreadyAddressed) window.location.reload();
    } catch (e) {
      setBusy(null);
      setError(e instanceof Error ? e.message : "Could not create the client.");
    }
  };

  return (
    // Mid-creation the dialog refuses to close so its confirmed destination is
    // not lost while the selector reloads.
    <Dialog open={open} onOpenChange={(next) => (busy ? undefined : onOpenChange(next))}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add a client</DialogTitle>
          <DialogDescription>
            A client is a separate workspace: its own brand, knowledge, content and channels.
            Nothing is shared with your other clients.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label className="text-xs tracking-wide uppercase" htmlFor="add-client-name">
              Client name
            </Label>
            <Input
              id="add-client-name"
              className="mt-1.5"
              placeholder="Acme Coffee"
              autoFocus
              value={clientName}
              disabled={busy !== null}
              onChange={(e) => setClientName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) void create();
              }}
            />
          </div>
          <div>
            <Label className="text-xs tracking-wide uppercase" htmlFor="add-client-brand">
              Brand name
            </Label>
            <Input
              id="add-client-brand"
              className="mt-1.5"
              placeholder="Acme Coffee"
              value={brandTouched ? brandName : clientName}
              disabled={busy !== null}
              onChange={(e) => {
                setBrandTouched(true);
                setBrandName(e.target.value);
              }}
            />
            <p className="mt-1.5 text-xs text-muted-foreground">
              Defaults to the client name. Everything else about the brand comes next, in
              onboarding.
            </p>
          </div>

          {error ? (
            <p className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" disabled={busy !== null} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!canSubmit} onClick={() => void create()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            {busy ?? "Create client"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

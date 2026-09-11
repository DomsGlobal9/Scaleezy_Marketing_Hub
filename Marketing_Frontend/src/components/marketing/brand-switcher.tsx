/**
 * Which brand the hub is working on, and how to add another.
 *
 * A client can own several brands. Every page reads the workspace's default
 * brand (`/brands/current/`), so switching is one PATCH that promotes the
 * chosen brand to default — the model demotes the previous one — followed by
 * a full reload, so no page-level cache can keep showing the old brand's
 * facts, drafts or readiness. A new brand is promoted the same way and the
 * reload lands in the setup wizard, because a brand with nothing taught is
 * exactly what the wizard is for.
 */
import { Check, ChevronsUpDown, Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { hasStringFields, parseList } from "@/lib/list-response";
import { cn } from "@/lib/utils";
import { getSelectedWorkspace } from "@/lib/workspace";

interface BrandRow {
  id: string;
  name: string;
  industry: string;
  status: string;
  is_default: boolean;
}

const CAN_EDIT = new Set(["OWNER", "ADMIN", "MANAGER", "EDITOR"]);

async function makeCurrent(id: string) {
  await api(`/api/marketing/brands/${id}/`, { method: "PATCH", body: { is_default: true } });
  window.location.reload();
}

export function BrandSwitcher({ dark = false }: { dark?: boolean }) {
  const [brands, setBrands] = useState<BrandRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const canEdit = CAN_EDIT.has(getSelectedWorkspace()?.role ?? "");

  useEffect(() => {
    let cancelled = false;
    api<unknown>("/api/marketing/brands/")
      .then((payload) => {
        if (cancelled) return;
        const rows = parseList<BrandRow>(
          payload,
          (v): v is BrandRow => hasStringFields(v, ["id", "name", "status"]),
          "Brands",
        ).filter((b) => b.status !== "ARCHIVED");
        setBrands(rows);
      })
      .catch(() => {
        if (!cancelled) setBrands([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const current = brands?.find((b) => b.is_default) ?? brands?.[0] ?? null;

  const switchTo = async (id: string) => {
    if (id === current?.id) return;
    setBusy(true);
    try {
      await makeCurrent(id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not switch brand.");
      setBusy(false);
    }
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Switch brand. Current brand: ${current?.name ?? "loading"}`}
            disabled={busy || brands === null}
            className={cn(
              "flex min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors disabled:opacity-60",
              dark
                ? "border-white/15 bg-white/5 text-white hover:border-primary/60 hover:bg-white/10"
                : "border-border bg-background text-foreground hover:border-foreground",
            )}
          >
            <span className="min-w-0">
              <span
                className={cn(
                  "block text-[0.625rem] font-semibold tracking-[0.14em] uppercase",
                  dark ? "text-white/45" : "text-muted-foreground",
                )}
              >
                Brand
              </span>
              <span className="block max-w-[14rem] truncate text-sm font-semibold">
                {busy ? "Switching…" : (current?.name ?? "Loading…")}
              </span>
            </span>
            <ChevronsUpDown
              className={cn("size-4 shrink-0", dark ? "text-primary" : "text-muted-foreground")}
              strokeWidth={1.75}
              aria-hidden
            />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-[16rem]">
          <DropdownMenuLabel>Your brands</DropdownMenuLabel>
          {(brands ?? []).map((brand) => (
            <DropdownMenuItem
              key={brand.id}
              disabled={!canEdit && brand.id !== current?.id}
              onSelect={() => void switchTo(brand.id)}
            >
              <Check className={brand.id === current?.id ? "text-gold" : "invisible"} aria-hidden />
              <span className="min-w-0">
                <span className="block truncate">{brand.name}</span>
                {brand.industry ? (
                  <span className="block truncate text-xs text-muted-foreground">
                    {brand.industry}
                  </span>
                ) : null}
              </span>
            </DropdownMenuItem>
          ))}
          {canEdit ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setAdding(true)}>
                <Plus aria-hidden />
                <span>Add a brand</span>
              </DropdownMenuItem>
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>

      <AddBrandDialog open={adding} onOpenChange={setAdding} />
    </>
  );
}

function AddBrandDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [saving, setSaving] = useState(false);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const brand = await api<BrandRow>("/api/marketing/brands/", {
        method: "POST",
        body: { name: name.trim(), industry: industry.trim() },
      });
      // Promote, then reload: the hub sends an untaught brand to setup.
      await makeCurrent(brand.id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the brand.");
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (saving ? undefined : onOpenChange(next))}>
      <DialogContent>
        <form onSubmit={create}>
          <DialogHeader>
            <DialogTitle>Add a brand</DialogTitle>
            <DialogDescription>
              A brand has its own knowledge, references, rules and content. Your connected accounts
              and team are shared across brands.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-5 space-y-4">
            <div>
              <Label htmlFor="new-brand-name" className="text-xs tracking-wide uppercase">
                Brand name
              </Label>
              <Input
                id="new-brand-name"
                autoFocus
                required
                className="mt-1.5"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={saving}
              />
            </div>
            <div>
              <Label htmlFor="new-brand-industry" className="text-xs tracking-wide uppercase">
                Industry
              </Label>
              <Input
                id="new-brand-industry"
                className="mt-1.5"
                placeholder="Optional"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                disabled={saving}
              />
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving || !name.trim()}>
              {saving ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
              Add and set up
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

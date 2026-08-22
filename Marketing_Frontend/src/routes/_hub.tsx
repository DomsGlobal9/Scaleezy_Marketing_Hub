import { createFileRoute, Link, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  Brain,
  CheckCircle2,
  ChevronsUpDown,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Send,
  Settings,
  ShieldCheck,
  Share2,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
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
import { Skeleton } from "@/components/ui/skeleton";
import { SiteFooter } from "@/components/marketing/site-footer";
import { api, apiPost } from "@/lib/api";
import { readActiveWorkspaceId, setActiveWorkspaceId } from "@/lib/workspace";

export const Route = createFileRoute("/_hub")({
  // The guard below reads localStorage, which does not exist during SSR.
  // Without ssr:false the server would evaluate beforeLoad as "signed out" and
  // the client would never re-run it, bouncing signed-in users to /login on
  // every refresh. This cascades to every hub page and nothing else —
  // /privacy and /terms are root siblings and stay server-rendered.
  ssr: false,
  beforeLoad: ({ context, location, preload }) => {
    // Preloads must not trigger navigation side effects.
    if (preload) return;
    if (!context.auth.isAuthenticated()) {
      throw redirect({
        to: "/login",
        search: { redirect: location.href },
        replace: true,
      });
    }
  },
  // Under ssr:false the subtree renders inside a ClientOnly boundary whose
  // fallback is null by default — without this the hub is a blank page on
  // every load.
  pendingComponent: HubSkeleton,
  component: HubLayout,
});

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, adminOnly: false },
  { to: "/brand-master", label: "Brand Master", icon: Brain, adminOnly: false },
  { to: "/accounts", label: "Social Media Accounts", icon: Share2, adminOnly: false },
  { to: "/publishing", label: "Publishing", icon: Send, adminOnly: false },
  { to: "/review", label: "Review", icon: CheckCircle2, adminOnly: false },
  { to: "/analytics", label: "Analytics", icon: BarChart3, adminOnly: false },
  { to: "/settings", label: "Settings", icon: Settings, adminOnly: false },
  { to: "/admin", label: "Admin", icon: ShieldCheck, adminOnly: true },
] as const;

function Brand() {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-dark text-gold">
        <Sparkles className="size-4.5" strokeWidth={1.75} />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-display text-lg leading-none font-semibold tracking-tight text-foreground">
          Scaleezy
        </span>
        <span className="mt-1 block text-[0.625rem] tracking-[0.18em] text-muted-foreground uppercase">
          Apparel Commerce
        </span>
      </span>
    </div>
  );
}

function NavList({
  isAdmin,
  onNavigate,
}: {
  isAdmin: boolean;
  onNavigate?: () => void;
}) {
  return (
    <nav className="space-y-1">
      <p className="label-eyebrow mb-3 px-3">Marketing Hub</p>
      {NAV.filter((item) => !item.adminOnly || isAdmin).map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: item.to === "/" }}
          onClick={onNavigate}
          className="group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground data-[status=active]:bg-brand-dark data-[status=active]:text-brand-dark-foreground"
        >
          <span className="absolute top-1/2 left-0 hidden h-6 w-1 -translate-y-1/2 rounded-r-full bg-gold group-data-[status=active]:block" />
          <item.icon
            className="size-4.5 shrink-0 group-data-[status=active]:text-gold"
            strokeWidth={1.75}
          />
          <span className="truncate">{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

/** Shown while the client-only hub subtree resolves after hydration. */
function HubSkeleton() {
  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-[270px] flex-col border-r border-border bg-card px-4 py-6 lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-8 flex-1 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-xl" />
          ))}
        </div>
      </aside>
      <main className="flex min-h-screen flex-col lg:pl-[270px]">
        <div className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-12">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="mt-4 h-4 w-96 max-w-full" />
          <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-32 rounded-xl" />
            ))}
          </div>
        </div>
      </main>
    </div>
  );
}

function SignOutButton({ onDone }: { onDone?: () => void }) {
  const navigate = useNavigate();
  const { auth } = Route.useRouteContext();
  const [busy, setBusy] = useState(false);

  const signOut = async () => {
    setBusy(true);
    const refresh = auth.getRefreshToken();
    try {
      // Best-effort server-side invalidation. The local session is cleared
      // either way — a network failure must never trap someone signed in.
      if (refresh) await apiPost("/api/auth/logout/", { refresh });
    } catch {
      /* ignore */
    } finally {
      auth.signOut();
      setActiveWorkspaceId(null);
      onDone?.();
      // No `redirect` — signing out should land on a clean login screen, not
      // bounce back into the page the user just left.
      await navigate({ to: "/login", search: { redirect: undefined }, replace: true });
    }
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      className="w-full justify-start text-muted-foreground hover:text-foreground"
      onClick={signOut}
      disabled={busy}
    >
      <LogOut className="size-4" /> Sign out
    </Button>
  );
}

interface WorkspaceMembership {
  workspace_id: string;
  workspace_name: string;
  role: string;
  status: string;
}

interface CurrentUser {
  memberships: WorkspaceMembership[];
}

interface CreatedWorkspace {
  id: string;
  workspace_name: string;
}

function ClientSelector({
  onReady,
  instanceId,
}: {
  onReady: (role: string) => void;
  instanceId: "desktop" | "mobile";
}) {
  const [memberships, setMemberships] = useState<WorkspaceMembership[]>([]);
  const [activeId, setActiveId] = useState<string | null>(readActiveWorkspaceId());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void api<CurrentUser>("/api/auth/me/")
      .then((user) => {
        if (cancelled) return;
        const available = user.memberships ?? [];
        const stored = readActiveWorkspaceId();
        const selected = available.some((item) => item.workspace_id === stored)
          ? stored
          : (available[0]?.workspace_id ?? null);
        setMemberships(available);
        setActiveId(selected);
        setActiveWorkspaceId(selected);
        if (selected) {
          onReady(available.find((item) => item.workspace_id === selected)?.role ?? "");
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load clients.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [onReady]);

  const switchClient = (workspaceId: string) => {
    if (!workspaceId || workspaceId === activeId) return;
    setActiveWorkspaceId(workspaceId);
    // A reload is deliberate: it clears every route-local cache and draft so
    // no stale Client A state can be displayed while Client B requests load.
    window.location.reload();
  };

  const createClient = async () => {
    const workspaceName = name.trim();
    if (!workspaceName) {
      setError("Enter a client name.");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const created = await apiPost<CreatedWorkspace>("/api/marketing/workspaces/", {
        workspace_name: workspaceName,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      setActiveWorkspaceId(created.id);
      window.location.assign("/brand-master?tab=teach");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the client.");
      setCreating(false);
    }
  };

  return (
    <>
      <div className="mb-5 border-b border-border pb-5">
        <Label htmlFor={`active-client-${instanceId}`} className="label-eyebrow px-1">
          Active client
        </Label>
        <div className="relative mt-2">
          <select
            id={`active-client-${instanceId}`}
            value={activeId ?? ""}
            disabled={loading || memberships.length === 0}
            onChange={(event) => switchClient(event.target.value)}
            className="h-10 w-full appearance-none rounded-xl border border-border bg-background px-3 pr-9 text-sm font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {memberships.length === 0 ? <option value="">No client selected</option> : null}
            {memberships.map((membership) => (
              <option key={membership.workspace_id} value={membership.workspace_id}>
                {membership.workspace_name}
              </option>
            ))}
          </select>
          <ChevronsUpDown className="pointer-events-none absolute top-3 right-3 size-4 text-muted-foreground" />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2 w-full justify-start"
          onClick={() => {
            setError("");
            setDialogOpen(true);
          }}
        >
          <Plus className="size-4" /> Add Client
        </Button>
        {error && !dialogOpen ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add a client</DialogTitle>
            <DialogDescription>
              Scaleezy will create an isolated workspace, Brand Master, and AI routing ready for onboarding.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor={`new-client-name-${instanceId}`}>Client name</Label>
            <Input
              id={`new-client-name-${instanceId}`}
              value={name}
              autoFocus
              maxLength={255}
              placeholder="Acme Fashion"
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void createClient();
              }}
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} disabled={creating}>
              Cancel
            </Button>
            <Button onClick={() => void createClient()} disabled={creating || !name.trim()}>
              {creating ? "Creating…" : "Create client"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function HubLayout() {
  const [open, setOpen] = useState(false);
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [activeRole, setActiveRole] = useState("");

  const markWorkspaceReady = useCallback((role: string) => {
    setActiveRole(role);
    setWorkspaceReady(true);
  }, []);
  const isAdmin = activeRole === "OWNER" || activeRole === "ADMIN";

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-[270px] flex-col border-r border-border bg-card px-4 py-6 lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-8 flex-1">
          <ClientSelector onReady={markWorkspaceReady} instanceId="desktop" />
          <NavList isAdmin={isAdmin} />
        </div>
        <div>
          <SignOutButton />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-card/95 px-4 py-3 backdrop-blur lg:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="outline" size="icon" aria-label="Open navigation">
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-[85vw] max-w-[300px] bg-card px-4 py-6">
            <SheetTitle className="sr-only">Marketing Hub navigation</SheetTitle>
            <Brand />
            <div className="mt-8">
              <ClientSelector onReady={markWorkspaceReady} instanceId="mobile" />
              <NavList isAdmin={isAdmin} onNavigate={() => setOpen(false)} />
            </div>
            <div className="mt-6 border-t border-border pt-4">
              <SignOutButton onDone={() => setOpen(false)} />
            </div>
          </SheetContent>
        </Sheet>
        <Brand />
      </header>

      <main className="flex min-h-screen flex-col lg:pl-[270px]">
        <div className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-8 sm:px-6 lg:px-10 lg:py-12">
          {workspaceReady ? (
            <Outlet />
          ) : (
            <div className="mx-auto max-w-xl rounded-2xl border border-border bg-card p-8 text-center">
              <h1 className="font-display text-2xl font-semibold text-foreground">
                Select or add a client
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Client context is required before Scaleezy can load brand, content, or publishing data.
              </p>
            </div>
          )}
        </div>
        <SiteFooter />
      </main>
    </div>
  );
}

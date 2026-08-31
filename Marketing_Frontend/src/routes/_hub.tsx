import { createFileRoute, Link, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  Brain,
  Check,
  CheckCircle2,
  ChevronsUpDown,
  Landmark,
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
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AddClientDialog } from "@/components/marketing/add-client-dialog";
import { SiteFooter } from "@/components/marketing/site-footer";
import { apiPost } from "@/lib/api";
import { clearWorkspaces, loadWorkspaces, selectWorkspace, useWorkspaces } from "@/lib/workspace";

export const Route = createFileRoute("/_hub")({
  // The guard below reads localStorage, which does not exist during SSR.
  // Without ssr:false the server would evaluate beforeLoad as "signed out" and
  // the client would never re-run it, bouncing signed-in users to /login on
  // every refresh. This cascades to every hub page and nothing else —
  // /privacy and /terms are root siblings and stay server-rendered.
  ssr: false,
  beforeLoad: async ({ context, location, preload }) => {
    if (!context.auth.isAuthenticated()) {
      // Preloads must not trigger navigation side effects.
      if (preload) return;
      throw redirect({
        to: "/login",
        search: { redirect: location.href },
        replace: true,
      });
    }

    // beforeLoad is the only serial, parent-first hook — child `loader`s all
    // fire in parallel after it. Awaiting the membership list here is what
    // stops a hub page requesting data for a workspace the user has left, or
    // (with more than one client and nothing stored) with no workspace at all,
    // which the backend answers with 400 NO_WORKSPACE. Preloads await it too:
    // the result is cached for the document, so it costs one request.
    await loadWorkspaces();
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
  // Named for the object, not for one stage of its lifecycle: this is where
  // every piece of work lives, whatever state it is in.
  { to: "/review", label: "Content", icon: CheckCircle2, adminOnly: false },
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

/**
 * "+ Add Client" — the trigger only.
 *
 * The dialog itself is a sibling of the DropdownMenu rather than a child of it:
 * Radix unmounts the menu content on close, so a dialog rendered in here would
 * be torn down by the very click that opened it.
 */
function WorkspaceAddClientSlot({
  first,
  onSelected,
}: {
  /** No clients at all — the menu has nothing else to say, so say this. */
  first: boolean;
  onSelected: () => void;
}) {
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={onSelected}>
        <Plus aria-hidden />
        <span>{first ? "Add your first client" : "Add client"}</span>
      </DropdownMenuItem>
    </>
  );
}

function workspaceLabel(state: ReturnType<typeof useWorkspaces>): string {
  const current = state.workspaces.find((w) => w.id === state.selectedId);
  if (current) return current.name;
  if (state.status === "loading" || state.status === "idle") return "Loading clients…";
  if (state.status === "error") return "Clients unavailable";
  return "No client yet";
}

function WorkspaceSwitcher({
  onNavigate,
  onAddClient,
}: {
  onNavigate?: () => void;
  onAddClient: () => void;
}) {
  const state = useWorkspaces();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={state.switching}
          className="flex w-full items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-left transition-colors hover:bg-secondary disabled:opacity-60"
        >
          <span className="min-w-0 flex-1">
            <span className="label-eyebrow block">Client</span>
            <span className="mt-0.5 block truncate text-sm font-medium text-foreground">
              {workspaceLabel(state)}
            </span>
          </span>
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-[var(--radix-dropdown-menu-trigger-width)]">
        <DropdownMenuLabel>Switch client</DropdownMenuLabel>
        {state.workspaces.length === 0 ? (
          <DropdownMenuItem disabled>
            {state.status === "error" ? "Clients unavailable" : "No clients yet"}
          </DropdownMenuItem>
        ) : (
          state.workspaces.map((workspace) => (
            <DropdownMenuItem
              key={workspace.id}
              onSelect={() => {
                onNavigate?.();
                selectWorkspace(workspace.id);
              }}
            >
              <Check
                className={workspace.id === state.selectedId ? "text-gold" : "invisible"}
                aria-hidden
              />
              <span className="truncate">{workspace.name}</span>
            </DropdownMenuItem>
          ))
        )}
        <WorkspaceAddClientSlot
          first={state.workspaces.length === 0}
          onSelected={() => {
            // Closes the mobile Sheet first. The dialog lives up in HubLayout
            // precisely so that closing this menu — or the Sheet holding it —
            // cannot unmount the wizard mid-creation.
            onNavigate?.();
            onAddClient();
          }}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * Covers the page opaquely between committing a switch and the document being
 * replaced, so the outgoing client's rows cannot be read or clicked while the
 * new tenant loads.
 */
function WorkspaceSwitchOverlay() {
  const { switching } = useWorkspaces();
  if (!switching) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-background"
      role="status"
      aria-live="polite"
    >
      <p className="text-sm text-muted-foreground">Switching client…</p>
    </div>
  );
}

/**
 * Nothing to address yet.
 *
 * Rendered in place of the page, not beside it: with no membership every hub
 * request answers 400 NO_WORKSPACE, so the alternative is six panels each
 * reporting the same failure in its own words. Only shown once the server has
 * actually said the list is empty — "loading" and "error" are not "none".
 */
function NoClientsYet({ onAddClient }: { onAddClient: () => void }) {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div className="max-w-md text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
          <Sparkles className="size-6" strokeWidth={1.5} />
        </span>
        <h2 className="mt-4 font-display text-xl font-semibold text-foreground">No clients yet</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          A client is a workspace of its own — brand, knowledge, content and channels, shared with
          nothing else. Create one and setup starts straight away.
        </p>
        <Button className="mt-5" onClick={onAddClient}>
          <Plus className="size-4" /> Add your first client
        </Button>
      </div>
    </div>
  );
}

function NavList({
  isAdmin,
  isPlatformAdmin,
  onNavigate,
}: {
  isAdmin: boolean;
  isPlatformAdmin: boolean;
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
          className="group relative flex min-h-11 items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground data-[status=active]:bg-brand-dark data-[status=active]:text-brand-dark-foreground lg:min-h-0"
        >
          <span className="absolute top-1/2 left-0 hidden h-6 w-1 -translate-y-1/2 rounded-r-full bg-gold group-data-[status=active]:block" />
          <item.icon
            className="size-4.5 shrink-0 group-data-[status=active]:text-gold"
            strokeWidth={1.75}
          />
          <span className="truncate">{item.label}</span>
        </Link>
      ))}
      {isPlatformAdmin ? (
        <>
          <p className="label-eyebrow mt-6 mb-3 px-3">Scaleezy staff</p>
          <Link
            to="/platform"
            onClick={onNavigate}
            className="flex min-h-11 items-center gap-3 rounded-xl border border-slate-300 bg-slate-900 px-3 py-2.5 text-sm font-medium text-slate-100 transition-colors hover:bg-slate-800 lg:min-h-0"
          >
            <Landmark className="size-4.5 shrink-0 text-amber-300" strokeWidth={1.75} />
            <span className="truncate">Platform console</span>
          </Link>
        </>
      ) : null}
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
      // Whoever signs in next on this browser must not inherit this person's
      // client as their default selection.
      clearWorkspaces();
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

function HubLayout() {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const workspaces = useWorkspaces();
  const noClients = workspaces.status === "ready" && workspaces.workspaces.length === 0;
  const activeRole = workspaces.workspaces.find(
    (workspace) => workspace.id === workspaces.selectedId,
  )?.role;
  const isAdmin = activeRole === "OWNER" || activeRole === "ADMIN";
  const isPlatformAdmin = workspaces.isPlatformAdmin;

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-[270px] flex-col border-r border-border bg-card px-4 py-6 lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-6">
          <WorkspaceSwitcher onAddClient={() => setCreating(true)} />
        </div>
        <div className="mt-6 flex-1">
          <NavList isAdmin={isAdmin} isPlatformAdmin={isPlatformAdmin} />
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
            <div className="mt-6">
              <WorkspaceSwitcher
                onNavigate={() => setOpen(false)}
                onAddClient={() => setCreating(true)}
              />
            </div>
            <div className="mt-6">
              <NavList
                isAdmin={isAdmin}
                isPlatformAdmin={isPlatformAdmin}
                onNavigate={() => setOpen(false)}
              />
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
          {noClients ? <NoClientsYet onAddClient={() => setCreating(true)} /> : <Outlet />}
        </div>
        <SiteFooter />
      </main>

      <AddClientDialog open={creating} onOpenChange={setCreating} onCreated={selectWorkspace} />
      <WorkspaceSwitchOverlay />
    </div>
  );
}

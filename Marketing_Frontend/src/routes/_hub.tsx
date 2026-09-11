import { createFileRoute, Link, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  Brain,
  CheckCircle2,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Menu,
  Plus,
  Send,
  Settings,
  ShieldCheck,
  Share2,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { SiteFooter } from "@/components/marketing/site-footer";
import { apiPost } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fetchMe, type Me } from "@/lib/platform";
import { clearWorkspaces, loadWorkspaces, useWorkspaces } from "@/lib/workspace";

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
  { to: "/overview", label: "Overview", icon: LayoutDashboard, adminOnly: false },
  { to: "/brand-master", label: "Brand Master", icon: Brain, adminOnly: false },
  { to: "/accounts", label: "Social Media Accounts", icon: Share2, adminOnly: false },
  { to: "/publishing", label: "Publishing", icon: Send, adminOnly: false },
  // Named for the object, not for one stage of its lifecycle: this is where
  // every piece of work lives, whatever state it is in.
  { to: "/review", label: "Content", icon: CheckCircle2, adminOnly: false },
  { to: "/growth", label: "Engagement", icon: MessagesSquare, adminOnly: false },
  { to: "/analytics", label: "Analytics", icon: BarChart3, adminOnly: false },
  { to: "/settings", label: "Settings", icon: Settings, adminOnly: false },
  { to: "/admin", label: "Admin", icon: ShieldCheck, adminOnly: true },
] as const;

function Brand() {
  return (
    <span className="flex min-w-0 items-center">
      <ScaleezyLogo className="w-[10.75rem]" priority />
    </span>
  );
}

/**
 * Who is signed in. The client is implied — a person has one workspace — so
 * the top bar names the person, not the tenant.
 */
function SignedInAs({ dark = false }: { dark?: boolean }) {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    let cancelled = false;
    void fetchMe().then((value) => {
      if (!cancelled) setMe(value);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const name = me ? [me.first_name, me.last_name].filter(Boolean).join(" ") || me.username : "…";
  return (
    <span className="flex min-w-0 items-center gap-3">
      <span
        className={cn(
          "grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold",
          dark ? "bg-primary/20 text-primary" : "bg-primary/10 text-primary",
        )}
        aria-hidden
      >
        {name.charAt(0).toUpperCase()}
      </span>
      <span className="min-w-0">
        <span
          className={cn(
            "block text-[0.625rem] font-semibold tracking-[0.14em] uppercase",
            dark ? "text-white/45" : "text-muted-foreground",
          )}
        >
          Signed in as
        </span>
        <span className={cn("block truncate text-sm font-semibold", dark && "text-white")}>
          {name}
        </span>
      </span>
    </span>
  );
}

/**
 * Nothing to address yet.
 *
 * Rendered in place of the page, not beside it: with no membership every hub
 * request answers 400 NO_WORKSPACE, so the alternative is six panels each
 * reporting the same failure in its own words. Only shown once the server has
 * actually said the list is empty — "loading" and "error" are not "none".
 * Clients are opened by Scaleezy, so there is nothing for the person to click.
 */
function NoClientsYet() {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <div className="max-w-md text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
          <Sparkles className="size-6" strokeWidth={1.5} />
        </span>
        <h2 className="mt-4 font-display text-xl font-semibold text-foreground">
          No workspace yet
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Your account is not attached to a client workspace. Scaleezy sets one up for you — if you
          signed up recently it is being reviewed; otherwise contact your administrator.
        </p>
      </div>
    </div>
  );
}

function NavList({ isAdmin, onNavigate }: { isAdmin: boolean; onNavigate?: () => void }) {
  return (
    <nav className="space-y-1" aria-label="Marketing Hub">
      <p className="mb-3 px-3 text-[0.625rem] font-semibold tracking-[0.16em] text-white/35 uppercase">
        Marketing Hub
      </p>
      {NAV.filter((item) => !item.adminOnly || isAdmin).map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: false }}
          onClick={onNavigate}
          className={cn(
            "group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-white/65 transition-colors hover:bg-white/8 hover:text-white data-[status=active]:bg-white/6 data-[status=active]:text-primary",
            item.to === "/settings" && "mt-6 border-t border-white/12 pt-5",
          )}
        >
          <span className="absolute top-1/2 -left-3 hidden h-8 w-1 -translate-y-1/2 rounded-r-full bg-primary group-data-[status=active]:block" />
          <item.icon
            className="size-5 shrink-0 group-data-[status=active]:text-primary"
            strokeWidth={1.75}
          />
          <span
            className={cn(
              "min-w-0 leading-snug",
              item.to === "/accounts" ? "whitespace-normal" : "truncate",
            )}
          >
            {item.label}
          </span>
        </Link>
      ))}
    </nav>
  );
}

/** Shown while the client-only hub subtree resolves after hydration. */
function HubSkeleton() {
  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-[236px] flex-col bg-brand-dark px-4 py-5 lg:flex">
        <div className="flex h-12 items-center px-2">
          <Brand />
        </div>
        <div className="mt-8 flex-1 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-xl" />
          ))}
        </div>
      </aside>
      <main className="flex min-h-screen flex-col lg:pl-[236px]">
        <div className="hidden h-[82px] bg-brand-dark lg:block" />
        <div className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-8 sm:px-6 lg:px-12 lg:py-12">
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

function SignOutButton({ onDone, dark = false }: { onDone?: () => void; dark?: boolean }) {
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
      className={cn(
        "w-full justify-start",
        dark ? "text-white/55 hover:bg-white/8 hover:text-white" : "text-muted-foreground",
      )}
      onClick={signOut}
      disabled={busy}
    >
      <LogOut className="size-4" /> Sign out
    </Button>
  );
}

function DesktopTopBar() {
  return (
    <header className="sticky top-0 z-30 hidden h-[82px] items-center gap-6 border-b border-white/10 bg-brand-dark px-8 text-white lg:flex xl:px-12">
      <SignedInAs dark />
      <div className="ml-auto">
        <Button asChild size="lg" className="h-11">
          <Link to="/publishing">
            <Plus className="size-4" /> Create content
          </Link>
        </Button>
      </div>
    </header>
  );
}

function HubLayout() {
  const [open, setOpen] = useState(false);
  const workspaces = useWorkspaces();
  const noClients = workspaces.status === "ready" && workspaces.workspaces.length === 0;
  const activeRole = workspaces.workspaces.find(
    (workspace) => workspace.id === workspaces.selectedId,
  )?.role;
  const isAdmin = activeRole === "OWNER" || activeRole === "ADMIN";

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[236px] flex-col bg-brand-dark px-4 py-5 text-white lg:flex">
        <div className="flex h-12 items-center px-2">
          <Brand />
        </div>
        <div className="mt-7 flex-1 overflow-y-auto">
          <NavList isAdmin={isAdmin} />
        </div>
        <div className="border-t border-white/12 pt-4">
          <p className="mb-3 px-3 text-[0.625rem] tracking-[0.14em] text-white/35 uppercase">
            Scaleezy Marketing Hub
          </p>
          <SignOutButton dark />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-white/10 bg-brand-dark px-4 text-white lg:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="text-white hover:bg-white/10 hover:text-primary"
              aria-label="Open navigation"
            >
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent
            side="left"
            className="w-[88vw] max-w-[320px] border-white/10 bg-brand-dark px-4 py-5 text-white [&>button]:text-white"
          >
            <SheetTitle className="sr-only">Marketing Hub navigation</SheetTitle>
            <Brand />
            <div className="mt-6">
              <SignedInAs dark />
            </div>
            <div className="mt-6">
              <NavList isAdmin={isAdmin} onNavigate={() => setOpen(false)} />
            </div>
            <div className="mt-6 border-t border-white/12 pt-4">
              <SignOutButton dark onDone={() => setOpen(false)} />
            </div>
          </SheetContent>
        </Sheet>
        <Brand />
        <Button asChild size="sm" className="ml-auto">
          <Link to="/publishing" aria-label="Create content">
            <Plus className="size-4" aria-hidden />
            <span className="hidden sm:inline">Create</span>
          </Link>
        </Button>
      </header>

      <main className="flex min-h-screen flex-col lg:pl-[236px]">
        <DesktopTopBar />
        <div className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-8 sm:px-6 lg:px-12 lg:py-12">
          {noClients ? <NoClientsYet /> : <Outlet />}
        </div>
        <SiteFooter />
      </main>
    </div>
  );
}

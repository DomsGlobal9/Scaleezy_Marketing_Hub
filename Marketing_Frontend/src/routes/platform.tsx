/**
 * Scaleezy Platform Console — a separate route tree with its own chrome.
 *
 * A staff member usually also belongs to a client workspace, so the console
 * must never look like the hub: dark slate top bar, its own left nav, and a
 * persistent PLATFORM MODE badge with a link back. The guard here only decides
 * whether to SHOW the console — every /api/platform/ request is re-gated on
 * the server by IsPlatformAdmin, so nothing client-side is a grant.
 */
import { createFileRoute, Link, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import {
  Activity,
  ArrowLeft,
  BookMarked,
  Building2,
  Inbox,
  Library,
  LogOut,
  Menu,
  Network,
  ShieldCheck,
  UserCog,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { apiPost } from "@/lib/api";
import { clearMeCache, fetchMe, type Me } from "@/lib/platform";
import { clearWorkspaces } from "@/lib/workspace";

export const Route = createFileRoute("/platform")({
  // Same reason as /_hub: the session lives in localStorage, which does not
  // exist during SSR.
  ssr: false,
  beforeLoad: async ({ context, location, preload }) => {
    if (!context.auth.isAuthenticated()) {
      if (preload) return;
      throw redirect({ to: "/login", search: { redirect: location.href }, replace: true });
    }
    const me = await fetchMe();
    if (!me?.is_platform_admin) {
      if (preload) return;
      // Not a platform admin: back to the hub, silently. The server would 403
      // every console request anyway; this just saves the empty page.
      throw redirect({ to: "/", replace: true });
    }
  },
  head: () => ({
    meta: [{ title: "Platform Console — Scaleezy" }, { name: "robots", content: "noindex" }],
  }),
  pendingComponent: ConsoleSkeleton,
  component: ConsoleLayout,
});

const NAV = [
  { to: "/platform", label: "Overview", icon: Activity, exact: true },
  { to: "/platform/signups", label: "Signups", icon: Inbox, exact: false },
  { to: "/platform/clients", label: "Clients", icon: Building2, exact: false },
  { to: "/platform/standards", label: "Standards", icon: BookMarked, exact: false },
  { to: "/platform/patterns", label: "Learned patterns", icon: Network, exact: false },
  { to: "/platform/library", label: "Library", icon: Library, exact: false },
  { to: "/platform/admins", label: "Admins", icon: UserCog, exact: false },
] as const;

function ConsoleNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="space-y-1">
      <p className="mb-3 px-3 text-[0.6875rem] font-semibold tracking-[0.14em] text-slate-500 uppercase">
        Console
      </p>
      {NAV.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: item.exact }}
          onClick={onNavigate}
          className="group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-200/70 hover:text-slate-900 data-[status=active]:bg-slate-900 data-[status=active]:text-white lg:min-h-0"
        >
          <item.icon className="size-4 shrink-0" strokeWidth={1.75} />
          <span className="truncate">{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function ModeBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-400/50 bg-amber-400/15 px-2.5 py-0.5 text-[0.625rem] font-bold tracking-[0.16em] text-amber-200 uppercase">
      <ShieldCheck className="size-3" /> Platform mode
    </span>
  );
}

function TopBar({ onOpenMenu }: { onOpenMenu?: () => void }) {
  // Already resolved (and cached) by beforeLoad; this is a synchronous-feeling
  // read of the same promise, never a second request.
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
  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900 text-slate-100">
      <div className="flex items-center gap-3 px-4 py-2.5 sm:px-6">
        {onOpenMenu ? (
          <Button
            variant="ghost"
            size="icon"
            className="text-slate-100 hover:bg-slate-800 hover:text-white lg:hidden"
            aria-label="Open console navigation"
            onClick={onOpenMenu}
          >
            <Menu className="size-5" />
          </Button>
        ) : null}
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-slate-700 text-amber-300">
          <ShieldCheck className="size-4" strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight">Scaleezy Platform Console</p>
          <p className="hidden truncate text-[0.6875rem] text-slate-400 sm:block">
            Signed in as {me?.username ?? "—"} · every action here is audited
          </p>
        </div>
        <ModeBadge />
        <Link
          to="/"
          className="hidden items-center gap-1.5 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-800 sm:inline-flex"
        >
          <ArrowLeft className="size-3.5" /> Back to hub
        </Link>
      </div>
    </header>
  );
}

function SignOut({ onDone }: { onDone?: () => void }) {
  const navigate = useNavigate();
  const { auth } = Route.useRouteContext();
  const [busy, setBusy] = useState(false);
  const signOut = async () => {
    setBusy(true);
    const refresh = auth.getRefreshToken();
    try {
      if (refresh) await apiPost("/api/auth/logout/", { refresh });
    } catch {
      /* local session is cleared either way */
    } finally {
      auth.signOut();
      clearWorkspaces();
      clearMeCache();
      onDone?.();
      await navigate({ to: "/login", search: { redirect: undefined }, replace: true });
    }
  };
  return (
    <Button
      variant="ghost"
      size="sm"
      className="w-full justify-start text-slate-600 hover:text-slate-900"
      onClick={() => void signOut()}
      disabled={busy}
    >
      <LogOut className="size-4" /> Sign out
    </Button>
  );
}

function ConsoleSkeleton() {
  return (
    <div className="min-h-screen bg-slate-50">
      <div className="h-[53px] border-b border-slate-800 bg-slate-900" />
      <div className="mx-auto grid max-w-[1500px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <div className="hidden space-y-2 lg:block">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full rounded-lg" />
          ))}
        </div>
        <div>
          <Skeleton className="h-8 w-64" />
          <Skeleton className="mt-3 h-4 w-96 max-w-full" />
          <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ConsoleLayout() {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-screen bg-slate-50 text-foreground">
      <TopBar onOpenMenu={() => setOpen(true)} />
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <span className="hidden" />
        </SheetTrigger>
        <SheetContent side="left" className="w-[85vw] max-w-[280px] bg-slate-50 px-4 py-6">
          <SheetTitle className="sr-only">Console navigation</SheetTitle>
          <div className="mb-4">
            <ModeBadge />
          </div>
          <ConsoleNav onNavigate={() => setOpen(false)} />
          <div className="mt-6 space-y-2 border-t border-slate-200 pt-4">
            <Button variant="ghost" size="sm" className="w-full justify-start" asChild>
              <Link to="/" onClick={() => setOpen(false)}>
                <ArrowLeft className="size-4" /> Back to hub
              </Link>
            </Button>
            <SignOut onDone={() => setOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>

      <div className="mx-auto grid max-w-[1500px] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="hidden lg:block">
          <div className="sticky top-[69px] flex flex-col gap-6">
            <ConsoleNav />
            <div className="border-t border-slate-200 pt-4">
              <SignOut />
            </div>
          </div>
        </aside>
        <main className="min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

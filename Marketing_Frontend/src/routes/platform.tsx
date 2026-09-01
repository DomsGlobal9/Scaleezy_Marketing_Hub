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
import { ScaleezyLogo } from "@/components/marketing/brand-logo";
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
    <nav className="space-y-1" aria-label="Platform console">
      <p className="mb-3 px-3 text-[0.625rem] font-semibold tracking-[0.16em] text-white/35 uppercase">
        Console
      </p>
      {NAV.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          activeOptions={{ exact: item.exact }}
          onClick={onNavigate}
          className="group relative flex min-h-11 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-white/65 transition-colors hover:bg-white/8 hover:text-white data-[status=active]:bg-white/6 data-[status=active]:text-primary"
        >
          <span className="absolute top-1/2 -left-3 hidden h-8 w-1 -translate-y-1/2 rounded-r-full bg-primary group-data-[status=active]:block" />
          <item.icon className="size-5 shrink-0" strokeWidth={1.75} />
          <span className="truncate">{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function ModeBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/45 bg-primary/10 px-2.5 py-1 text-[0.625rem] font-bold tracking-[0.16em] text-primary uppercase">
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
    <header className="sticky top-0 z-30 h-[72px] border-b border-white/10 bg-brand-dark text-white">
      <div className="flex h-full items-center gap-4 px-4 sm:px-6 lg:px-8">
        {onOpenMenu ? (
          <Button
            variant="ghost"
            size="icon"
            className="text-white hover:bg-white/10 hover:text-primary lg:hidden"
            aria-label="Open console navigation"
            onClick={onOpenMenu}
          >
            <Menu className="size-5" />
          </Button>
        ) : null}
        <ScaleezyLogo className="hidden w-[9.5rem] sm:block" priority />
        <span className="hidden h-7 w-px bg-white/15 sm:block" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight">Platform Console</p>
          <p className="hidden truncate text-[0.6875rem] text-white/45 md:block">
            Signed in as {me?.username ?? "—"} · every action here is audited
          </p>
        </div>
        <ModeBadge />
        <Link
          to="/"
          className="hidden items-center gap-1.5 rounded-lg border border-white/15 px-3 py-2 text-xs font-semibold text-white/70 transition-colors hover:border-primary/60 hover:text-primary sm:inline-flex"
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
      className="w-full justify-start text-white/55 hover:bg-white/8 hover:text-white"
      onClick={() => void signOut()}
      disabled={busy}
    >
      <LogOut className="size-4" /> Sign out
    </Button>
  );
}

function ConsoleSkeleton() {
  return (
    <div className="min-h-screen bg-background">
      <div className="h-[72px] border-b border-white/10 bg-brand-dark" />
      <aside className="fixed inset-y-[72px] left-0 hidden w-[236px] bg-brand-dark px-4 py-6 lg:block">
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-11 w-full bg-white/10" />
          ))}
        </div>
      </aside>
      <div className="px-4 py-8 sm:px-6 lg:ml-[236px] lg:px-12 lg:py-12">
        <div className="mx-auto max-w-[1500px]">
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
    <div className="min-h-screen bg-background text-foreground">
      <TopBar onOpenMenu={() => setOpen(true)} />
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <span className="hidden" />
        </SheetTrigger>
        <SheetContent
          side="left"
          className="w-[88vw] max-w-[320px] border-white/10 bg-brand-dark px-4 py-6 text-white [&>button]:text-white"
        >
          <SheetTitle className="sr-only">Console navigation</SheetTitle>
          <ScaleezyLogo className="mb-5 w-[10rem]" />
          <div className="mb-6">
            <ModeBadge />
          </div>
          <ConsoleNav onNavigate={() => setOpen(false)} />
          <div className="mt-6 space-y-2 border-t border-white/12 pt-4">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-white/60 hover:bg-white/8 hover:text-white"
              asChild
            >
              <Link to="/" onClick={() => setOpen(false)}>
                <ArrowLeft className="size-4" /> Back to hub
              </Link>
            </Button>
            <SignOut onDone={() => setOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>

      <aside className="fixed inset-y-[72px] left-0 hidden w-[236px] flex-col bg-brand-dark px-4 py-6 lg:flex">
        <div className="flex flex-1 flex-col gap-6 overflow-y-auto">
          <ConsoleNav />
          <div className="mt-auto border-t border-white/12 pt-4">
            <SignOut />
          </div>
        </div>
      </aside>
      <main className="min-w-0 px-4 py-8 sm:px-6 lg:ml-[236px] lg:px-12 lg:py-12">
        <div className="mx-auto max-w-[1500px]">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

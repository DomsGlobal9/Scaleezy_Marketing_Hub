import { createFileRoute, Link, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  Brain,
  CheckCircle2,
  LayoutDashboard,
  LogOut,
  Menu,
  Send,
  Settings,
  Share2,
  Sparkles,
} from "lucide-react";
import { useState } from "react";

import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SiteFooter } from "@/components/marketing/site-footer";
import { apiPost } from "@/lib/api";

export const Route = createFileRoute("/_hub")({
  // The guard below reads localStorage, which does not exist during SSR.
  // Without ssr:false the server would evaluate beforeLoad as "signed out" and
  // the client would never re-run it, bouncing signed-in users to /login on
  // every refresh. This cascades to all five hub pages and nothing else —
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
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/brand-master", label: "Brand Master", icon: Brain },
  { to: "/accounts", label: "Social Media Accounts", icon: Share2 },
  { to: "/publishing", label: "Publishing", icon: Send },
  { to: "/review", label: "Review", icon: CheckCircle2 },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
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

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="space-y-1">
      <p className="label-eyebrow mb-3 px-3">Marketing Hub</p>
      {NAV.map((item) => (
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

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-[270px] flex-col border-r border-border bg-card px-4 py-6 lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-8 flex-1">
          <NavList />
        </div>
        <div className="rounded-xl border border-border bg-secondary/60 p-3">
          <p className="text-xs font-medium text-foreground">Shared Intelligence Layer</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            CRM, Inventory, Analytics, Finance and Try-On signals feed this hub.
          </p>
        </div>
        <div className="mt-2">
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
              <NavList onNavigate={() => setOpen(false)} />
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
          <Outlet />
        </div>
        <SiteFooter />
      </main>
    </div>
  );
}

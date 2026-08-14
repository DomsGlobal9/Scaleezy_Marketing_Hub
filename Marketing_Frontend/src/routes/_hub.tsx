import { createFileRoute, Link, Outlet } from "@tanstack/react-router";
import { BarChart3, LayoutDashboard, Menu, Send, Settings, Share2, Sparkles } from "lucide-react";
import { useState } from "react";

import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { SiteFooter } from "@/components/marketing/site-footer";

export const Route = createFileRoute("/_hub")({
  component: HubLayout,
});

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/accounts", label: "Social Media Accounts", icon: Share2 },
  { to: "/publishing", label: "Publishing", icon: Send },
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

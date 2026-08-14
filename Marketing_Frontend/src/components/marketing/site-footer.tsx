import { Link } from "@tanstack/react-router";

const LEGAL_LINKS = [
  { to: "/privacy", label: "Privacy Policy" },
  { to: "/terms", label: "Terms & Conditions" },
] as const;

/**
 * Site-wide footer. Rendered by the hub layout and by the legal pages, so the
 * links stay reachable from anywhere without touching individual routes.
 */
export function SiteFooter() {
  return (
    <footer className="mt-12 border-t border-border bg-card/40">
      <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-3 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
        <p className="text-xs text-muted-foreground">
          © {new Date().getFullYear()} Scaleezy. All rights reserved.
        </p>
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2">
          {LEGAL_LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}

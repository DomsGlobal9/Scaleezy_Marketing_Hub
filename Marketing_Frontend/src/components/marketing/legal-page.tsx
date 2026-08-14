import { Link } from "@tanstack/react-router";
import { ArrowLeft, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/marketing/site-footer";

/**
 * Shell for the public legal pages. These sit outside the `_hub` layout so they
 * stay reachable without the app chrome — platform app reviews (X, Meta) require
 * a publicly accessible policy URL.
 */
export function LegalPage({
  title,
  updated,
  intro,
  children,
}: {
  title: string;
  updated: string;
  intro: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex w-full max-w-[900px] items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <span className="flex min-w-0 items-center gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-brand-dark text-gold">
              <Sparkles className="size-4.5" strokeWidth={1.75} />
            </span>
            <span className="min-w-0">
              <span className="block truncate font-display text-lg leading-none font-semibold tracking-tight text-foreground">
                Scaleezy
              </span>
              <span className="mt-1 block text-[0.625rem] tracking-[0.18em] text-muted-foreground uppercase">
                Marketing Hub
              </span>
            </span>
          </span>
          <Link
            to="/"
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            <span className="hidden sm:inline">Back to hub</span>
          </Link>
        </div>
      </header>

      <main className="flex-1">
        <div className="mx-auto w-full max-w-[900px] px-4 py-10 sm:px-6 lg:py-14">
          <p className="label-eyebrow">Legal</p>
          <h1 className="mt-2 text-3xl leading-tight font-semibold tracking-tight text-foreground sm:text-4xl">
            {title}
          </h1>
          <p className="mt-3 text-sm text-muted-foreground">Last updated: {updated}</p>
          <p className="mt-5 text-base leading-relaxed text-muted-foreground">{intro}</p>

          <div className="mt-10 space-y-8">{children}</div>
        </div>
      </main>

      <SiteFooter />
    </div>
  );
}

export function LegalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-muted-foreground">{children}</div>
    </section>
  );
}

export function LegalList({ items }: { items: ReactNode[] }) {
  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2.5">
          <span className="mt-2 size-1 shrink-0 rounded-full bg-primary" />
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** Operating entity behind the service. Referenced by both legal pages. */
export const COMPANY = {
  /** Registered entity name, not the Scaleezy brand. */
  legalName: "Doms Global LLP",
  registeredAddress: "Gachibowli INOX Prism Mall, Hyderabad",
  contactEmail: "domsgloballlp@gmail.com",
  jurisdiction: "Hyderabad, Telangana, India",
} as const;

/** Contact address, used wherever the policies say "contact us". */
export function ContactLink() {
  return (
    <a
      href={`mailto:${COMPANY.contactEmail}`}
      className="font-medium text-primary underline underline-offset-4 hover:text-primary/80"
    >
      {COMPANY.contactEmail}
    </a>
  );
}

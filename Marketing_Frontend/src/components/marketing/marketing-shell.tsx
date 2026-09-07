/**
 * The chrome and the shared rhythm of every public marketing page.
 *
 * Extracted from the landing page once there was more than one of them, so the
 * header, the section spacing and the type scale are defined once. A marketing
 * site whose pages each invent their own spacing reads as a set of unrelated
 * documents, which is the opposite of what these pages are for.
 */
import { Link } from "@tanstack/react-router";
import { ArrowRight, Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { SiteFooter } from "@/components/marketing/site-footer";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The public navigation. Each entry is a real page, not an in-page anchor. */
export const MARKETING_NAV = [
  { to: "/how-it-works", label: "How it works" },
  { to: "/capabilities", label: "Capabilities" },
  { to: "/trust", label: "Trust" },
] as const;

/* ------------------------------------------------------------------ */
/* Layout primitives                                                   */
/* ------------------------------------------------------------------ */

/** One page-width column. Every marketing section sits inside exactly one. */
export function Container({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1200px] px-5 sm:px-8 lg:px-12", className)}>
      {children}
    </div>
  );
}

export function Eyebrow({
  children,
  dark = false,
  className,
}: {
  children: ReactNode;
  dark?: boolean;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "text-[0.6875rem] font-semibold tracking-[0.18em] uppercase",
        dark ? "text-primary" : "text-muted-foreground",
        className,
      )}
    >
      {children}
    </p>
  );
}

/** A vertical rhythm unit. `tone` picks the band colour. */
export function Section({
  children,
  id,
  tone = "light",
  className,
}: {
  children: ReactNode;
  id?: string;
  tone?: "light" | "dark" | "muted";
  className?: string;
}) {
  return (
    <section
      {...(id ? { id } : {})}
      className={cn(
        "scroll-mt-24 py-20 sm:py-28",
        tone === "dark" && "bg-brand-dark text-white",
        tone === "muted" && "border-y border-border bg-secondary/60",
        className,
      )}
    >
      <Container>{children}</Container>
    </section>
  );
}

/** The heading block that opens a section: eyebrow, h2, and an optional lede. */
export function SectionHead({
  eyebrow,
  title,
  lede,
  dark = false,
}: {
  eyebrow: string;
  title: string;
  lede?: string;
  dark?: boolean;
}) {
  return (
    <div className="max-w-[42rem]">
      <Eyebrow dark={dark}>{eyebrow}</Eyebrow>
      <h2 className="mt-5 text-3xl leading-[1.1] font-bold tracking-[-0.02em] text-balance sm:text-4xl lg:text-[3.25rem]">
        {title}
      </h2>
      {lede && (
        <p
          className={cn(
            "mt-5 text-lg text-pretty",
            dark ? "text-white/65" : "text-muted-foreground",
          )}
        >
          {lede}
        </p>
      )}
    </div>
  );
}

/**
 * The opening block of a subpage: breadcrumb, h1, lede.
 *
 * Every public page needs exactly one h1 that names its own subject — search
 * and answer engines both use it to decide what the URL is about, and a site
 * where four pages share one h1 competes with itself.
 */
export function PageHero({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  children?: ReactNode;
}) {
  return (
    <section className="relative overflow-hidden border-b border-border">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 h-[30rem] w-[56rem] -translate-x-1/2 rounded-full bg-primary/15 blur-[120px]"
      />
      <Container className="relative py-16 sm:py-20 lg:py-24">
        <nav aria-label="Breadcrumb" className="mb-8">
          <ol className="flex items-center gap-2 text-sm text-muted-foreground">
            <li>
              <Link to="/" className="transition-colors hover:text-foreground">
                Home
              </Link>
            </li>
            <li aria-hidden>/</li>
            <li className="font-medium text-foreground">{eyebrow}</li>
          </ol>
        </nav>
        <div className="max-w-[46rem]">
          <Eyebrow>{eyebrow}</Eyebrow>
          <h1 className="mt-5 text-[2.5rem] leading-[1.06] font-bold tracking-[-0.03em] text-balance sm:text-5xl lg:text-[3.75rem]">
            {title}
          </h1>
          <p className="mt-6 text-lg leading-relaxed text-pretty text-muted-foreground sm:text-xl">
            {lede}
          </p>
        </div>
        {children}
      </Container>
    </section>
  );
}

/**
 * Question-and-answer block.
 *
 * Rendered as a real <dl> and always paired with FAQPage JSON-LD carrying the
 * identical text. The answer opens with a complete, self-contained sentence so
 * it still means something when an assistant quotes it alone.
 */
export function Faq({
  entries,
  tone = "light",
}: {
  entries: readonly { question: string; answer: string }[];
  tone?: "light" | "dark";
}) {
  const dark = tone === "dark";
  return (
    <dl
      className={cn(
        "mt-12 grid gap-px overflow-hidden rounded-2xl border",
        dark ? "border-white/12 bg-white/12" : "border-border bg-border",
      )}
    >
      {entries.map((entry) => (
        <div key={entry.question} className={cn("p-6 sm:p-8", dark ? "bg-brand-dark" : "bg-card")}>
          <dt className={cn("text-lg font-semibold text-balance", dark && "text-white")}>
            {entry.question}
          </dt>
          <dd
            className={cn(
              "mt-3 leading-relaxed text-pretty",
              dark ? "text-white/70" : "text-muted-foreground",
            )}
          >
            {entry.answer}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Emits JSON-LD. Rendered with the body so it always matches what is visible. */
export function JsonLd({ data }: { data: object | object[] }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}

/** The closing call to action shared by every marketing page. */
export function ClosingCta({
  title = "Teach it once. Ship every week.",
  lede = "Start with one brand and one channel. Add the rest when it has earned your trust.",
}: {
  title?: string;
  lede?: string;
}) {
  return (
    <section className="py-20 sm:py-28">
      <Container>
        <div className="relative overflow-hidden rounded-3xl bg-brand-dark px-6 py-16 text-center text-white sm:px-12 sm:py-20">
          <div
            aria-hidden
            className="pointer-events-none absolute -bottom-32 left-1/2 h-80 w-[42rem] -translate-x-1/2 rounded-full bg-primary/25 blur-[100px]"
          />
          <div className="relative mx-auto max-w-[36rem]">
            <h2 className="text-3xl leading-[1.1] font-bold tracking-[-0.02em] text-balance sm:text-[2.75rem]">
              {title}
            </h2>
            <p className="mt-5 text-lg text-pretty text-white/65">{lede}</p>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Button asChild size="lg" className="w-full sm:w-auto">
                <Link to="/signup">
                  Create an account <ArrowRight className="size-4" />
                </Link>
              </Button>
              <Button
                asChild
                variant="outline"
                size="lg"
                className="w-full border-white/25 bg-transparent text-white hover:border-white hover:bg-white hover:text-brand-dark sm:w-auto"
              >
                <Link to="/login" search={{ redirect: undefined }}>
                  Sign in
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </Container>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Header                                                              */
/* ------------------------------------------------------------------ */

/**
 * Dark, like every other navigation shell in the product. Not a style
 * preference: the wordmark asset is white and lime on transparency, so on a
 * light bar the "scale" half disappears into the background entirely.
 */
function SiteHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-brand-dark/95 text-white backdrop-blur-md">
      <Container className="flex h-[72px] items-center gap-6">
        <Link to="/" aria-label="Scaleezy home" className="shrink-0">
          <ScaleezyLogo className="w-[8.5rem] sm:w-[9.75rem]" priority />
        </Link>

        <nav aria-label="Primary" className="ml-auto hidden items-center gap-8 lg:flex">
          {MARKETING_NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="text-sm font-medium text-white/65 transition-colors hover:text-white data-[status=active]:text-primary"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          {/* Hidden on the narrowest screens, where the logo, this, the primary
              action and the menu button together overflow 390px by a few
              pixels. It reappears inside the drawer below, so signing in is
              never more than one tap away. */}
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="hidden text-white/70 hover:bg-white/10 hover:text-white sm:inline-flex"
          >
            <Link to="/login" search={{ redirect: undefined }}>
              Sign in
            </Link>
          </Button>
          <Button asChild size="sm">
            <Link to="/signup">Get started</Link>
          </Button>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="marketing-mobile-nav"
            aria-label={open ? "Close navigation" : "Open navigation"}
            className="grid size-9 place-items-center rounded-lg text-white/70 transition-colors hover:bg-white/10 hover:text-white lg:hidden"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </Container>

      <div
        id="marketing-mobile-nav"
        hidden={!open}
        className="border-t border-white/10 lg:hidden"
        onClick={() => setOpen(false)}
      >
        <Container className="flex flex-col py-2">
          {MARKETING_NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-lg px-3 py-3 text-sm font-medium text-white/75 transition-colors hover:bg-white/8 hover:text-white data-[status=active]:text-primary"
            >
              {item.label}
            </Link>
          ))}
          <Link
            to="/login"
            search={{ redirect: undefined }}
            className="mt-1 mb-1 border-t border-white/10 px-3 pt-4 pb-3 text-sm font-medium text-white/75 transition-colors hover:text-white sm:hidden"
          >
            Sign in
          </Link>
        </Container>
      </div>
    </header>
  );
}

/** Wraps a public page in the shared header, main landmark and footer. */
export function MarketingShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </div>
  );
}

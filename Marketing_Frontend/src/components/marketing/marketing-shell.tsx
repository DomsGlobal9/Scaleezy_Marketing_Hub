/**
 * The chrome and the shared rhythm of every public marketing page.
 *
 * The visual language is editorial rather than dashboard-like: a header that
 * gets out of the way, headlines set far larger than the body, one idea per
 * screen, and long runs of white space between them. Type sizes are fluid
 * (`clamp`) rather than stepped at breakpoints, so a headline is proportionate
 * on a phone and on a wide display without a size for every device in between.
 *
 * Everything here is layout. The pages own their content; this file owns the
 * measure, the scale and the spacing, so four pages read as one publication.
 */
import { Link } from "@tanstack/react-router";
import { ArrowRight, Menu, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { Reveal } from "@/components/marketing/motion";
import { SiteFooter } from "@/components/marketing/site-footer";
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

export function Container({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1240px] px-6 sm:px-10 lg:px-14", className)}>
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
        "text-[0.6875rem] font-semibold tracking-[0.2em] uppercase",
        dark ? "text-primary" : "text-muted-foreground",
        className,
      )}
    >
      {children}
    </p>
  );
}

/**
 * A section. Vertical space is the main tool this design has, so the default
 * is generous and scales with the viewport.
 */
export function Section({
  children,
  id,
  tone = "light",
  className,
  bleed = false,
}: {
  children: ReactNode;
  id?: string;
  tone?: "light" | "dark" | "muted";
  className?: string;
  /** Skip the container, for bands that run edge to edge. */
  bleed?: boolean;
}) {
  return (
    <section
      {...(id ? { id } : {})}
      className={cn(
        "scroll-mt-24 py-24 sm:py-32 lg:py-40",
        tone === "dark" && "bg-brand-dark text-white",
        tone === "muted" && "bg-secondary/50",
        className,
      )}
    >
      {bleed ? children : <Container>{children}</Container>}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Type                                                                */
/* ------------------------------------------------------------------ */

/** The page's own h1. One per page, and the largest thing on it. */
export function DisplayHeading({
  children,
  className,
  as: Tag = "h1",
}: {
  children: ReactNode;
  className?: string;
  as?: "h1" | "h2" | "p";
}) {
  return (
    <Tag
      className={cn(
        "text-[clamp(2.75rem,7.2vw,5.75rem)] leading-[0.98] font-bold tracking-[-0.04em] text-balance",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** A section headline. Smaller than the h1, still far larger than body copy. */
export function SectionHeading({
  children,
  className,
  as: Tag = "h2",
}: {
  children: ReactNode;
  className?: string;
  as?: "h2" | "h3" | "p";
}) {
  return (
    <Tag
      className={cn(
        "text-[clamp(2rem,4.4vw,3.5rem)] leading-[1.03] font-bold tracking-[-0.03em] text-balance",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

export function Lede({
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
        "text-[clamp(1.0625rem,1.5vw,1.375rem)] leading-relaxed text-pretty",
        dark ? "text-white/65" : "text-muted-foreground",
        className,
      )}
    >
      {children}
    </p>
  );
}

/* ------------------------------------------------------------------ */
/* Buttons and links                                                   */
/* ------------------------------------------------------------------ */

const PILL_BASE =
  "inline-flex items-center justify-center gap-2 rounded-full text-[0.6875rem] font-semibold tracking-[0.14em] uppercase transition-colors px-6 py-3.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/** The small, letter-spaced pill this design uses instead of a chunky button. */
export function PillLink({
  to,
  search,
  children,
  variant = "solid",
  className,
}: {
  to: "/signup" | "/login" | "/how-it-works" | "/capabilities" | "/trust";
  search?: { redirect: undefined };
  children: ReactNode;
  variant?: "solid" | "outline" | "onDark";
  className?: string;
}) {
  const styles = {
    solid: "bg-foreground text-background hover:bg-primary hover:text-primary-foreground",
    outline:
      "border border-foreground/25 text-foreground hover:border-foreground hover:bg-foreground hover:text-background",
    onDark:
      "border border-white/30 text-white hover:border-primary hover:bg-primary hover:text-primary-foreground",
  }[variant];

  return (
    <Link to={to} {...(search ? { search } : {})} className={cn(PILL_BASE, styles, className)}>
      {children}
    </Link>
  );
}

/** An inline "keep reading" link. The arrow is part of the idiom. */
export function ArrowLink({
  to,
  children,
  dark = false,
  className,
}: {
  to: "/how-it-works" | "/capabilities" | "/trust" | "/privacy" | "/terms";
  children: ReactNode;
  dark?: boolean;
  className?: string;
}) {
  return (
    <Link
      to={to}
      className={cn(
        "group inline-flex items-center gap-1.5 font-semibold underline-offset-4 hover:underline",
        dark ? "text-primary" : "text-brand-link",
        className,
      )}
    >
      {children}
      <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

/* ------------------------------------------------------------------ */
/* Composition blocks                                                  */
/* ------------------------------------------------------------------ */

/**
 * The tall rounded panel that holds a figure.
 *
 * Where the reference design puts full-bleed photography, this puts a drawn
 * diagram on a tinted ground. There is no honest photograph of what this
 * software does, and a mocked-up dashboard would mean inventing a customer's
 * numbers, so the panel carries a picture of the mechanism instead.
 */
export function MediaPanel({
  children,
  tone = "tint",
  className,
}: {
  children: ReactNode;
  tone?: "tint" | "dark" | "plain";
  className?: string;
}) {
  return (
    <figure
      className={cn(
        "flex min-h-[19rem] items-center justify-center overflow-hidden rounded-[1.75rem] p-8 sm:min-h-[24rem] sm:p-12",
        tone === "tint" && "bg-accent/60 text-foreground",
        tone === "dark" && "bg-brand-dark text-white",
        tone === "plain" && "border border-border bg-card text-foreground",
        className,
      )}
    >
      {children}
    </figure>
  );
}

/**
 * An asymmetric text/figure row that alternates side down the page.
 *
 * Short copy on one side, a figure on the other, with enough space around them
 * that only one row is ever fully in view.
 */
export function FeatureRow({
  eyebrow,
  title,
  body,
  bullets,
  figure,
  flip = false,
  children,
}: {
  eyebrow?: string;
  title: string;
  body: string;
  bullets?: readonly string[];
  figure: ReactNode;
  flip?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-20">
      <Reveal from={flip ? "right" : "left"} className={flip ? "lg:order-2" : undefined}>
        {eyebrow && <Eyebrow className="mb-5">{eyebrow}</Eyebrow>}
        <SectionHeading as="h2">{title}</SectionHeading>
        <Lede className="mt-6">{body}</Lede>
        {bullets && (
          <ul className="mt-8 space-y-3 border-t border-border pt-8">
            {bullets.map((point) => (
              <li key={point} className="flex gap-3 text-[0.9375rem] text-muted-foreground">
                <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />
                <span className="text-pretty">{point}</span>
              </li>
            ))}
          </ul>
        )}
        {children && <div className="mt-8">{children}</div>}
      </Reveal>
      <Reveal from={flip ? "left" : "right"} delay={80} className={flip ? "lg:order-1" : undefined}>
        {figure}
      </Reveal>
    </div>
  );
}

/**
 * A full-bleed dark band carrying one sentence, set as a poster.
 *
 * The reference design uses these to break a long scroll: no navigation, no
 * links, just a statement at a size the rest of the page never reaches.
 */
export function StatementBand({ children, footnote }: { children: ReactNode; footnote?: string }) {
  return (
    <section className="bg-brand-dark py-28 text-white sm:py-36 lg:py-44">
      <Container>
        <Reveal>
          <p className="max-w-[22ch] text-[clamp(2.25rem,6vw,5rem)] leading-[1.02] font-bold tracking-[-0.035em] text-balance">
            {children}
          </p>
          {footnote && <p className="mt-10 max-w-[46ch] text-white/55">{footnote}</p>}
        </Reveal>
      </Container>
    </section>
  );
}

/** The opening block of a subpage: breadcrumb, oversized h1, lede. */
export function PageHero({
  eyebrow,
  title,
  lede,
  figure,
}: {
  eyebrow: string;
  title: ReactNode;
  lede: string;
  figure?: ReactNode;
}) {
  return (
    <section className="border-b border-border pt-14 pb-20 sm:pt-20 sm:pb-28 lg:pb-32">
      <Container>
        <nav aria-label="Breadcrumb" className="mb-12">
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

        <div
          className={cn(
            "grid gap-14",
            figure && "lg:grid-cols-[1.15fr_1fr] lg:items-center lg:gap-20",
          )}
        >
          <Reveal from="none">
            <Eyebrow>{eyebrow}</Eyebrow>
            {/* The display size is measured against the viewport, but with a
                figure alongside it the headline only gets half the width, and
                a viewport-sized clamp then breaks it over five or six lines.
                Step it down when the hero is split. */}
            <DisplayHeading className={cn("mt-6", figure && "text-[clamp(2.25rem,4.4vw,3.75rem)]")}>
              {title}
            </DisplayHeading>
            <Lede className="mt-8 max-w-[44ch]">{lede}</Lede>
          </Reveal>
          {figure && (
            <Reveal from="right" delay={100}>
              {figure}
            </Reveal>
          )}
        </div>
      </Container>
    </section>
  );
}

/** Question-and-answer block, always paired with FAQPage JSON-LD. */
export function Faq({
  entries,
  tone = "light",
}: {
  entries: readonly { question: string; answer: string }[];
  tone?: "light" | "dark";
}) {
  const dark = tone === "dark";
  return (
    <dl className="mt-16 grid gap-0">
      {entries.map((entry, i) => (
        <Reveal
          as="div"
          key={entry.question}
          delay={i * 40}
          className={cn(
            "grid gap-4 border-t py-8 md:grid-cols-[1fr_1.35fr] md:gap-12 md:py-10",
            dark ? "border-white/15" : "border-border",
            i === entries.length - 1 &&
              (dark ? "border-b border-b-white/15" : "border-b border-b-border"),
          )}
        >
          <dt
            className={cn(
              "text-[1.0625rem] leading-snug font-semibold text-balance sm:text-lg",
              dark && "text-white",
            )}
          >
            {entry.question}
          </dt>
          <dd
            className={cn(
              "leading-relaxed text-pretty",
              dark ? "text-white/65" : "text-muted-foreground",
            )}
          >
            {entry.answer}
          </dd>
        </Reveal>
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
    <section className="border-t border-border py-28 sm:py-36">
      <Container>
        <Reveal className="mx-auto max-w-[46rem] text-center">
          <SectionHeading>{title}</SectionHeading>
          <Lede className="mx-auto mt-7 max-w-[42ch]">{lede}</Lede>
          <div className="mt-11 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <PillLink to="/signup">Create an account</PillLink>
            <PillLink to="/login" search={{ redirect: undefined }} variant="outline">
              Sign in
            </PillLink>
          </div>
        </Reveal>
      </Container>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Header                                                              */
/* ------------------------------------------------------------------ */

/**
 * A header that gets out of the way.
 *
 * Transparent over the top of the page and only growing a hairline rule and a
 * blurred backdrop once the reader has scrolled, so the first screen is the
 * headline rather than a navigation bar. The mark switches to the dark-ink
 * artwork because this bar is light.
 *
 * The three links stay visible on desktop rather than hiding behind the menu
 * button the reference design uses everywhere. With three destinations, hiding
 * them costs discoverability and buys only tidiness.
 */
function SiteHeader() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "sticky top-0 z-40 transition-[background-color,border-color,backdrop-filter] duration-300",
        scrolled || open
          ? "border-b border-border bg-background/85 backdrop-blur-md"
          : "border-b border-transparent bg-transparent",
      )}
    >
      <Container className="flex h-[84px] items-center gap-8">
        <Link to="/" aria-label="Scaleezy home" className="shrink-0">
          <ScaleezyLogo className="w-[8.25rem] sm:w-[9.5rem]" tone="light" priority />
        </Link>

        <nav aria-label="Primary" className="ml-auto hidden items-center gap-9 lg:flex">
          {MARKETING_NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="text-[0.9375rem] font-medium text-muted-foreground transition-colors hover:text-foreground data-[status=active]:text-foreground"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <Link
            to="/login"
            search={{ redirect: undefined }}
            className="hidden px-2 text-[0.9375rem] font-medium text-muted-foreground transition-colors hover:text-foreground sm:inline"
          >
            Sign in
          </Link>
          <PillLink to="/signup" className="px-5 py-3">
            Get started
          </PillLink>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="marketing-mobile-nav"
            aria-label={open ? "Close navigation" : "Open navigation"}
            className="-mr-2 grid size-10 place-items-center rounded-full text-foreground transition-colors hover:bg-secondary lg:hidden"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </Container>

      <div
        id="marketing-mobile-nav"
        hidden={!open}
        className="border-t border-border lg:hidden"
        onClick={() => setOpen(false)}
      >
        <Container className="flex flex-col py-3">
          {MARKETING_NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="py-3.5 text-[1.0625rem] font-medium text-foreground/80 transition-colors hover:text-foreground data-[status=active]:text-foreground"
            >
              {item.label}
            </Link>
          ))}
          <Link
            to="/login"
            search={{ redirect: undefined }}
            className="mt-1 border-t border-border pt-4 pb-2 text-[1.0625rem] font-medium text-foreground/80 transition-colors hover:text-foreground sm:hidden"
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

/**
 * The public landing page — what a visitor sees at the bare domain.
 *
 * Deliberately server-rendered, unlike /login and /_hub. Those two opt out
 * because their guards read localStorage, which does not exist during SSR; a
 * marketing page has the opposite requirement, because a crawler that gets an
 * empty shell indexes nothing. Signed-in visitors are moved on to their
 * dashboard from an effect after hydration instead of from `beforeLoad`, which
 * would run on the server as "signed out" and never re-evaluate on the client.
 *
 * Every claim on this page is one the code actually supports. The five
 * channels below are the five with real publish paths in
 * apps/publishing/services.py — TikTok and Google Business exist in the
 * platform enum but have no adapter, so they are not advertised here.
 */
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import {
  ArrowRight,
  BarChart3,
  Brain,
  CheckCircle2,
  Facebook,
  Instagram,
  Layers,
  Linkedin,
  MessagesSquare,
  Send,
  ShieldCheck,
  Sparkles,
  Twitter,
  Youtube,
} from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { SiteFooter } from "@/components/marketing/site-footer";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Scaleezy — social marketing that knows your brand" },
      {
        name: "description",
        content:
          "Scaleezy learns your brand from your own material, drafts campaigns with the AI models you choose, and publishes only what a person has approved.",
      },
      { property: "og:title", content: "Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content:
          "Brand intelligence, governed AI generation, human approval and multi-channel publishing in one loop.",
      },
    ],
  }),
  component: LandingPage,
});

/* ------------------------------------------------------------------ */
/* Content                                                             */
/* ------------------------------------------------------------------ */

const LOOP = [
  {
    step: "01",
    title: "Learn",
    body: "Upload documents, decks, transcripts and reference posts. Scaleezy reads them into a brand profile you can inspect, correct and confirm.",
  },
  {
    step: "02",
    title: "Create",
    body: "Describe the outcome. Posters, carousels and video are drafted against your confirmed brand — not a generic prompt.",
  },
  {
    step: "03",
    title: "Review",
    body: "Every draft waits for a person. Approve it, ask for edits, or reject it with the reason attached.",
  },
  {
    step: "04",
    title: "Publish",
    body: "Send approved work to five channels at once, now or on a schedule. One channel failing never blocks the others.",
  },
  {
    step: "05",
    title: "Improve",
    body: "Rejections and real performance feed back in, so the next draft starts closer to what you would have approved anyway.",
  },
] as const;

const CAPABILITIES = [
  {
    icon: Brain,
    title: "A brand memory, not a prompt",
    body: "Facts, references and preferences are stored separately from the words a model wrote, and each one keeps a link to the material it came from.",
  },
  {
    icon: Layers,
    title: "Your models, your routing",
    body: "Route copy to one provider and images to another, run several in failover, or let them compete on the same task. Change it without a deploy.",
  },
  {
    icon: CheckCircle2,
    title: "Approval is not optional",
    body: "Publishing is gated on an explicit human decision. Scheduled posts, retries and automated runs all pass through the same gate.",
  },
  {
    icon: MessagesSquare,
    title: "One engagement inbox",
    body: "Mentions and comments land in a single queue with clear ownership. Replies are drafted by AI and sent only after someone approves them.",
  },
  {
    icon: BarChart3,
    title: "Numbers with a source",
    body: "Reach, engagement, leads and revenue trace back to the post, the model and the cost that produced them. Missing data reads as missing, never as zero.",
  },
  {
    icon: ShieldCheck,
    title: "Separated by default",
    body: "Every record belongs to one workspace and one brand. Access is checked on every request, on every path that can write.",
  },
] as const;

const CHANNELS = [
  { icon: Instagram, label: "Instagram" },
  { icon: Facebook, label: "Facebook" },
  { icon: Linkedin, label: "LinkedIn" },
  { icon: Twitter, label: "X" },
  { icon: Youtube, label: "YouTube" },
] as const;

const TRUST = [
  {
    title: "Nothing is invented",
    body: "Work that did not finish is never recorded as finished. A provider outage, a failed upload or a rejected post stays visible and retryable.",
  },
  {
    title: "Every output has a lineage",
    body: "You can follow any published post back through the draft, the approval, the model that wrote it and the brand material it drew on.",
  },
  {
    title: "You hold the keys",
    body: "Provider credentials and channel tokens are encrypted per workspace. Scaleezy never asks for a social password — authorisation happens on the platform's own page.",
  },
] as const;

/* ------------------------------------------------------------------ */
/* Layout primitives                                                   */
/* ------------------------------------------------------------------ */

/** One page-width column. Matches the hub's 1400px editorial measure. */
function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`mx-auto w-full max-w-[1200px] px-5 sm:px-8 lg:px-12 ${className}`}>
      {children}
    </div>
  );
}

function Eyebrow({ children, dark = false }: { children: ReactNode; dark?: boolean }) {
  return (
    <p
      className={`text-[0.6875rem] font-semibold tracking-[0.18em] uppercase ${
        dark ? "text-primary" : "text-muted-foreground"
      }`}
    >
      {children}
    </p>
  );
}

/* ------------------------------------------------------------------ */
/* Sections                                                            */
/* ------------------------------------------------------------------ */

function Header() {
  return (
    // Dark, like every other navigation shell in the product. Not a style
    // preference: the wordmark asset is white and lime on transparency, so on
    // a light bar the "scale" half disappears into the background entirely.
    <header className="sticky top-0 z-40 border-b border-white/10 bg-brand-dark/95 text-white backdrop-blur-md">
      <Container className="flex h-[72px] items-center gap-6">
        <Link to="/" aria-label="Scaleezy home" className="shrink-0">
          <ScaleezyLogo className="w-[8.5rem] sm:w-[9.75rem]" priority />
        </Link>

        <nav aria-label="Sections" className="ml-auto hidden items-center gap-8 lg:flex">
          {[
            { href: "#how-it-works", label: "How it works" },
            { href: "#capabilities", label: "Capabilities" },
            { href: "#trust", label: "Trust" },
          ].map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm font-medium text-white/65 transition-colors hover:text-white"
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 lg:ml-0">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="text-white/70 hover:bg-white/10 hover:text-white"
          >
            <Link to="/login" search={{ redirect: undefined }}>
              Sign in
            </Link>
          </Button>
          <Button asChild size="sm">
            <Link to="/signup">Get started</Link>
          </Button>
        </div>
      </Container>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* A single soft lime wash. One light source, no gradient stack. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[34rem] w-[64rem] -translate-x-1/2 rounded-full bg-primary/18 blur-[120px]"
      />
      <Container className="relative pt-16 pb-20 sm:pt-24 lg:pt-28 lg:pb-28">
        <div className="mx-auto max-w-[52rem] text-center">
          <Eyebrow>Scaleezy Marketing Hub</Eyebrow>
          <h1 className="mt-6 text-[2.75rem] leading-[1.04] font-bold tracking-[-0.03em] text-balance sm:text-6xl lg:text-[4.5rem]">
            Social marketing that knows your brand.
          </h1>
          <p className="mx-auto mt-7 max-w-[38rem] text-lg leading-relaxed text-pretty text-muted-foreground sm:text-xl">
            Scaleezy learns your brand from your own material, drafts the work with the AI models
            you choose, and publishes only what a person has approved.
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Button asChild size="lg" className="w-full sm:w-auto">
              <Link to="/signup">
                Get started <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg" className="w-full sm:w-auto">
              <Link to="/login" search={{ redirect: undefined }}>
                Sign in
              </Link>
            </Button>
          </div>

          <p className="mt-5 text-sm text-muted-foreground">
            Publishes to Instagram, Facebook, LinkedIn, X and YouTube.
          </p>
        </div>

        <div className="mt-16 sm:mt-20">
          <LoopDiagram />
        </div>
      </Container>
    </section>
  );
}

/**
 * The product in one picture: what goes in, what comes out, and the human in
 * the middle. Drawn from type and rules rather than a screenshot, because a
 * screenshot of an empty account says nothing and a filled one would mean
 * inventing a customer's numbers.
 */
function LoopDiagram() {
  const stages = [
    { icon: Brain, label: "Brand Brain", note: "your material" },
    { icon: Sparkles, label: "Draft", note: "routed AI" },
    { icon: CheckCircle2, label: "Approval", note: "a person" },
    { icon: Send, label: "Published", note: "five channels" },
  ];

  return (
    <div className="mx-auto max-w-[62rem] rounded-3xl border border-border bg-card p-5 shadow-card sm:p-8">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-0">
        {stages.map((stage, i) => (
          <div key={stage.label} className="relative flex items-start gap-4 p-3 lg:flex-col lg:p-5">
            <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand-dark text-primary">
              <stage.icon className="size-5" strokeWidth={1.75} />
            </span>
            <div className="min-w-0 lg:mt-4">
              <p className="text-base font-semibold">{stage.label}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{stage.note}</p>
            </div>
            {/* Connector, desktop only: the flow is top-to-bottom on mobile. */}
            {i < stages.length - 1 && (
              <span
                aria-hidden
                className="absolute top-[2.6rem] -right-2 hidden h-px w-4 bg-border lg:block"
              />
            )}
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center gap-3 border-t border-border pt-5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
          <BarChart3 className="size-4" strokeWidth={1.75} />
        </span>
        <p className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">Then it closes.</span> Approvals,
          rejections and real performance return to the Brand Brain, so the next draft starts
          sharper than the last.
        </p>
      </div>
    </div>
  );
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-24 bg-brand-dark py-20 text-white sm:py-28">
      <Container>
        <div className="max-w-[42rem]">
          <Eyebrow dark>How it works</Eyebrow>
          <h2 className="mt-5 text-3xl leading-[1.1] font-bold tracking-[-0.02em] text-balance sm:text-4xl lg:text-[3.25rem]">
            One loop, end to end.
          </h2>
          <p className="mt-5 text-lg text-pretty text-white/65">
            Most tools hand you a blank prompt box and a scheduler. Scaleezy connects what your
            brand knows to what it ships, and feeds the result back in.
          </p>
        </div>

        <ol className="mt-14 grid gap-px overflow-hidden rounded-2xl border border-white/12 bg-white/12 sm:grid-cols-2 lg:grid-cols-5">
          {LOOP.map((item) => (
            <li key={item.step} className="bg-brand-dark p-6 lg:p-7">
              <span className="text-sm font-semibold text-primary tabular-nums">{item.step}</span>
              <h3 className="mt-4 text-xl font-semibold">{item.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-white/60">{item.body}</p>
            </li>
          ))}
        </ol>
      </Container>
    </section>
  );
}

function Capabilities() {
  return (
    <section id="capabilities" className="scroll-mt-24 py-20 sm:py-28">
      <Container>
        <div className="max-w-[42rem]">
          <Eyebrow>Capabilities</Eyebrow>
          <h2 className="mt-5 text-3xl leading-[1.1] font-bold tracking-[-0.02em] text-balance sm:text-4xl lg:text-[3.25rem]">
            Built for work you have to stand behind.
          </h2>
        </div>

        <div className="mt-14 grid gap-x-10 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((item) => (
            <div key={item.title}>
              <span className="grid size-11 place-items-center rounded-xl border border-border bg-secondary">
                <item.icon className="size-5" strokeWidth={1.75} />
              </span>
              <h3 className="mt-5 text-lg font-semibold text-balance">{item.title}</h3>
              <p className="mt-2.5 leading-relaxed text-pretty text-muted-foreground">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

function Channels() {
  return (
    <section className="border-y border-border bg-secondary/60 py-16 sm:py-20">
      <Container>
        <div className="flex flex-col items-center gap-10 text-center lg:flex-row lg:justify-between lg:gap-16 lg:text-left">
          <div className="max-w-[26rem]">
            <Eyebrow>Channels</Eyebrow>
            <h2 className="mt-4 text-2xl font-bold tracking-[-0.02em] text-balance sm:text-3xl">
              Five channels, one approved post.
            </h2>
            <p className="mt-3 text-pretty text-muted-foreground">
              Connect an account once. Publishing fans out per channel, so one failure never takes
              the rest down with it — and only the failed channel is retried.
            </p>
          </div>

          {/* Wraps freely on small screens; held to a single row from lg, where
              breaking one channel onto a line of its own just looks like an
              afterthought. */}
          <ul className="flex flex-wrap items-center justify-center gap-2.5 sm:gap-3 lg:flex-nowrap">
            {CHANNELS.map((channel) => (
              <li
                key={channel.label}
                className="flex items-center gap-2 rounded-xl border border-border bg-card px-3.5 py-2.5 shadow-card"
              >
                <channel.icon className="size-[1.125rem] shrink-0" strokeWidth={1.75} />
                <span className="text-sm font-semibold whitespace-nowrap">{channel.label}</span>
              </li>
            ))}
          </ul>
        </div>
      </Container>
    </section>
  );
}

function Trust() {
  return (
    <section id="trust" className="scroll-mt-24 py-20 sm:py-28">
      <Container>
        <div className="max-w-[42rem]">
          <Eyebrow>Trust</Eyebrow>
          <h2 className="mt-5 text-3xl leading-[1.1] font-bold tracking-[-0.02em] text-balance sm:text-4xl lg:text-[3.25rem]">
            An honest system beats a confident one.
          </h2>
        </div>

        <div className="mt-14 grid gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-3">
          {TRUST.map((item) => (
            <div key={item.title} className="bg-card p-7 lg:p-8">
              <h3 className="text-lg font-semibold text-balance">{item.title}</h3>
              <p className="mt-3 leading-relaxed text-pretty text-muted-foreground">{item.body}</p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

function ClosingCta() {
  return (
    <section className="pb-20 sm:pb-28">
      <Container>
        <div className="relative overflow-hidden rounded-3xl bg-brand-dark px-6 py-16 text-center text-white sm:px-12 sm:py-20">
          <div
            aria-hidden
            className="pointer-events-none absolute -bottom-32 left-1/2 h-80 w-[42rem] -translate-x-1/2 rounded-full bg-primary/25 blur-[100px]"
          />
          <div className="relative mx-auto max-w-[36rem]">
            <h2 className="text-3xl leading-[1.1] font-bold tracking-[-0.02em] text-balance sm:text-[2.75rem]">
              Teach it once. Ship every week.
            </h2>
            <p className="mt-5 text-lg text-pretty text-white/65">
              Start with one brand and one channel. Add the rest when it has earned your trust.
            </p>
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
/* Page                                                                */
/* ------------------------------------------------------------------ */

function LandingPage() {
  const navigate = useNavigate();
  const { auth } = Route.useRouteContext();

  // After hydration, not in beforeLoad: the session lives in localStorage, so
  // on the server this check can only ever answer "signed out". Someone with a
  // session gets their dashboard; a crawler, and anyone signed out, gets the
  // fully rendered page above.
  useEffect(() => {
    if (auth.isAuthenticated()) {
      void navigate({ to: "/overview", replace: true });
    }
  }, [auth, navigate]);

  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main>
        <Hero />
        <HowItWorks />
        <Capabilities />
        <Channels />
        <Trust />
        <ClosingCta />
      </main>
      <SiteFooter />
    </div>
  );
}

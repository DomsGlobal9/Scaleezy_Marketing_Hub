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
 * This page is the overview; each block links to the page that covers it
 * properly. It carries the site-level Organization and SoftwareApplication
 * schema, which is defined here once rather than repeated on every page.
 *
 * Every claim is one the code actually supports. The five channels are the five
 * with real publish paths in apps/publishing/services.py — TikTok and Google
 * Business exist in the platform enum but have no adapter, so they are not
 * advertised anywhere on this site.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  Brain,
  CheckCircle2,
  Facebook,
  Instagram,
  Layers,
  Linkedin,
  MessagesSquare,
  ShieldCheck,
  Twitter,
  Youtube,
} from "lucide-react";
import { useEffect } from "react";

import {
  ApprovalGateIllustration,
  BrandBrainIllustration,
  FanOutIllustration,
} from "@/components/marketing/illustrations";
import {
  ArrowLink,
  ClosingCta,
  Container,
  DisplayHeading,
  Eyebrow,
  FeatureRow,
  Faq,
  JsonLd,
  Lede,
  MarketingShell,
  MediaPanel,
  PillLink,
  Section,
  SectionHeading,
  StatementBand,
} from "@/components/marketing/marketing-shell";
import { Circled, Reveal, Underlined } from "@/components/marketing/motion";
import {
  faqSchema,
  marketingHead,
  organizationSchema,
  softwareApplicationSchema,
  webPageSchema,
} from "@/lib/seo";

const SEO = {
  title: "Scaleezy — AI social media marketing that knows your brand",
  description:
    "Scaleezy learns your brand from your own documents, drafts posters, carousels and video with the AI models you choose, and publishes to Instagram, Facebook, LinkedIn, X and YouTube only after a person approves.",
  path: "/",
  keywords: [
    "AI social media marketing platform",
    "AI content generation for brands",
    "brand voice AI",
    "social media approval workflow",
    "multi-channel social publishing",
    "AI marketing automation",
    "social media management software",
  ],
} as const;

export const Route = createFileRoute("/")({
  head: () => marketingHead(SEO),
  component: LandingPage,
});

const ROWS = [
  {
    eyebrow: "Learn",
    title: "It reads your brand before it writes a word.",
    body: "Upload the documents, decks, transcripts and reference posts you already have. Scaleezy turns them into a brand profile you can inspect, correct and confirm — and every fact keeps a link back to the file it came from.",
    bullets: [
      "Extracted facts arrive as candidates, never as brand truth.",
      "What a model inferred stays separate from what a person stated.",
    ],
    Figure: BrandBrainIllustration,
    to: "/how-it-works" as const,
    link: "See how it learns",
  },
  {
    eyebrow: "Review",
    title: "Nothing goes out that a person has not approved.",
    body: "Every draft waits in a queue. Approve it, ask for edits, or reject it with the reason attached — and that reason becomes a constraint on the next generation rather than a note nobody reads.",
    bullets: [
      "Scheduled posts, retries and automated runs pass the same gate.",
      "Revisions are versioned against the draft they replace.",
    ],
    Figure: ApprovalGateIllustration,
    to: "/capabilities" as const,
    link: "See every capability",
  },
  {
    eyebrow: "Publish",
    title: "Five channels, and one failure never costs you four.",
    body: "An approved post fans out to each connected account as its own job. A token that expired on one network does not take the others down, and the retry re-attempts only what actually failed.",
    bullets: [
      "Instagram, Facebook, LinkedIn, X and YouTube.",
      "Immediate or scheduled, with posting windows enforced server-side.",
    ],
    Figure: FanOutIllustration,
    to: "/trust" as const,
    link: "How your data stays separate",
  },
] as const;

const CAPABILITIES = [
  {
    icon: Brain,
    title: "A brand memory, not a prompt",
    body: "Facts, references and preferences are stored separately from the words a model wrote, each linked to the material it came from.",
  },
  {
    icon: Layers,
    title: "Your models, your routing",
    body: "Route copy to one provider and images to another, run several in failover, or let them compete. Change it without a deploy.",
  },
  {
    icon: CheckCircle2,
    title: "Approval is not optional",
    body: "Publishing is gated on an explicit human decision, on every path that can reach a channel.",
  },
  {
    icon: MessagesSquare,
    title: "One engagement inbox",
    body: "Mentions and comments land in a single queue with clear ownership. Replies are drafted by AI, sent only after approval.",
  },
  {
    icon: BarChart3,
    title: "Numbers with a source",
    body: "Reach, leads and revenue trace back to the post, the model and the cost behind them. Missing data reads as missing, never as zero.",
  },
  {
    icon: ShieldCheck,
    title: "Separated by default",
    body: "Every record belongs to one workspace and one brand. Access is checked on every request that can write.",
  },
] as const;

const CHANNELS = [
  { icon: Instagram, label: "Instagram" },
  { icon: Facebook, label: "Facebook" },
  { icon: Linkedin, label: "LinkedIn" },
  { icon: Twitter, label: "X" },
  { icon: Youtube, label: "YouTube" },
] as const;

const FAQ = [
  {
    question: "What is Scaleezy?",
    answer:
      "Scaleezy is an AI social media marketing platform that learns a brand from its own documents and reference material, drafts posters, carousels, video and copy through the AI providers each workspace configures, and publishes to Instagram, Facebook, LinkedIn, X and YouTube only after a person has approved the work.",
  },
  {
    question: "Does AI publish to my accounts automatically?",
    answer:
      "No. Publishing is gated on an explicit human approval. A draft can be generated automatically, scheduled and queued, but it cannot reach a channel until a person has approved that specific piece of work.",
  },
  {
    question: "Which platforms can Scaleezy publish to?",
    answer:
      "Scaleezy publishes to five channels: Instagram, Facebook, LinkedIn, X and YouTube. Each connected account is authorised on the platform's own OAuth page, so Scaleezy never receives or stores a social password.",
  },
  {
    question: "Can I use my own AI models?",
    answer:
      "Yes. Providers are configured per workspace and routed per capability, so you can send copy to one model and images to another, or order several as failover for the same task. Changing that routing takes effect without a deploy.",
  },
] as const;

/* ------------------------------------------------------------------ */
/* Sections                                                            */
/* ------------------------------------------------------------------ */

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-56 -right-40 h-[38rem] w-[52rem] rounded-full bg-primary/20 blur-[130px]"
      />
      <Container className="relative pt-16 pb-24 sm:pt-24 lg:pt-28 lg:pb-32">
        <Reveal from="none">
          <Eyebrow>Scaleezy Marketing Hub</Eyebrow>
          <DisplayHeading className="mt-8 max-w-[16ch]">
            Social marketing that knows your <Underlined>brand</Underlined>
          </DisplayHeading>
          <Lede className="mt-9 max-w-[46ch]">
            Scaleezy learns your brand from your own material, drafts the work with the AI models
            you choose, and publishes only what a person has approved.
          </Lede>
          <div className="mt-11 flex flex-wrap items-center gap-3">
            <PillLink to="/signup">Get started</PillLink>
            <PillLink to="/how-it-works" variant="outline">
              See how it works
            </PillLink>
          </div>
        </Reveal>
      </Container>
    </section>
  );
}

function Channels() {
  return (
    <Section tone="muted" className="py-20 sm:py-24">
      <Reveal>
        <div className="flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-[30rem]">
            <Eyebrow>Channels</Eyebrow>
            <SectionHeading className="mt-5">Five channels, one approved post.</SectionHeading>
          </div>
          <ul className="flex flex-wrap gap-2.5">
            {CHANNELS.map((channel) => (
              <li
                key={channel.label}
                className="flex items-center gap-2 rounded-full border border-border bg-card px-4 py-2.5"
              >
                <channel.icon className="size-[1.0625rem] shrink-0" strokeWidth={1.75} />
                <span className="text-sm font-semibold whitespace-nowrap">{channel.label}</span>
              </li>
            ))}
          </ul>
        </div>
      </Reveal>
    </Section>
  );
}

function Capabilities() {
  return (
    <Section id="capabilities">
      <Reveal>
        <Eyebrow>Capabilities</Eyebrow>
        <SectionHeading className="mt-5 max-w-[18ch]">
          Built for work you have to stand behind.
        </SectionHeading>
      </Reveal>

      <div className="mt-20 grid gap-x-12 gap-y-14 sm:grid-cols-2 lg:grid-cols-3">
        {CAPABILITIES.map((item, i) => (
          <Reveal as="article" key={item.title} delay={(i % 3) * 70}>
            <item.icon className="size-6 text-foreground" strokeWidth={1.5} />
            <h3 className="mt-6 text-xl font-semibold text-balance">{item.title}</h3>
            <p className="mt-3 leading-relaxed text-pretty text-muted-foreground">{item.body}</p>
          </Reveal>
        ))}
      </div>

      <Reveal className="mt-16">
        <ArrowLink to="/capabilities">See every capability</ArrowLink>
      </Reveal>
    </Section>
  );
}

function Questions() {
  return (
    <Section>
      <Reveal>
        <Eyebrow>Common questions</Eyebrow>
        <SectionHeading className="mt-5 max-w-[16ch]">Answered directly.</SectionHeading>
      </Reveal>
      <Faq entries={FAQ} />
      <Reveal className="mt-14">
        <ArrowLink to="/how-it-works">More about how it works</ArrowLink>
      </Reveal>
    </Section>
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
    <MarketingShell>
      <JsonLd
        data={[
          organizationSchema(),
          softwareApplicationSchema(),
          webPageSchema(SEO),
          faqSchema(FAQ, SEO.path),
        ]}
      />

      <Hero />

      <Section className="pt-4 sm:pt-6 lg:pt-8">
        <div className="grid gap-28 lg:gap-36">
          {ROWS.map((row, i) => (
            <FeatureRow
              key={row.eyebrow}
              eyebrow={row.eyebrow}
              title={row.title}
              body={row.body}
              bullets={row.bullets}
              flip={i % 2 === 1}
              figure={
                <MediaPanel tone={i % 2 === 1 ? "plain" : "tint"}>
                  <row.Figure className="w-full text-foreground" />
                </MediaPanel>
              }
            >
              <ArrowLink to={row.to}>{row.link}</ArrowLink>
            </FeatureRow>
          ))}
        </div>
      </Section>

      <StatementBand footnote="Approvals, rejections and measured performance all return to the brand profile, so the next draft starts closer to what you would have approved anyway.">
        Every result comes back and makes the next one <Circled>sharper</Circled>
      </StatementBand>

      <Capabilities />
      <Channels />
      <Questions />
      <ClosingCta />
    </MarketingShell>
  );
}

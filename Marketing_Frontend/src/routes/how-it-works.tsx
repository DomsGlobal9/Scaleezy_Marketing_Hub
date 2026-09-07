/**
 * /how-it-works — the loop, explained one stage at a time.
 *
 * Written so that each stage's first sentence is a complete, self-contained
 * answer. That serves a reader skimming the page, a featured snippet quoting
 * one paragraph, and an assistant summarising the page without linking to it.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2, Rocket, Send, Sparkles, Upload } from "lucide-react";

import {
  ApprovalGateIllustration,
  BrandBrainIllustration,
  FanOutIllustration,
  LineageIllustration,
  LoopRingIllustration,
  RoutingIllustration,
} from "@/components/marketing/illustrations";
import {
  ClosingCta,
  Container,
  Faq,
  JsonLd,
  MarketingShell,
  PageHero,
  Section,
  SectionHead,
} from "@/components/marketing/marketing-shell";
import { Button } from "@/components/ui/button";
import { breadcrumbSchema, faqSchema, marketingHead, webPageSchema } from "@/lib/seo";

const SEO = {
  title: "How it works — AI social media marketing, from brand to published post",
  description:
    "See how Scaleezy learns your brand from your own documents, drafts social content with the AI models you choose, routes every draft through human approval, and publishes to five channels.",
  path: "/how-it-works",
  image: "/og/og-how-it-works.png",
  keywords: [
    "how AI social media marketing works",
    "AI content generation workflow",
    "social media approval workflow",
    "brand voice AI",
    "AI marketing automation process",
    "multi-channel social publishing",
  ],
} as const;

export const Route = createFileRoute("/how-it-works")({
  head: () => marketingHead(SEO),
  component: HowItWorksPage,
});

const STAGES = [
  {
    step: "01",
    art: "brand" as const,
    icon: Upload,
    title: "Learn: your brand becomes structured knowledge",
    lead: "Scaleezy learns a brand by reading the material the brand already has, rather than by asking someone to describe it in a prompt.",
    body: "Upload brand books, product decks, price lists, call transcripts and pasted notes. Add the posts, campaigns and competitor work you want the output to feel like. Each upload is read into candidate facts and style signals, and each one keeps a link back to the file or reference it came from.",
    detail: [
      "Documents, transcripts, links and pasted text all become sources.",
      "Extracted facts arrive as candidates, never as brand truth.",
      "A person confirms, corrects or rejects each one before it counts.",
      "What a model inferred is stored separately from what a person stated.",
    ],
  },
  {
    step: "02",
    art: "routing" as const,
    icon: Sparkles,
    title: "Create: drafts written against the confirmed brand",
    lead: "Generation starts from your compiled brand profile, not from a blank prompt box.",
    body: "Describe the outcome in a sentence — the campaign, the offer, the audience. Scaleezy assembles the brief from your confirmed brand facts, the references you selected and the format you picked, then routes each part of the job to the AI provider configured for that capability.",
    detail: [
      "Posters, carousels, video and captions from one brief.",
      "Copy and images can go to different providers.",
      "Posters are composed locally from your real palette and fonts.",
      "Every generation records the model, the cost and the brief it used.",
    ],
  },
  {
    step: "03",
    art: "approval" as const,
    icon: CheckCircle2,
    title: "Review: a person decides, every time",
    lead: "No draft becomes a published post without an explicit human approval.",
    body: "Work lands in a review queue. Approve it, ask for edits, or reject it with the reason attached. Rejection is not a dead end: the reason is captured as training signal, and a revision is linked to the version it replaces so the history stays readable.",
    detail: [
      "Approve, request edits, or reject with a tagged reason.",
      "Revisions are versioned against the draft they replace.",
      "Scheduled posts and automated runs pass the same gate.",
      "Nothing is marked approved that a person did not approve.",
    ],
  },
  {
    step: "04",
    art: "fanout" as const,
    icon: Send,
    title: "Publish: five channels, independently",
    lead: "An approved post fans out to each connected channel as its own job, so one platform failing never blocks the rest.",
    body: "Publish immediately or schedule it. Each channel is attempted separately and reports its own outcome, so a token that expired on one network does not cost you the other four — and the retry targets only what actually failed.",
    detail: [
      "Instagram, Facebook, LinkedIn, X and YouTube.",
      "Immediate or scheduled, with per-account posting windows.",
      "Per-channel success, failure and retry.",
      "Account settings — pauses, daily limits, allowed hours — are enforced server-side.",
    ],
  },
  {
    step: "05",
    art: "lineage" as const,
    icon: Rocket,
    title: "Improve: results return to the brand",
    lead: "Approvals, rejections and measured performance feed back into the brand profile, so the next draft starts closer to what you would have approved anyway.",
    body: "The reasons you rejected something become constraints on the next generation. Real reach and engagement, once ingested, attach to the post, the model and the references that produced it — which is what makes it possible to say why one piece of work outperformed another.",
    detail: [
      "Rejection reasons become explicit generation constraints.",
      "Performance attaches to the post, model, cost and references.",
      "Numbers that were never measured stay blank, not zero.",
      "The brand profile can always be rebuilt from its underlying records.",
    ],
  },
] as const;

const FAQ = [
  {
    question: "How does Scaleezy learn my brand voice?",
    answer:
      "Scaleezy reads the material you already have — brand books, decks, transcripts, past posts and reference work — and turns it into candidate facts and style signals. Each candidate is reviewed by a person before it influences anything, and what a model inferred is stored separately from what a person stated, so the two can never be confused.",
  },
  {
    question: "Does AI publish to my social accounts automatically?",
    answer:
      "No. Publishing is gated on an explicit human approval. A draft can be generated automatically, scheduled and queued, but it cannot reach Instagram, Facebook, LinkedIn, X or YouTube until a person has approved that specific piece of work.",
  },
  {
    question: "Which social media platforms can Scaleezy publish to?",
    answer:
      "Scaleezy publishes to five channels: Instagram, Facebook, LinkedIn, X and YouTube. Each connected account is authorised on the platform's own OAuth page, so Scaleezy never receives or stores a social password.",
  },
  {
    question: "How long does it take to set up?",
    answer:
      "You can generate your first post as soon as one brand profile exists and one AI provider is configured. The brand profile gets sharper as you add material and confirm facts, so most teams start with a handful of documents and one channel, then expand.",
  },
  {
    question: "What happens if a post fails to publish on one channel?",
    answer:
      "Each channel is published as its own job. A failure on one platform is recorded against that channel only, the other channels still go out, and the retry re-attempts just the channel that failed rather than posting a second copy everywhere.",
  },
  {
    question: "Can I use my own AI provider?",
    answer:
      "Yes. Providers are configured per workspace and routed per capability, so you can send copy to one model and images to another, run several in failover order, or let them compete on the same task. Changing that routing takes effect without a deploy.",
  },
] as const;

function HowItWorksPage() {
  return (
    <MarketingShell>
      <JsonLd
        data={[
          webPageSchema(SEO),
          breadcrumbSchema([
            { name: "Home", path: "/" },
            { name: "How it works", path: SEO.path },
          ]),
          faqSchema(FAQ, SEO.path),
        ]}
      />

      <PageHero
        eyebrow="How it works"
        title="From your brand's own material to a published post."
        lede="Scaleezy runs one loop: learn the brand, draft the work, put it in front of a person, publish what they approve, and feed the result back in. Here is what happens at each stage."
      >
        <div className="mt-14 grid items-center gap-10 lg:grid-cols-[1fr_auto]">
          <ol className="grid gap-3 sm:grid-cols-5">
            {STAGES.map((stage) => (
              <li
                key={stage.step}
                className="rounded-xl border border-border bg-card p-4 shadow-card"
              >
                <span className="text-xs font-semibold text-primary tabular-nums">
                  {stage.step}
                </span>
                <p className="mt-2 text-sm font-semibold">{stage.title.split(":")[0]}</p>
              </li>
            ))}
          </ol>
          <LoopRingIllustration className="mx-auto max-w-[15rem] text-foreground lg:max-w-[17rem]" />
        </div>
      </PageHero>

      {STAGES.map((stage, i) => (
        <Section key={stage.step} tone={i % 2 === 1 ? "muted" : "light"} id={`stage-${stage.step}`}>
          <div className="grid gap-12 lg:grid-cols-2 lg:items-center lg:gap-16">
            <div className={i % 2 === 1 ? "lg:order-2" : undefined}>
              <div className="flex items-center gap-3">
                <span className="grid size-11 place-items-center rounded-xl bg-brand-dark text-primary">
                  <stage.icon className="size-5" strokeWidth={1.75} />
                </span>
                <span className="text-sm font-semibold text-muted-foreground tabular-nums">
                  Stage {stage.step}
                </span>
              </div>
              <h2 className="mt-6 text-2xl leading-tight font-bold tracking-[-0.02em] text-balance sm:text-3xl lg:text-[2.25rem]">
                {stage.title}
              </h2>
              <p className="mt-5 text-lg leading-relaxed font-medium text-pretty">{stage.lead}</p>
              <p className="mt-4 leading-relaxed text-pretty text-muted-foreground">{stage.body}</p>
              <ul className="mt-6 space-y-2.5">
                {stage.detail.map((point) => (
                  <li key={point} className="flex gap-3 text-sm text-muted-foreground">
                    <CheckCircle2
                      className="mt-0.5 size-4 shrink-0 text-primary"
                      strokeWidth={2}
                      aria-hidden
                    />
                    <span className="text-pretty">{point}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className={i % 2 === 1 ? "lg:order-1" : undefined}>
              <figure className="rounded-2xl border border-border bg-card p-6 shadow-card sm:p-8">
                {stage.art === "brand" && <BrandBrainIllustration className="text-foreground" />}
                {stage.art === "routing" && <RoutingIllustration className="text-foreground" />}
                {stage.art === "approval" && (
                  <ApprovalGateIllustration className="text-foreground" />
                )}
                {stage.art === "fanout" && <FanOutIllustration className="text-foreground" />}
                {stage.art === "lineage" && <LineageIllustration className="text-foreground" />}
              </figure>
            </div>
          </div>
        </Section>
      ))}

      <Section tone="dark">
        <SectionHead
          dark
          eyebrow="Common questions"
          title="How it works, answered directly."
          lede="The questions teams ask before they trust software with their brand's public voice."
        />
        <Faq entries={FAQ} tone="dark" />
      </Section>

      <Section>
        <div className="rounded-2xl border border-border bg-card p-8 sm:p-10">
          <h2 className="text-2xl font-bold tracking-[-0.02em] text-balance">Keep reading</h2>
          <p className="mt-3 text-muted-foreground">
            The loop above is the shape of the product. These two pages cover what it can do and how
            it keeps your work separate and honest.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button asChild variant="outline">
              <Link to="/capabilities">
                Capabilities <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/trust">
                Trust and security <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
        </div>
      </Section>

      <ClosingCta
        title="See the loop on your own brand."
        lede="Bring one brand document and one channel. The rest follows from there."
      />
    </MarketingShell>
  );
}

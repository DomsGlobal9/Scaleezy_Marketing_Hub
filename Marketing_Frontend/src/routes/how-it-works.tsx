/**
 * /how-it-works — the loop, explained one stage at a time.
 *
 * Written so that each stage's first sentence is a complete, self-contained
 * answer. That serves a reader skimming the page, a featured snippet quoting
 * one paragraph, and an assistant summarising the page without linking to it.
 *
 * Laid out as one stage per screen: an oversized headline, a short lede, a
 * figure, and the detail underneath. The reading order is the product's order.
 */
import { createFileRoute } from "@tanstack/react-router";

import {
  ApprovalGateIllustration,
  BrandBrainIllustration,
  FanOutIllustration,
  LineageIllustration,
  LoopRingIllustration,
  RoutingIllustration,
} from "@/components/marketing/illustrations";
import {
  ArrowLink,
  ClosingCta,
  Eyebrow,
  Faq,
  FeatureRow,
  JsonLd,
  MarketingShell,
  MediaPanel,
  PageHero,
  Section,
  SectionHeading,
  StatementBand,
} from "@/components/marketing/marketing-shell";
import { Reveal, Underlined } from "@/components/marketing/motion";
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
    eyebrow: "Stage 01 — Learn",
    title: "Your brand becomes structured knowledge.",
    lead: "Scaleezy learns a brand by reading the material the brand already has, rather than by asking someone to describe it in a prompt.",
    body: "Upload brand books, product decks, price lists, call transcripts and pasted notes. Add the posts, campaigns and competitor work you want the output to feel like. Each upload is read into candidate facts and style signals, and each one keeps a link back to the file or reference it came from.",
    detail: [
      "Documents, transcripts, links and pasted text all become sources.",
      "Extracted facts arrive as candidates, never as brand truth.",
      "A person confirms, corrects or rejects each one before it counts.",
      "What a model inferred is stored separately from what a person stated.",
    ],
    Figure: BrandBrainIllustration,
  },
  {
    step: "02",
    eyebrow: "Stage 02 — Create",
    title: "Drafts written against the confirmed brand.",
    lead: "Generation starts from your compiled brand profile, not from a blank prompt box.",
    body: "Describe the outcome in a sentence — the campaign, the offer, the audience. Scaleezy assembles the brief from your confirmed brand facts, the references you selected and the format you picked, then routes each part of the job to the AI provider configured for that capability.",
    detail: [
      "Posters, carousels, video and captions from one brief.",
      "Copy and images can go to different providers.",
      "Posters are composed locally from your real palette and fonts.",
      "Every generation records the model, the cost and the brief it used.",
    ],
    Figure: RoutingIllustration,
  },
  {
    step: "03",
    eyebrow: "Stage 03 — Review",
    title: "A person decides, every time.",
    lead: "No draft becomes a published post without an explicit human approval.",
    body: "Work lands in a review queue. Approve it, ask for edits, or reject it with the reason attached. Rejection is not a dead end: the reason is captured as training signal, and a revision is linked to the version it replaces so the history stays readable.",
    detail: [
      "Approve, request edits, or reject with a tagged reason.",
      "Revisions are versioned against the draft they replace.",
      "Scheduled posts and automated runs pass the same gate.",
      "Nothing is marked approved that a person did not approve.",
    ],
    Figure: ApprovalGateIllustration,
  },
  {
    step: "04",
    eyebrow: "Stage 04 — Publish",
    title: "Five channels, independently.",
    lead: "An approved post fans out to each connected channel as its own job, so one platform failing never blocks the rest.",
    body: "Publish immediately or schedule it. Each channel is attempted separately and reports its own outcome, so a token that expired on one network does not cost you the other four — and the retry targets only what actually failed.",
    detail: [
      "Instagram, Facebook, LinkedIn, X and YouTube.",
      "Immediate or scheduled, with per-account posting windows.",
      "Per-channel success, failure and retry.",
      "Account settings — pauses, daily limits, allowed hours — are enforced server-side.",
    ],
    Figure: FanOutIllustration,
  },
  {
    step: "05",
    eyebrow: "Stage 05 — Improve",
    title: "Results return to the brand.",
    lead: "Approvals, rejections and measured performance feed back into the brand profile, so the next draft starts closer to what you would have approved anyway.",
    body: "The reasons you rejected something become constraints on the next generation. Real reach and engagement, once ingested, attach to the post, the model and the references that produced it — which is what makes it possible to say why one piece of work outperformed another.",
    detail: [
      "Rejection reasons become explicit generation constraints.",
      "Performance attaches to the post, model, cost and references.",
      "Numbers that were never measured stay blank, not zero.",
      "The brand profile can always be rebuilt from its underlying records.",
    ],
    Figure: LineageIllustration,
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
        title={
          <>
            From your brand's own material to a published <Underlined>post</Underlined>
          </>
        }
        lede="Scaleezy runs one loop: learn the brand, draft the work, put it in front of a person, publish what they approve, and feed the result back in."
        figure={
          <MediaPanel tone="tint">
            <LoopRingIllustration className="mx-auto max-w-[19rem] text-foreground" />
          </MediaPanel>
        }
      />

      <Section>
        <div className="grid gap-28 lg:gap-40">
          {STAGES.map((stage, i) => (
            <FeatureRow
              key={stage.step}
              eyebrow={stage.eyebrow}
              title={stage.title}
              body={stage.lead}
              bullets={stage.detail}
              flip={i % 2 === 1}
              figure={
                <MediaPanel tone={i % 2 === 1 ? "plain" : "tint"}>
                  <stage.Figure className="w-full text-foreground" />
                </MediaPanel>
              }
            >
              <p className="max-w-[52ch] leading-relaxed text-pretty text-muted-foreground">
                {stage.body}
              </p>
            </FeatureRow>
          ))}
        </div>
      </Section>

      <StatementBand footnote="Most tools hand you a blank prompt box and a scheduler. The loop is what connects what your brand knows to what it ships.">
        One loop, end to end.
      </StatementBand>

      <Section>
        <Reveal>
          <Eyebrow>Common questions</Eyebrow>
          <SectionHeading className="mt-5 max-w-[18ch]">
            How it works, answered directly.
          </SectionHeading>
        </Reveal>
        <Faq entries={FAQ} />
        <Reveal className="mt-14 flex flex-wrap gap-x-10 gap-y-4">
          <ArrowLink to="/capabilities">See every capability</ArrowLink>
          <ArrowLink to="/trust">How your data stays separate</ArrowLink>
        </Reveal>
      </Section>

      <ClosingCta
        title="See the loop on your own brand."
        lede="Bring one brand document and one channel. The rest follows from there."
      />
    </MarketingShell>
  );
}

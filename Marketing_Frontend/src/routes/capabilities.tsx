/**
 * /capabilities — what the product actually does, grouped by the job it does.
 *
 * The feature list is checked against the code, not against ambition. Anything
 * that is not built is not on this page, and the two platforms that exist in
 * the Platform enum without an adapter (TikTok, Google Business) are named
 * nowhere on the site.
 *
 * Five groups, each opening with a definition sentence. The definitions are
 * deliberate: they are the lines an answer engine can lift whole, and they
 * give a reader who knows the category nothing to decode.
 */
import { createFileRoute } from "@tanstack/react-router";
import {
  BarChart3,
  Brain,
  CalendarClock,
  CheckCircle2,
  Coins,
  FileText,
  Image as ImageIcon,
  Layers,
  MessagesSquare,
  Repeat,
  Send,
  ShieldCheck,
  Users,
} from "lucide-react";

import {
  BrandBrainIllustration,
  FanOutIllustration,
  LineageIllustration,
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
import {
  breadcrumbSchema,
  faqSchema,
  marketingHead,
  softwareApplicationSchema,
  webPageSchema,
} from "@/lib/seo";

const SEO = {
  title: "Capabilities — brand AI, governed generation, publishing and analytics",
  description:
    "Every capability in the Scaleezy Marketing Hub: a brand knowledge base, per-capability AI provider routing, poster and video generation, human approval, multi-channel publishing, an engagement inbox and revenue attribution.",
  path: "/capabilities",
  image: "/og/og-capabilities.png",
  keywords: [
    "AI social media marketing platform features",
    "brand knowledge base software",
    "AI provider routing",
    "AI poster generation",
    "social media scheduling software",
    "engagement inbox",
    "marketing revenue attribution",
  ],
} as const;

export const Route = createFileRoute("/capabilities")({
  head: () => marketingHead(SEO),
  component: CapabilitiesPage,
});

const GROUPS = [
  {
    id: "brand-intelligence",
    eyebrow: "Brand intelligence",
    title: "A brand memory, not a prompt you retype.",
    lede: "A brand knowledge base is a structured record of what is true about a business and what its work should feel like, kept separately from the words any model wrote.",
    Figure: BrandBrainIllustration,
    items: [
      {
        icon: FileText,
        title: "Sources you can point at",
        body: "Documents, decks, price lists, transcripts, links and pasted notes become sources. Everything extracted from them keeps a link back to the file it came from, so any fact can be traced to its origin.",
      },
      {
        icon: Brain,
        title: "Facts, separated from inference",
        body: "What a person stated and what a model inferred are stored as different things with different authority. An AI inference can never silently overwrite a human-confirmed preference.",
      },
      {
        icon: ImageIcon,
        title: "References with intent",
        body: "Add posts, campaigns and competitor work as inspiration, and say what you want from each one — the whole reference or only its palette, layout, or tone.",
      },
      {
        icon: CheckCircle2,
        title: "Human confirmation",
        body: "Extracted facts arrive as candidates. Only what a person confirms influences generation, and confirming or rejecting one rebuilds the compiled brand profile deterministically.",
      },
    ],
  },
  {
    id: "generation",
    eyebrow: "Generation",
    title: "Your models, routed per capability.",
    lede: "Provider routing means each kind of work — copy, images, video, embeddings — is sent to whichever configured AI provider you chose for that job, independently of the others.",
    Figure: RoutingIllustration,
    items: [
      {
        icon: Layers,
        title: "Per-capability routing",
        body: "Send copy to one provider and images to another. Order several as failover, or let them compete on the same task and keep the best result. Changes take effect without a deploy.",
      },
      {
        icon: ImageIcon,
        title: "Posters composed, not hallucinated",
        body: "Imagery is generated, then composed locally against your real palette, fonts and logo. The output uses your brand's actual colours every time instead of only accidentally.",
      },
      {
        icon: Send,
        title: "Static, carousel and video",
        body: "One brief produces a poster, an ordered carousel or a video with captions, sized correctly for each destination rather than cropped from one master.",
      },
      {
        icon: Coins,
        title: "Cost and quota, counted",
        body: "Spend and usage are counted from actual generation records rather than a running total that can drift, and limits are enforced before a provider call rather than after you have been billed for it.",
      },
    ],
  },
  {
    id: "governance",
    eyebrow: "Review and governance",
    title: "Approval is a wall, not a suggestion.",
    lede: "An approval gate is a rule that no content reaches a public channel until a named person has approved that specific piece of work.",
    Figure: LineageIllustration,
    items: [
      {
        icon: CheckCircle2,
        title: "One gate, every path",
        body: "Immediate posts, scheduled posts, retries and automated runs all pass the same check. There is no route to a channel that skips it.",
      },
      {
        icon: Repeat,
        title: "Reasons become training",
        body: "Rejecting work with a reason does more than stop it. The reason is captured against the brand and becomes an explicit constraint on the next generation.",
      },
      {
        icon: Users,
        title: "Roles that mean something",
        body: "Owner, admin, manager, editor and viewer are enforced server-side on every request. A viewer cannot mutate anything, whichever endpoint they call.",
      },
      {
        icon: CalendarClock,
        title: "Windows and limits, enforced",
        body: "Posting pauses, daily caps and allowed hours are applied by the server on every publish path, not just shown in a settings screen.",
      },
    ],
  },
  {
    id: "distribution",
    eyebrow: "Distribution and engagement",
    title: "Five channels, and the conversations after.",
    lede: "Publishing fans an approved post out to each connected channel as an independent job, so channels succeed or fail on their own.",
    Figure: FanOutIllustration,
    items: [
      {
        icon: Send,
        title: "Instagram, Facebook, LinkedIn, X, YouTube",
        body: "Connect each account once through the platform's own OAuth page. Scaleezy never receives a social password, and stored tokens are encrypted per workspace.",
      },
      {
        icon: CalendarClock,
        title: "Now or scheduled",
        body: "Scheduled work is executed by a durable background worker, so a post set for Friday goes out on Friday whether or not anyone has the app open.",
      },
      {
        icon: MessagesSquare,
        title: "A shared engagement inbox",
        body: "Mentions and comments arrive in one queue with clear ownership, so two people cannot answer the same conversation. Replies are drafted by AI and sent only after approval.",
      },
      {
        icon: Repeat,
        title: "Retry what failed",
        body: "A retry re-attempts only the channels that failed. Channels that already published are skipped, so retrying cannot post a second copy.",
      },
    ],
  },
  {
    id: "measurement",
    eyebrow: "Measurement",
    title: "Numbers that can name their source.",
    lede: "Attribution links a published post to the model, cost, references and approval that produced it, so performance can be explained rather than only reported.",
    Figure: LineageIllustration,
    items: [
      {
        icon: BarChart3,
        title: "Reach, engagement, conversions",
        body: "Post-level metrics are ingested from the platforms with their freshness recorded, so you can tell current data from stale data at a glance.",
      },
      {
        icon: Coins,
        title: "Leads and revenue",
        body: "Captured leads and revenue events attribute back to the content and campaign that produced them, closing the loop between a post and its outcome.",
      },
      {
        icon: ShieldCheck,
        title: "Missing means missing",
        body: "A metric that was never measured is shown as unavailable, never as zero. A zero is a measurement; a blank is the absence of one, and conflating them makes every report untrustworthy.",
      },
      {
        icon: Brain,
        title: "Back into the brand",
        body: "Outcomes return to the brand profile and inform the next plan, which is what makes the loop a loop rather than a pipeline.",
      },
    ],
  },
] as const;

const FAQ = [
  {
    question: "What is a brand knowledge base in marketing software?",
    answer:
      "A brand knowledge base is a structured, reviewable record of what is true about a business and what its creative work should feel like. In Scaleezy it holds facts extracted from your own documents and references, each traceable to its source, each confirmed or rejected by a person, and with model-inferred claims kept separate from human-stated ones.",
  },
  {
    question: "Can I use different AI models for text and images?",
    answer:
      "Yes. Scaleezy routes per capability, so copy, images, video and embeddings are each sent to whichever configured provider you chose for that job. You can also order several providers as failover for the same capability, and changes take effect without a deploy.",
  },
  {
    question: "Does Scaleezy support scheduled posting?",
    answer:
      "Yes. Posts can be published immediately or scheduled, and scheduled work is executed by a durable background worker rather than by the browser, so a post scheduled for a future date goes out whether or not anyone has the application open.",
  },
  {
    question: "What formats can Scaleezy generate?",
    answer:
      "Scaleezy generates static posters, ordered carousels and video with captions from a single brief. Imagery is generated through your configured provider and then composed locally against your brand's real palette, fonts and logo, and each destination is re-composed at its own dimensions rather than cropped from one master.",
  },
  {
    question: "How does Scaleezy control AI spend?",
    answer:
      "Usage and spend are counted from actual generation records rather than accumulated in a counter that can drift, and plan limits are checked before a provider is called rather than after. A workspace that has reached its cap is stopped before the billable request, not billed for the one that took it over.",
  },
] as const;

function CapabilitiesPage() {
  return (
    <MarketingShell>
      <JsonLd
        data={[
          webPageSchema(SEO),
          softwareApplicationSchema(),
          breadcrumbSchema([
            { name: "Home", path: "/" },
            { name: "Capabilities", path: SEO.path },
          ]),
          faqSchema(FAQ, SEO.path),
        ]}
      />

      <PageHero
        eyebrow="Capabilities"
        title={
          <>
            Everything between a brand document and a measured <Underlined>post</Underlined>
          </>
        }
        lede="One system covering brand intelligence, governed AI generation, human review, multi-channel publishing, engagement and attribution. This page lists what it does — and only what it does."
      />

      <Section>
        <div className="grid gap-32 lg:gap-44">
          {GROUPS.map((group, i) => (
            <div key={group.id} id={group.id} className="scroll-mt-28">
              <FeatureRow
                eyebrow={group.eyebrow}
                title={group.title}
                body={group.lede}
                flip={i % 2 === 1}
                figure={
                  <MediaPanel tone={i % 2 === 1 ? "plain" : "tint"}>
                    <group.Figure className="w-full text-foreground" />
                  </MediaPanel>
                }
              />
              <div className="mt-16 grid gap-x-12 gap-y-12 sm:grid-cols-2">
                {group.items.map((item, j) => (
                  <Reveal as="article" key={item.title} delay={(j % 2) * 70}>
                    <item.icon className="size-6 text-foreground" strokeWidth={1.5} />
                    <h3 className="mt-5 text-lg font-semibold text-balance">{item.title}</h3>
                    <p className="mt-2.5 leading-relaxed text-pretty text-muted-foreground">
                      {item.body}
                    </p>
                  </Reveal>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <StatementBand footnote="Anything not built is not on this page. Two platforms exist in the code without a publishing adapter, and neither is named anywhere on this site.">
        Only what it actually does.
      </StatementBand>

      <Section>
        <Reveal>
          <Eyebrow>Common questions</Eyebrow>
          <SectionHeading className="mt-5 max-w-[18ch]">What it does, precisely.</SectionHeading>
        </Reveal>
        <Faq entries={FAQ} />
        <Reveal className="mt-14 flex flex-wrap gap-x-10 gap-y-4">
          <ArrowLink to="/how-it-works">How it works, stage by stage</ArrowLink>
          <ArrowLink to="/trust">How your data stays separate</ArrowLink>
        </Reveal>
      </Section>

      <ClosingCta
        title="Put it against your own brief."
        lede="One brand, one channel, one post. The rest is the same loop repeated."
      />
    </MarketingShell>
  );
}

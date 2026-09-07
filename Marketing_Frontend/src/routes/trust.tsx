/**
 * /trust — isolation, provenance, honest state and credential handling.
 *
 * The claims here are the ones the codebase actually enforces. Where something
 * is a design rule rather than a certification, it is written as a design rule:
 * this page deliberately claims no audit, standard or compliance badge the
 * product does not hold.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  Eye,
  FileSearch,
  KeyRound,
  Lock,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  UserCheck,
} from "lucide-react";

import { IsolationIllustration, LineageIllustration } from "@/components/marketing/illustrations";
import {
  ClosingCta,
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
  title: "Trust and security — tenant isolation, provenance and honest state",
  description:
    "How Scaleezy keeps client data separated, encrypts social and provider credentials per workspace, traces every published post back to its source, and refuses to record work as finished when it is not.",
  path: "/trust",
  image: "/og/og-trust.png",
  keywords: [
    "multi-tenant marketing software security",
    "AI content provenance",
    "social media token encryption",
    "marketing data isolation",
    "AI governance for marketing teams",
    "audit trail marketing software",
  ],
} as const;

export const Route = createFileRoute("/trust")({
  head: () => marketingHead(SEO),
  component: TrustPage,
});

const PILLARS = [
  {
    id: "isolation",
    eyebrow: "Isolation",
    title: "One client's work never reaches another's.",
    lede: "Tenant isolation means every record belongs to exactly one workspace, and access is re-checked on every request rather than assumed from a previous one.",
    illustration: "isolation" as const,
    items: [
      {
        icon: Lock,
        title: "Scoped by default, not by memory",
        body: "Data access is filtered by workspace at the query layer, so a listing endpoint cannot return another client's rows even if a permission check were forgotten. Correct behaviour is the default rather than something each screen has to remember.",
      },
      {
        icon: UserCheck,
        title: "Membership is checked every time",
        body: "The workspace a request addresses and the workspace it is authorised for must be the same value. A request that names two different workspaces is refused rather than resolved in the caller's favour.",
      },
      {
        icon: ShieldCheck,
        title: "No staff back door",
        body: "Being an administrator of the platform does not grant access to a client's data. Platform administration is a separate surface with its own boundary, and it does not widen tenant access.",
      },
      {
        icon: Eye,
        title: "Brand-level too",
        body: "Isolation is not only per client. Inside one workspace, one brand's references and facts cannot be attached to another brand's work, and a record's brand cannot be quietly reassigned after the fact.",
      },
    ],
  },
  {
    id: "credentials",
    eyebrow: "Credentials",
    title: "We never ask for a social password.",
    lede: "Every channel connection is authorised on the platform's own OAuth page, so Scaleezy receives a scoped token rather than a password.",
    illustration: null,
    items: [
      {
        icon: KeyRound,
        title: "Authorisation happens on the platform",
        body: "Connecting Instagram, Facebook, LinkedIn, X or YouTube sends you to that platform's own consent screen. Scaleezy never sees, transmits or stores your social account password.",
      },
      {
        icon: Lock,
        title: "Tokens encrypted at rest",
        body: "Access and refresh tokens are stored encrypted and are never returned to the browser. The client application receives the state of a connection, never the secret behind it.",
      },
      {
        icon: KeyRound,
        title: "Your AI keys stay yours",
        body: "Provider credentials are held per workspace and encrypted with the same mechanism. A workspace's key is used for that workspace's generations and is not shared across clients.",
      },
      {
        icon: RefreshCw,
        title: "Revocation is respected",
        body: "A connection whose authorisation has been withdrawn is marked as needing reconnection and stops publishing, rather than continuing to fail silently in the background.",
      },
    ],
  },
  {
    id: "provenance",
    eyebrow: "Provenance",
    title: "Every output can name where it came from.",
    lede: "Provenance is the ability to trace a published post backwards through its approval, the model that drafted it, and the brand material it drew on.",
    illustration: "lineage" as const,
    items: [
      {
        icon: FileSearch,
        title: "A chain, not a guess",
        body: "A post links to the draft, the draft to the brief and the model that produced it, and the brief to the confirmed brand facts and references behind it. Each link is a record, not a reconstruction.",
      },
      {
        icon: ScrollText,
        title: "Rebuildable by design",
        body: "The compiled brand profile is derived, and can always be rebuilt from the underlying source records. Nothing important exists only as a summary that cannot be recomputed.",
      },
      {
        icon: UserCheck,
        title: "Who said what",
        body: "A claim a person confirmed and a claim a model inferred are permanently distinguishable. An inference cannot be promoted into a human statement, and changing your mind writes a new record rather than overwriting the old one.",
      },
      {
        icon: Eye,
        title: "Archived means excluded",
        body: "When a source or reference is archived, it stops influencing future generation. Retrieval eligibility is evaluated as a rule at query time rather than depending on a flag someone remembered to set.",
      },
    ],
  },
  {
    id: "honesty",
    eyebrow: "Operational honesty",
    title: "Nothing is recorded as finished when it is not.",
    lede: "A state is honest when it reflects what actually happened: queued is not processing, processing is not ready, and a failure stays visible until someone deals with it.",
    illustration: null,
    items: [
      {
        icon: ShieldCheck,
        title: "No fabricated success",
        body: "Work that did not complete is never stored as complete. A provider outage, a failed upload or a rejected post remains visible and retryable instead of being smoothed over into an apparent success.",
      },
      {
        icon: RefreshCw,
        title: "Retries do not duplicate",
        body: "Re-running a job skips the channels that already succeeded. Retrying one failed platform cannot post a second copy to the four that worked.",
      },
      {
        icon: FileSearch,
        title: "Failures carry a reason",
        body: "A failed publish records what went wrong against the channel it happened on, so the fix is a specific action rather than a re-run and a hope.",
      },
      {
        icon: ScrollText,
        title: "Actions are audited",
        body: "Connections, publishes, approvals and administrative changes are written to an audit trail that survives the deletion of the user who performed them.",
      },
    ],
  },
] as const;

const FAQ = [
  {
    question: "How does Scaleezy keep different clients' data separate?",
    answer:
      "Every record belongs to exactly one workspace, and queries are filtered by workspace at the data-access layer rather than relying on each screen to remember. Membership is re-checked on every request, and a request that addresses one workspace while being authorised for another is refused rather than resolved in the caller's favour.",
  },
  {
    question: "Does Scaleezy store my social media passwords?",
    answer:
      "No. Connecting an account sends you to that platform's own OAuth consent screen, and Scaleezy receives a scoped access token rather than a password. Tokens are stored encrypted and are never returned to the browser.",
  },
  {
    question: "Can staff at Scaleezy read my brand data?",
    answer:
      "Platform administration is a separate surface with its own boundary and does not grant access to a client workspace's data. Being an administrator of the platform is not a tenant bypass; explicit workspace membership is still required to read a workspace's records.",
  },
  {
    question: "Can I tell whether a fact came from a person or from AI?",
    answer:
      "Yes, permanently. Human-stated claims and model-inferred claims are stored as different things with different authority, an inference can never be promoted into a human statement, and changing a preference writes a new record that supersedes the old one rather than overwriting it.",
  },
  {
    question: "What happens to my data if I archive a source?",
    answer:
      "An archived source stops influencing future generation. Eligibility for retrieval is evaluated as a rule when the data is queried rather than depending on a flag being set correctly at archive time, so an archived reference cannot leak back into a later draft.",
  },
  {
    question: "Is Scaleezy SOC 2 or ISO 27001 certified?",
    answer:
      "Scaleezy does not currently hold a SOC 2 or ISO 27001 certification, and this page claims no audit it has not passed. What it describes are design rules enforced in the product: workspace isolation, encrypted credentials, traceable provenance and honest failure states.",
  },
] as const;

function TrustPage() {
  return (
    <MarketingShell>
      <JsonLd
        data={[
          webPageSchema(SEO),
          breadcrumbSchema([
            { name: "Home", path: "/" },
            { name: "Trust", path: SEO.path },
          ]),
          faqSchema(FAQ, SEO.path),
        ]}
      />

      <PageHero
        eyebrow="Trust"
        title="An honest system beats a confident one."
        lede="Software that publishes in your brand's name has to be trustworthy in a specific way: it must keep clients apart, protect credentials, explain where output came from, and admit when something failed. Here is how each is handled."
      >
        <div className="mt-12 grid gap-3 sm:grid-cols-4">
          {PILLARS.map((pillar) => (
            <a
              key={pillar.id}
              href={`#${pillar.id}`}
              className="rounded-xl border border-border bg-card p-4 shadow-card transition-colors hover:border-foreground"
            >
              <p className="text-sm font-semibold">{pillar.eyebrow}</p>
            </a>
          ))}
        </div>
      </PageHero>

      {PILLARS.map((pillar, i) => (
        <Section key={pillar.id} id={pillar.id} tone={i % 2 === 1 ? "muted" : "light"}>
          <SectionHead eyebrow={pillar.eyebrow} title={pillar.title} lede={pillar.lede} />

          {pillar.illustration && (
            <div className="mt-12 rounded-2xl border border-border bg-card p-6 shadow-card sm:p-10">
              {pillar.illustration === "isolation" && (
                <IsolationIllustration className="mx-auto max-w-[34rem] text-foreground" />
              )}
              {pillar.illustration === "lineage" && (
                <LineageIllustration className="mx-auto max-w-[34rem] text-foreground" />
              )}
            </div>
          )}

          <div className="mt-12 grid gap-x-10 gap-y-11 sm:grid-cols-2">
            {pillar.items.map((item) => (
              <article key={item.title}>
                <span className="grid size-11 place-items-center rounded-xl border border-border bg-card">
                  <item.icon className="size-5" strokeWidth={1.75} />
                </span>
                <h3 className="mt-5 text-lg font-semibold text-balance">{item.title}</h3>
                <p className="mt-2.5 leading-relaxed text-pretty text-muted-foreground">
                  {item.body}
                </p>
              </article>
            ))}
          </div>
        </Section>
      ))}

      <Section tone="dark">
        <SectionHead
          dark
          eyebrow="Common questions"
          title="Security and governance, answered."
          lede="Including the question most vendor pages avoid."
        />
        <Faq entries={FAQ} tone="dark" />
      </Section>

      <Section>
        <div className="rounded-2xl border border-border bg-card p-8 sm:p-10">
          <h2 className="text-2xl font-bold tracking-[-0.02em] text-balance">Keep reading</h2>
          <p className="mt-3 text-muted-foreground">
            These rules exist to protect a specific workflow. Read how that workflow runs, and what
            the product can do inside it.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button asChild variant="outline">
              <Link to="/how-it-works">
                How it works <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/capabilities">
                Capabilities <ArrowRight className="size-4" />
              </Link>
            </Button>
          </div>
          <p className="mt-8 text-sm text-muted-foreground">
            Our{" "}
            <Link to="/privacy" className="lime-link">
              Privacy Policy
            </Link>{" "}
            and{" "}
            <Link to="/terms" className="lime-link">
              Terms &amp; Conditions
            </Link>{" "}
            set out the contractual side of the above.
          </p>
        </div>
      </Section>

      <ClosingCta
        title="Trust it with one channel first."
        lede="Start where the blast radius is small, and widen it only once the system has earned it."
      />
    </MarketingShell>
  );
}

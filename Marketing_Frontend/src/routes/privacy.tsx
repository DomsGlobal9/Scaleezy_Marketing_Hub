import { createFileRoute } from "@tanstack/react-router";

import {
  COMPANY,
  ContactLink,
  LegalList,
  LegalPage,
  LegalSection,
} from "@/components/marketing/legal-page";

export const Route = createFileRoute("/privacy")({
  head: () => ({
    meta: [
      { title: "Privacy Policy — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "How Scaleezy Marketing Hub collects, uses, stores and protects your data and connected social accounts.",
      },
      { property: "og:title", content: "Privacy Policy — Scaleezy Marketing Hub" },
    ],
  }),
  component: PrivacyPage,
});

function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="14 August 2026"
      intro="This policy explains what Scaleezy Marketing Hub collects, why we collect it, where it is stored, and the choices you have. It covers the marketing workspace, connected social accounts and AI content generation."
    >
      <LegalSection title="1. Who we are">
        <p>
          Scaleezy Marketing Hub (&ldquo;Scaleezy&rdquo;, &ldquo;we&rdquo;, &ldquo;us&rdquo;) is
          operated by {COMPANY.legalName}, registered at {COMPANY.registeredAddress}. For any
          privacy question, contact us at <ContactLink />.
        </p>
      </LegalSection>

      <LegalSection title="2. Information we collect">
        <p>We collect only what the product needs in order to work:</p>
        <LegalList
          items={[
            <>
              <strong className="text-foreground">Workspace details</strong> — workspace name,
              timezone, default language, and your customer reference in the wider Scaleezy system.
            </>,
            <>
              <strong className="text-foreground">Connected social account data</strong> — the
              account name, username, account type, profile URL and platform account ID returned by
              the platform after you authorise it, plus the role of the person who connected it.
            </>,
            <>
              <strong className="text-foreground">Authorisation tokens</strong> — the OAuth access
              and refresh tokens issued by each platform, together with their scopes and expiry.
            </>,
            <>
              <strong className="text-foreground">Marketing content</strong> — images, videos and
              other assets you upload or generate, plus the campaign briefs, captions and hashtags
              associated with them.
            </>,
            <>
              <strong className="text-foreground">Publishing records</strong> — what was published,
              to which account, when, whether it succeeded, and any error returned by the platform.
            </>,
            <>
              <strong className="text-foreground">Brand kit</strong> — your brand logo and any
              contact phone number you choose to add to generated posters.
            </>,
            <>
              <strong className="text-foreground">Audit and activity logs</strong> — connection,
              permission and token events, including the IP address and browser user agent used.
            </>,
          ]}
        />
        <p className="rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-foreground">
          <strong>We never ask for, receive or store your social media passwords.</strong>{" "}
          Authorisation always happens on the platform&rsquo;s own login page, and we only ever
          receive a revocable token.
        </p>
      </LegalSection>

      <LegalSection title="3. How we use your information">
        <LegalList
          items={[
            "To publish the content you approve to the social accounts you select.",
            "To generate marketing copy and imagery from the briefs you provide.",
            "To show you performance metrics such as reach, engagement and conversions.",
            "To keep your connections healthy — refreshing tokens and telling you when reauthorisation is needed.",
            "To maintain a security and compliance audit trail of who changed what.",
          ]}
        />
        <p>
          We do not sell your data. We use content and activity within client workspaces to improve Scaleezy's shared creative intelligence. Scaleezy does not reproduce another client's brand names, customer data, product names, taglines, or literal creative content in your generated output.
        </p>
      </LegalSection>

      <LegalSection title="4. Third-party services">
        <p>
          Operating the product means sharing some data with the providers below. Each handles data
          under its own privacy policy.
        </p>
        <LegalList
          items={[
            <>
              <strong className="text-foreground">Social platforms</strong> — Meta (Facebook,
              Instagram), LinkedIn, X, TikTok, YouTube and Google Business Profile receive the
              content you choose to publish, via their official APIs.
            </>,
            <>
              <strong className="text-foreground">Configured AI providers</strong> — campaign
              briefs and reference images are sent to the AI providers your workspace administrator
              enables and routes (currently including Google Gemini and OpenAI) to produce copy and
              imagery.
            </>,
            <>
              <strong className="text-foreground">Supabase</strong> — provides our database hosting
              and the storage bucket holding your uploaded and generated media.
            </>,
          ]}
        />
      </LegalSection>

      <LegalSection title="5. Storage and security">
        <LegalList
          items={[
            "OAuth tokens are encrypted at rest using Fernet symmetric encryption and are never exposed to the browser or written to logs in readable form.",
            "Media files are stored in a Supabase storage bucket, separate from the application database.",
            "Access to production data is limited to personnel who need it to operate the service.",
          ]}
        />
        <p>
          No system is perfectly secure. If we become aware of a breach affecting your data, we will
          notify you and the relevant authority as required by law.
        </p>
      </LegalSection>

      <LegalSection title="6. Data retention">
        <p>
          We keep your workspace data for as long as your account is active. Disconnecting a social
          account revokes and stops using its tokens, while retaining the publishing and audit
          history tied to it so your records stay complete. When you close your account we delete or
          anonymise your data within 30 days, except where we must retain it to meet a legal
          obligation.
        </p>
      </LegalSection>

      <LegalSection title="7. Your rights">
        <p>
          Depending on where you live, you may have the right to access, correct, export or delete
          your personal data, to object to or restrict processing, and to withdraw consent. You can
          disconnect any social account at any time from the Social Media Accounts page, which stops
          all future publishing to it immediately. To exercise any other right, contact us via{" "}
          <ContactLink />. We respond within 30 days.
        </p>
      </LegalSection>

      <LegalSection title="8. Cookies and local storage">
        <p>
          We use cookies and browser local storage only to keep you signed in and to remember
          preferences such as your brand kit settings. We do not use advertising or cross-site
          tracking cookies.
        </p>
      </LegalSection>

      <LegalSection title="9. International transfers">
        <p>
          Your data may be processed in countries other than your own, including by the third-party
          providers listed above. Where required, we rely on appropriate safeguards such as standard
          contractual clauses.
        </p>
      </LegalSection>

      <LegalSection title="10. Changes to this policy">
        <p>
          We may update this policy as the product changes. We will revise the &ldquo;last
          updated&rdquo; date above and, for material changes, notify you in the application.
        </p>
      </LegalSection>

      <LegalSection title="11. Contact us">
        <p>
          Questions about this policy or your data: get in touch via <ContactLink />, or write to{" "}
          {COMPANY.legalName}, {COMPANY.registeredAddress}.
        </p>
      </LegalSection>
    </LegalPage>
  );
}

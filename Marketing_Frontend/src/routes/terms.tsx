import { createFileRoute } from "@tanstack/react-router";

import {
  COMPANY,
  ContactLink,
  LegalList,
  LegalPage,
  LegalSection,
} from "@/components/marketing/legal-page";

export const Route = createFileRoute("/terms")({
  head: () => ({
    meta: [
      { title: "Terms & Conditions — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "The terms governing your use of Scaleezy Marketing Hub, including AI-generated content and third-party social platforms.",
      },
      { property: "og:title", content: "Terms & Conditions — Scaleezy Marketing Hub" },
    ],
  }),
  component: TermsPage,
});

function TermsPage() {
  return (
    <LegalPage
      title="Terms & Conditions"
      updated="14 August 2026"
      intro="These terms govern your use of Scaleezy Marketing Hub. By connecting a social account or publishing content through the service, you agree to them."
    >
      <LegalSection title="1. Agreement">
        <p>
          These terms form an agreement between you and {COMPANY.legalName}, registered at{" "}
          {COMPANY.registeredAddress}. If you are using the service for an organisation, you confirm
          you are authorised to accept these terms on its behalf. If you do not agree, do not use
          the service.
        </p>
      </LegalSection>

      <LegalSection title="2. The service">
        <p>
          Scaleezy Marketing Hub lets you generate marketing content, connect social media accounts
          through their official authorisation flows, publish approved content to those accounts,
          and review performance. Features may change, and we may add or withdraw functionality over
          time.
        </p>
      </LegalSection>

      <LegalSection title="3. Your account">
        <LegalList
          items={[
            "You are responsible for the accuracy of the information in your workspace and for activity carried out under your account.",
            "You must have the authority to connect and publish to each social account you add.",
            "You must keep your login credentials confidential and tell us promptly about any unauthorised use.",
          ]}
        />
      </LegalSection>

      <LegalSection title="4. Your content">
        <p>
          You keep all ownership of the content you upload or generate. You grant us a limited
          licence to store, process and transmit that content strictly so we can operate the service
          for you — for example, storing an asset and delivering it to the platform you selected.
          This licence ends when you delete the content or close your account.
        </p>
        <p>
          You are responsible for holding the necessary rights to everything you publish, including
          images, trademarks, music and the likeness of any person shown.
        </p>
      </LegalSection>

      <LegalSection title="5. AI-generated content">
        <p>
          The service uses generative AI to produce copy and imagery. You should understand that:
        </p>
        <LegalList
          items={[
            "AI output can be inaccurate, misleading or unsuitable. Review everything before publishing — you remain responsible for what goes out under your brand.",
            "We do not warrant that generated content is original, or that it will not resemble other material.",
            "Generated content may not be eligible for copyright protection in some jurisdictions.",
            "Claims made in generated copy — pricing, discounts, availability, product properties — must be verified by you before publication.",
          ]}
        />
        <p className="rounded-xl border border-gold/30 bg-gold/8 px-4 py-3 text-foreground">
          You are the publisher. Approving content for publication is your confirmation that it is
          accurate, lawful and appropriate for your audience.
        </p>
      </LegalSection>

      <LegalSection title="6. Third-party platforms">
        <p>
          Publishing depends on services we do not control. Your use of each social platform is
          governed by that platform&rsquo;s own terms, and you must comply with them. We are not
          responsible for:
        </p>
        <LegalList
          items={[
            "A platform rejecting, removing, restricting or delaying your content.",
            "Suspension of your account by a platform.",
            "API changes, rate limits, quota exhaustion or outages that prevent publishing.",
            "Any charge a platform levies for API access on your behalf.",
          ]}
        />
      </LegalSection>

      <LegalSection title="7. Acceptable use">
        <p>You must not use the service to:</p>
        <LegalList
          items={[
            "Publish unlawful, defamatory, hateful, harassing or deceptive content.",
            "Infringe anyone's intellectual property or privacy rights.",
            "Send spam, or publish at a volume intended to evade platform limits.",
            "Impersonate any person or organisation.",
            "Attempt to gain unauthorised access to the service or interfere with its operation.",
          ]}
        />
        <p>We may suspend or terminate access for any breach of this section.</p>
      </LegalSection>

      <LegalSection title="8. Availability">
        <p>
          We aim to keep the service available but do not guarantee uninterrupted operation. The
          service is provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo;, without warranties
          of any kind to the maximum extent permitted by law. Scheduled maintenance and dependency
          outages may interrupt publishing.
        </p>
      </LegalSection>

      <LegalSection title="9. Limitation of liability">
        <p>
          To the fullest extent permitted by law, we are not liable for indirect, incidental or
          consequential loss, or for lost profits, revenue, goodwill or data, arising from your use
          of the service. Our total aggregate liability is limited to the amount you paid us in the{" "}
          12 months preceding the claim. Nothing here excludes liability that cannot be excluded by
          law.
        </p>
      </LegalSection>

      <LegalSection title="10. Indemnity">
        <p>
          You agree to indemnify us against claims arising from content you publish through the
          service, or from your breach of these terms or of any platform&rsquo;s terms.
        </p>
      </LegalSection>

      <LegalSection title="11. Termination">
        <p>
          You may stop using the service and close your account at any time. We may suspend or
          terminate access if you breach these terms, or if required by law or by a platform. On
          termination, your right to use the service ends immediately; data handling then follows
          our Privacy Policy.
        </p>
      </LegalSection>

      <LegalSection title="12. Governing law">
        <p>
          These terms are governed by the laws of India, and the courts of {COMPANY.jurisdiction}{" "}
          have exclusive jurisdiction over any dispute.
        </p>
      </LegalSection>

      <LegalSection title="13. Changes and contact">
        <p>
          We may update these terms as the service evolves. Continued use after a change means you
          accept the revised terms. Questions: get in touch via <ContactLink />.
        </p>
      </LegalSection>
    </LegalPage>
  );
}

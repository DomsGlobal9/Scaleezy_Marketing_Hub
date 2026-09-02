import { createFileRoute, Link, redirect, useNavigate, useRouter } from "@tanstack/react-router";
import { AlertCircle, Loader2, UserPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { ApiError, apiPost } from "@/lib/api";
import type { Session } from "@/lib/auth";

/** POST /api/auth/signup/ — a session plus what it created. */
interface SignupResult extends Session {
  workspace_id: string;
  brand_id: string;
  brand_status: string;
}

export const Route = createFileRoute("/signup")({
  // Same reason as /login: the auth check reads localStorage, which does not
  // exist during SSR.
  ssr: false,
  beforeLoad: ({ context }) => {
    if (context.auth.isAuthenticated()) {
      throw redirect({ to: "/", replace: true });
    }
  },
  head: () => ({
    meta: [
      { title: "Create account — Scaleezy Marketing Hub" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: SignupPage,
});

type FieldKey =
  | "legal_name"
  | "brand_name"
  | "website"
  | "email"
  | "contact_person"
  | "contact_phone"
  | "industry"
  | "location"
  | "password";

const FIELD_KEYS: readonly FieldKey[] = [
  "legal_name",
  "brand_name",
  "website",
  "email",
  "contact_person",
  "contact_phone",
  "industry",
  "location",
  "password",
];

/**
 * The backend answers validation failures with
 * {error: {code: "VALIDATION_ERROR", fields: {name: [message]}}}. Pull the
 * first message per field so it can sit under the input that caused it.
 */
function fieldErrors(err: unknown): Partial<Record<FieldKey, string>> {
  if (!(err instanceof ApiError)) return {};
  const payload = err.payload as { error?: { fields?: Record<string, unknown> } } | null;
  const fields = payload?.error?.fields;
  if (!fields || typeof fields !== "object") return {};
  const out: Partial<Record<FieldKey, string>> = {};
  for (const key of FIELD_KEYS) {
    const value = fields[key];
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string") out[key] = first;
  }
  return out;
}

/** "acme.com" is what people type; the API wants a scheme. */
function normaliseWebsite(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function SignupPage() {
  const router = useRouter();
  const navigate = useNavigate();
  const { auth } = Route.useRouteContext();

  const [legalName, setLegalName] = useState("");
  const [brandName, setBrandName] = useState("");
  const [website, setWebsite] = useState("");
  const [email, setEmail] = useState("");
  const [contactPerson, setContactPerson] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [industry, setIndustry] = useState("");
  const [location, setLocation] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<Partial<Record<FieldKey, string>>>({});
  const [submitting, setSubmitting] = useState(false);

  const canSubmit =
    legalName.trim().length > 0 &&
    email.trim().length > 0 &&
    contactPerson.trim().length > 0 &&
    contactPhone.trim().length > 0 &&
    industry.trim().length > 0 &&
    location.trim().length > 0 &&
    password.length >= 8 &&
    confirm.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;

    setError(null);
    setFieldError({});
    if (password !== confirm) {
      setFieldError({ password: "Passwords do not match." });
      return;
    }

    setSubmitting(true);
    try {
      const result = await apiPost<SignupResult>(
        "/api/auth/signup/",
        {
          email: email.trim(),
          password,
          // The brand speaks as its trading name; when "Brand name" was left
          // blank the legal name IS the trading name.
          brand_name: brandName.trim() || legalName.trim(),
          legal_name: legalName.trim(),
          website: normaliseWebsite(website),
          industry: industry.trim(),
          location: location.trim(),
          contact_person: contactPerson.trim(),
          contact_phone: contactPhone.trim(),
        },
        { public: true },
      );

      if (!result?.access || !result?.refresh) {
        throw new Error("The server did not return a valid session.");
      }

      auth.signIn({ access: result.access, refresh: result.refresh });
      // Re-runs beforeLoad everywhere so the guard sees the new session; the
      // hub then discovers the one workspace this signup created.
      await router.invalidate();
      await navigate({ to: "/onboarding", replace: true });
    } catch (err) {
      const fields = fieldErrors(err);
      setFieldError(fields);
      if (Object.keys(fields).length === 0) {
        setError(
          err instanceof Error ? err.message : "Could not create your account. Please try again.",
        );
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-dark px-4 py-10">
      <div className="w-full max-w-lg">
        <div className="mb-8 flex flex-col items-center text-center">
          <ScaleezyLogo className="w-[12rem]" priority />
          <p className="mt-3 text-[0.625rem] tracking-[0.18em] text-white/45 uppercase">
            Marketing Hub
          </p>
        </div>

        <form onSubmit={handleSubmit} className="surface-card p-6 sm:p-8" noValidate>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">
            Create your account
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Tell us about your brand. Scaleezy reviews every new brand before calibration is
            unlocked; you can add knowledge and inspirations straight away.
          </p>

          {error ? (
            <p
              role="alert"
              className="mt-4 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/8 px-3 py-2.5 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">{error}</span>
            </p>
          ) : null}

          <div className="mt-5 space-y-4">
            <div>
              <Label htmlFor="legal_name" className="text-xs tracking-wide uppercase">
                Legal business name
              </Label>
              <Input
                id="legal_name"
                name="legal_name"
                autoComplete="organization"
                autoFocus
                required
                className="mt-1.5"
                value={legalName}
                onChange={(e) => setLegalName(e.target.value)}
                disabled={submitting}
              />
              {fieldError.legal_name ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.legal_name}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="brand_name" className="text-xs tracking-wide uppercase">
                Brand name{" "}
                <span className="normal-case text-muted-foreground">(if different)</span>
              </Label>
              <Input
                id="brand_name"
                name="brand_name"
                className="mt-1.5"
                placeholder={legalName.trim() || undefined}
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
                disabled={submitting}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                Leave blank if you trade under the legal name.
              </p>
              {fieldError.brand_name ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.brand_name}</p>
              ) : null}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="industry" className="text-xs tracking-wide uppercase">
                  Industry / vertical
                </Label>
                <Input
                  id="industry"
                  name="industry"
                  required
                  placeholder="Specialty coffee"
                  className="mt-1.5"
                  value={industry}
                  onChange={(e) => setIndustry(e.target.value)}
                  disabled={submitting}
                />
                {fieldError.industry ? (
                  <p className="mt-1 text-xs text-destructive">{fieldError.industry}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="location" className="text-xs tracking-wide uppercase">
                  City / region
                </Label>
                <Input
                  id="location"
                  name="location"
                  required
                  autoComplete="address-level2"
                  placeholder="Bengaluru, India"
                  className="mt-1.5"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  disabled={submitting}
                />
                {fieldError.location ? (
                  <p className="mt-1 text-xs text-destructive">{fieldError.location}</p>
                ) : null}
              </div>
            </div>
            <div>
              <Label htmlFor="website" className="text-xs tracking-wide uppercase">
                Website <span className="normal-case text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="website"
                name="website"
                type="text"
                inputMode="url"
                autoComplete="url"
                placeholder="acme.com"
                className="mt-1.5"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                disabled={submitting}
              />
              {fieldError.website ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.website}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="email" className="text-xs tracking-wide uppercase">
                Work email
              </Label>
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                className="mt-1.5"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
              />
              {fieldError.email ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.email}</p>
              ) : null}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="contact_person" className="text-xs tracking-wide uppercase">
                  Contact person
                </Label>
                <Input
                  id="contact_person"
                  name="contact_person"
                  required
                  autoComplete="name"
                  className="mt-1.5"
                  value={contactPerson}
                  onChange={(e) => setContactPerson(e.target.value)}
                  disabled={submitting}
                />
                {fieldError.contact_person ? (
                  <p className="mt-1 text-xs text-destructive">{fieldError.contact_person}</p>
                ) : null}
              </div>
              <div>
                <Label htmlFor="contact_phone" className="text-xs tracking-wide uppercase">
                  Contact number
                </Label>
                <Input
                  id="contact_phone"
                  name="contact_phone"
                  type="tel"
                  required
                  autoComplete="tel"
                  placeholder="+91 98765 43210"
                  className="mt-1.5"
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                  disabled={submitting}
                />
                {fieldError.contact_phone ? (
                  <p className="mt-1 text-xs text-destructive">{fieldError.contact_phone}</p>
                ) : null}
              </div>
            </div>
            <div>
              <Label htmlFor="password" className="text-xs tracking-wide uppercase">
                Password
              </Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                className="mt-1.5"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
              />
              <p className="mt-1 text-xs text-muted-foreground">At least 8 characters.</p>
              {fieldError.password ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.password}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="confirm" className="text-xs tracking-wide uppercase">
                Confirm password
              </Label>
              <Input
                id="confirm"
                name="confirm"
                type="password"
                autoComplete="new-password"
                required
                className="mt-1.5"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={submitting}
              />
            </div>
          </div>

          <Button type="submit" className="mt-6 w-full" disabled={submitting || !canSubmit}>
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Creating your account…
              </>
            ) : (
              <>
                <UserPlus className="size-4" /> Create account
              </>
            )}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-white/50">
          Already have an account?{" "}
          <Link
            to="/login"
            search={{ redirect: undefined }}
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

import { createFileRoute, Link, redirect, useNavigate, useRouter } from "@tanstack/react-router";
import { AlertCircle, Eye, EyeOff, Loader2, Sparkles, UserPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

type FieldKey = "brand_name" | "website" | "email" | "password";

const FIELD_KEYS: readonly FieldKey[] = ["brand_name", "website", "email", "password"];

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

  const [brandName, setBrandName] = useState("");
  const [website, setWebsite] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<Partial<Record<FieldKey, string>>>({});
  const [submitting, setSubmitting] = useState(false);

  const canSubmit =
    brandName.trim().length > 0 && email.trim().length > 0 && password.length >= 8 && confirm.length > 0;

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
          brand_name: brandName.trim(),
          website: normaliseWebsite(website),
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
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="grid size-12 place-items-center rounded-xl bg-brand-dark text-gold">
            <Sparkles className="size-6" strokeWidth={1.75} />
          </span>
          <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight text-foreground">
            Scaleezy
          </h1>
          <p className="mt-1 text-[0.625rem] tracking-[0.18em] text-muted-foreground uppercase">
            Marketing Hub
          </p>
        </div>

        <form onSubmit={handleSubmit} className="surface-card p-6" noValidate>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">Create your account</h2>
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
              <Label htmlFor="brand_name" className="text-xs tracking-wide uppercase">
                Brand name
              </Label>
              <Input
                id="brand_name"
                name="brand_name"
                autoComplete="organization"
                autoFocus
                required
                className="mt-1.5"
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
                disabled={submitting}
              />
              {fieldError.brand_name ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.brand_name}</p>
              ) : null}
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
            <div>
              <Label htmlFor="password" className="text-xs tracking-wide uppercase">
                Password
              </Label>
              <div className="relative mt-1.5">
                <Input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  minLength={8}
                  className="pr-10"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors flex items-center justify-center focus:outline-none"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">At least 8 characters.</p>
              {fieldError.password ? (
                <p className="mt-1 text-xs text-destructive">{fieldError.password}</p>
              ) : null}
            </div>
            <div>
              <Label htmlFor="confirm" className="text-xs tracking-wide uppercase">
                Confirm password
              </Label>
              <div className="relative mt-1.5">
                <Input
                  id="confirm"
                  name="confirm"
                  type={showConfirmPassword ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  className="pr-10"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  disabled={submitting}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword((prev) => !prev)}
                  className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors flex items-center justify-center focus:outline-none"
                  aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                >
                  {showConfirmPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
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

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Already have an account?{" "}
          <Link
            to="/login"
            search={{ redirect: undefined }}
            className="font-medium text-foreground underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

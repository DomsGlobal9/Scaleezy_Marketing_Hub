/**
 * The one sign-in form, shared by the client hub (/login) and the Scaleezy
 * staff console (/platform/login). Both post to the same endpoint; what
 * differs is what happens with the session afterwards, which the caller
 * decides in `onSession` — throw there and the message is shown as the error.
 */
import { AlertCircle, Loader2, LogIn } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScaleezyLogo } from "@/components/marketing/brand-logo";
import { apiPost } from "@/lib/api";
import type { Session } from "@/lib/auth";

export function LoginForm({
  eyebrow,
  title,
  subtitle,
  onSession,
  footer,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  onSession: (session: Session) => Promise<void>;
  footer?: ReactNode;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;

    setError(null);
    setSubmitting(true);
    try {
      const session = await apiPost<Session>(
        "/api/auth/login/",
        { username: username.trim(), password },
        { public: true },
      );

      if (!session?.access || !session?.refresh) {
        throw new Error("The server did not return a valid session.");
      }

      await onSession(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in. Please try again.");
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-dark px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <ScaleezyLogo className="w-[12rem]" priority />
          <p className="mt-3 text-[0.625rem] tracking-[0.18em] text-white/45 uppercase">
            {eyebrow}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="surface-card p-6 sm:p-8" noValidate>
          <h2 className="text-lg font-semibold tracking-tight text-foreground">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>

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
              <Label htmlFor="username" className="text-xs tracking-wide uppercase">
                Username
              </Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                autoFocus
                required
                className="mt-1.5"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={submitting}
              />
            </div>
            <div>
              <Label htmlFor="password" className="text-xs tracking-wide uppercase">
                Password
              </Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className="mt-1.5"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
              />
            </div>
          </div>

          <Button
            type="submit"
            className="mt-6 w-full"
            disabled={submitting || !username.trim() || !password}
          >
            {submitting ? (
              <>
                <Loader2 className="size-4 animate-spin" /> Signing in…
              </>
            ) : (
              <>
                <LogIn className="size-4" /> Sign in
              </>
            )}
          </Button>
        </form>

        {footer}
      </div>
    </div>
  );
}

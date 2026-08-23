import { createFileRoute, Link, redirect, useNavigate, useRouter } from "@tanstack/react-router";
import { AlertCircle, Loader2, LogIn, Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiPost } from "@/lib/api";
import { safeInternalPath, type Session } from "@/lib/auth";

export const Route = createFileRoute("/login")({
  // Same reason as /_hub: the auth check reads localStorage, which does not
  // exist during SSR. Without this the server would render the signed-out
  // branch and the client would never re-evaluate it.
  ssr: false,
  validateSearch: (search: Record<string, unknown>) => ({
    redirect: safeInternalPath(search["redirect"]) ?? undefined,
  }),
  beforeLoad: ({ context, search }) => {
    if (context.auth.isAuthenticated()) {
      throw redirect({ to: search.redirect ?? "/", replace: true });
    }
  },
  head: () => ({
    meta: [{ title: "Sign in — Scaleezy Marketing Hub" }, { name: "robots", content: "noindex" }],
  }),
  component: LoginPage,
});

function LoginPage() {
  const router = useRouter();
  const navigate = useNavigate();
  const search = Route.useSearch();
  const { auth } = Route.useRouteContext();

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

      auth.signIn(session);
      // Re-runs beforeLoad everywhere so the guard sees the new session.
      await router.invalidate();
      await navigate({ to: search.redirect ?? "/", replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in. Please try again.");
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
          <h2 className="text-lg font-semibold tracking-tight text-foreground">Sign in</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Use your workspace credentials to continue.
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

        <p className="mt-6 text-center text-xs text-muted-foreground">
          New to Scaleezy?{" "}
          <Link to="/signup" className="font-medium text-foreground underline-offset-4 hover:underline">
            Create an account
          </Link>
        </p>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Trouble signing in? Contact your workspace administrator.
        </p>
      </div>
    </div>
  );
}

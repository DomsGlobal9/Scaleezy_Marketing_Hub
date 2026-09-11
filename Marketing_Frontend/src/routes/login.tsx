import { createFileRoute, Link, redirect, useNavigate, useRouter } from "@tanstack/react-router";

import { LoginForm } from "@/components/marketing/login-form";
import { safeInternalPath } from "@/lib/auth";

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
      throw redirect({ to: search.redirect ?? "/overview", replace: true });
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

  return (
    <LoginForm
      eyebrow="Marketing Hub"
      title="Sign in"
      subtitle="Use your workspace credentials to continue."
      onSession={async (session) => {
        auth.signIn(session);
        // Re-runs beforeLoad everywhere so the guard sees the new session.
        await router.invalidate();
        await navigate({ to: search.redirect ?? "/overview", replace: true });
      }}
      footer={
        <>
          <p className="mt-6 text-center text-xs text-white/50">
            New to Scaleezy?{" "}
            <Link
              to="/signup"
              className="font-semibold text-primary underline-offset-4 hover:underline"
            >
              Create an account
            </Link>
          </p>
          <p className="mt-2 text-center text-xs text-white/40">
            Trouble signing in? Contact your workspace administrator.
          </p>
        </>
      }
    />
  );
}

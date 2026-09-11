/**
 * Scaleezy staff sign-in. `platform_.login` (trailing underscore) keeps this
 * page OUT of the /platform layout, whose guard would otherwise bounce a
 * signed-out visitor straight back here.
 *
 * Same credentials endpoint as /login; the difference is the check after: a
 * session that is not a platform admin is discarded on the spot, so a client
 * who lands here by accident ends up signed out with a clear message, never
 * inside the console and never silently dropped into their hub.
 */
import { createFileRoute, redirect, useNavigate, useRouter } from "@tanstack/react-router";

import { LoginForm } from "@/components/marketing/login-form";
import { clearMeCache, fetchMe } from "@/lib/platform";

export const Route = createFileRoute("/platform_/login")({
  ssr: false,
  beforeLoad: ({ context }) => {
    if (context.auth.isAuthenticated()) {
      throw redirect({ to: "/platform", replace: true });
    }
  },
  head: () => ({
    meta: [{ title: "Staff sign in — Scaleezy" }, { name: "robots", content: "noindex" }],
  }),
  component: PlatformLoginPage,
});

function PlatformLoginPage() {
  const router = useRouter();
  const navigate = useNavigate();
  const { auth } = Route.useRouteContext();

  return (
    <LoginForm
      eyebrow="Platform console · Scaleezy staff"
      title="Staff sign in"
      subtitle="For Scaleezy administrators only. Clients sign in to the Marketing Hub."
      onSession={async (session) => {
        auth.signIn(session);
        clearMeCache();
        const me = await fetchMe({ force: true });
        if (!me?.is_platform_admin) {
          auth.signOut();
          clearMeCache();
          throw new Error("This account does not hold Scaleezy platform authority.");
        }
        await router.invalidate();
        await navigate({ to: "/platform", replace: true });
      }}
      footer={
        <p className="mt-6 text-center text-xs text-white/40">
          Every action in the console is audited.
        </p>
      }
    />
  );
}

/**
 * /onboarding — kept only for old links and resume behaviour.
 *
 * Brand Setup is no longer a destination of its own: teaching Scaleezy a
 * brand happens inside Brand Master ("Teach Scaleezy"), so this route simply
 * lands there. Nothing renders here.
 */
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_hub/onboarding")({
  beforeLoad: () => {
    throw redirect({ to: "/brand-master", search: { tab: "teach" }, replace: true });
  },
  component: () => null,
});

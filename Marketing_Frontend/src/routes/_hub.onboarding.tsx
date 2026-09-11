/**
 * /onboarding — an address, not a page. Old bookmarks land on the setup
 * wizard, which itself forwards a finished client to the hub.
 */
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_hub/onboarding")({
  beforeLoad: () => {
    throw redirect({ to: "/setup", search: {}, replace: true });
  },
});

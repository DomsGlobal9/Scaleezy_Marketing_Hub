/**
 * /onboarding — now just an address, not a page.
 *
 * The guided wizard that lived here was a re-sequenced view over the same
 * panels and endpoints as Brand Master's "Teach Scaleezy" tab: the same
 * server-derived onboarding summary, the same skip/calibrate/react calls, the
 * same knowledge and inspiration panels. Teach is resumable from anywhere by
 * construction, so one surface now owns setup and this route forwards to it.
 *
 * The path itself stays routable on purpose:
 *
 *  - old bookmarks and deep links to /onboarding (any ?step= is dropped —
 *    teach re-derives the position from the server) keep landing somewhere
 *    sensible, and
 *  - AddClientDialog rewrites the address bar to /onboarding with
 *    history.replaceState and then reloads, precisely so the fresh document
 *    boots already addressed to the new client. beforeLoad throws before any
 *    component mounts, so that guarantee holds: the first thing to call
 *    /brands/current/ is Brand Master, under the new workspace id.
 */
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/_hub/onboarding")({
  beforeLoad: () => {
    // Unconditional alias, so unlike the stateful auth bounces in /_hub and
    // /platform it is safe (and right) to follow during preloads too.
    throw redirect({ to: "/brand-master", search: { tab: "teach" }, replace: true });
  },
});

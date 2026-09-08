import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
import { createAuthStore } from "./lib/auth";
import { setSessionExpiredHandler } from "./lib/api";

export const getRouter = () => {
  const queryClient = new QueryClient();
  // Built per router, like the QueryClient above. Never at module scope: on a
  // server runtime that would be one instance shared by concurrent requests.
  const auth = createAuthStore();

  const router = createRouter({
    routeTree,
    context: { queryClient, auth },
    scrollRestoration: true,
    // Fetch and parse a route's chunk on hover/touchstart instead of on the
    // click itself. Without this, pressing "Create content" downloaded and
    // compiled the whole Create Studio bundle inside the click — Vercel's
    // field data flagged that navigation at 200ms+ of blocked input.
    defaultPreload: "intent",
    defaultPreloadStaleTime: 0,
  });

  // When a refresh fails mid-session, re-run the route guards so the user is
  // sent to /login instead of staring at a page that silently stopped loading.
  setSessionExpiredHandler(() => {
    void router.invalidate();
  });

  return router;
};

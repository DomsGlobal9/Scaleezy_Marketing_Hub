import { createFileRoute, redirect } from "@tanstack/react-router";

// Governed Autopilot now lives inside Admin as the "Missions" tab, behind
// Admin's OWNER/ADMIN gate. This route only keeps old links and bookmarks
// working.
export const Route = createFileRoute("/_hub/autopilot")({
  beforeLoad: ({ preload }) => {
    // Preloads must not trigger navigation side effects.
    if (preload) return;
    throw redirect({ to: "/admin", search: { tab: "missions" }, replace: true });
  },
});

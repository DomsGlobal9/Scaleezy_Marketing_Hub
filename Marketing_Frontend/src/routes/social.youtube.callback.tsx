import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";

export const Route = createFileRoute("/social/youtube/callback")({
  component: YouTubeCallbackPage,
});

function YouTubeCallbackPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");
    const errorDescription = params.get("error_description");

    // Handle YouTube OAuth errors
    if (error) {
      const msg = errorDescription || "YouTube authorization was not granted.";
      setStatus("error");
      setErrorMessage(msg);
      toast.error(msg);
      setTimeout(() => navigate({ to: "/accounts" }), 3000);
      return;
    }

    if (!code || !state) {
      setStatus("error");
      setErrorMessage("Invalid callback parameters — missing authorization code or state.");
      toast.error("Invalid OAuth callback parameters.");
      setTimeout(() => navigate({ to: "/accounts" }), 3000);
      return;
    }

    // Exchange code for token via backend
    apiFetch("/api/marketing/social-accounts/oauth_callback/", {
      public: true,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: "YOUTUBE",
        code,
        state,
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setStatus("success");
          toast.success("YouTube channel connected successfully!");
          setTimeout(() => navigate({ to: "/accounts" }), 2000);
        } else {
          const msg = data.message || data.error?.message || "Failed to connect YouTube channel.";
          setStatus("error");
          setErrorMessage(msg);
          toast.error(msg);
          setTimeout(() => navigate({ to: "/accounts" }), 3000);
        }
      })
      .catch((err) => {
        console.error("YouTube callback error:", err);
        setStatus("error");
        setErrorMessage("Network error while connecting YouTube channel.");
        toast.error("Network error during YouTube connection.");
        setTimeout(() => navigate({ to: "/accounts" }), 3000);
      });
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center max-w-md px-6">
        {status === "loading" && (
          <>
            <Loader2 className="mx-auto size-10 animate-spin text-primary" />
            <h2 className="mt-4 text-lg font-semibold text-foreground">
              Connecting your YouTube channel…
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Please wait while we verify your authorization with Google.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <CheckCircle2 className="mx-auto size-10 text-emerald-500" />
            <h2 className="mt-4 text-lg font-semibold text-foreground">
              YouTube Connected!
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Redirecting you back to Social Accounts…
            </p>
          </>
        )}

        {status === "error" && (
          <>
            <AlertTriangle className="mx-auto size-10 text-amber-500" />
            <h2 className="mt-4 text-lg font-semibold text-foreground">
              Connection Failed
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">{errorMessage}</p>
            <p className="mt-3 text-xs text-muted-foreground">
              Redirecting you back to Social Accounts…
            </p>
          </>
        )}
      </div>
    </div>
  );
}

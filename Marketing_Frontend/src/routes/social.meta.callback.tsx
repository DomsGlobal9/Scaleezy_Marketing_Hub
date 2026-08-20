import { useEffect, useState, useRef } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";

export const Route = createFileRoute("/social/meta/callback")({
  component: MetaCallbackPage,
});

function MetaCallbackPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState("");

  const fired = useRef(false);

  useEffect(() => {
    if (fired.current) return;
    fired.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");
    const errorDescription = params.get("error_description");

    // Handle Meta OAuth errors (user denied, etc.)
    if (error) {
      const msg = errorDescription || "Meta authorization was not granted.";
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
        platform: "FACEBOOK", // Backend routes both FACEBOOK and INSTAGRAM through the unified flow
        code,
        state,
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setStatus("success");
          toast.success("Meta accounts synced successfully!");
          setTimeout(() => navigate({ to: "/accounts" }), 2000);
        } else {
          const msg = data.message || data.error?.message || "Failed to connect Meta accounts.";
          setStatus("error");
          setErrorMessage(msg);
          toast.error(msg);
          setTimeout(() => navigate({ to: "/accounts" }), 3000);
        }
      })
      .catch((err) => {
        console.error("Meta callback error:", err);
        setStatus("error");
        setErrorMessage("Network error while connecting Meta accounts.");
        toast.error("Network error during Meta connection.");
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
              Syncing your Meta accounts…
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Please wait while we verify your authorization and sync your Facebook Pages and Instagram accounts.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <CheckCircle2 className="mx-auto size-10 text-emerald-500" />
            <h2 className="mt-4 text-lg font-semibold text-foreground">
              Meta Connected!
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

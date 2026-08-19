import { useEffect } from "react";
import { createFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/oauth/callback")({
  component: OAuthCallbackPage,
});

function OAuthCallbackPage() {
  const navigate = useNavigate();
  const search = useSearch({ from: "/oauth/callback" }) as { code?: string; state?: string };

  useEffect(() => {
    if (!search.code || !search.state) {
      toast.error("Invalid OAuth callback parameters.");
      navigate({ to: "/accounts" });
      return;
    }

    // Call the backend to exchange code for token
    fetch(import.meta.env.VITE_API_URL + "/api/marketing/social-accounts/oauth_callback/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        // X is the only platform using this generic callback; YouTube, Meta and
        // LinkedIn each have their own /social/<platform>/callback route.
        platform: "X",
        code: search.code,
        state: search.state,
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          toast.success("Account connected successfully!");
        } else {
          toast.error(data.message || "Failed to connect account.");
        }
        navigate({ to: "/accounts" });
      })
      .catch((err) => {
        console.error(err);
        toast.error("Network error during connection.");
        navigate({ to: "/accounts" });
      });
  }, [search.code, search.state, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center">
        <Loader2 className="mx-auto size-8 animate-spin text-primary" />
        <h2 className="mt-4 text-lg font-medium text-foreground">Completing connection...</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Please wait while we verify your account.
        </p>
      </div>
    </div>
  );
}

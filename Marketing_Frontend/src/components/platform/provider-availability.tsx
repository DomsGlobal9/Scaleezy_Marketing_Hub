import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, ErrorNote, type ConfirmRequest } from "@/components/platform/shared";
import { PlatformListControls } from "@/components/platform/list-controls";
import { apiPost } from "@/lib/api";
import { usePlatformPage } from "@/lib/use-platform-page";

interface ProviderAvailability {
  id: string;
  key: string;
  display_name: string;
  is_available: boolean;
}

/** Platform emergency availability, not a second credential/routing console. */
export function ProviderAvailabilityPanel() {
  const { items, pageInfo, loading, error, load, setPage, setQuery } =
    usePlatformPage<ProviderAvailability>("/api/platform/providers/", "providers");
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const change = (provider: ProviderAvailability) =>
    setConfirm({
      title: `${provider.is_available ? "Disable" : "Make available"} ${provider.display_name} platform-wide?`,
      description: provider.is_available
        ? "New routing decisions across every client will exclude this provider. Calls already running are not cancelled. Credentials and client routing choices stay unchanged."
        : "Existing client enablement and routing will determine whether this provider is used. This does not add routes, credentials or run a provider check.",
      confirmLabel: provider.is_available ? "Disable platform-wide" : "Make available",
      destructive: provider.is_available,
      run: async () => {
        await apiPost(`/api/platform/providers/${provider.id}/availability/`, {
          is_available: !provider.is_available,
        });
        toast.success("Platform availability updated.");
        await load();
      },
    });
  return (
    <section className="mt-8 surface-card p-5">
      <h2 className="text-lg font-semibold">Provider availability</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Platform-wide emergency controls. Client credentials and capability routing remain in
        workspace Admin. Every change is audited.
      </p>
      <PlatformListControls
        pageInfo={pageInfo}
        loading={loading}
        setPage={setPage}
        setQuery={setQuery}
      />
      <ErrorNote message={error} />
      {error ? (
        <Button className="my-3" variant="outline" disabled={loading} onClick={() => void load()}>
          Retry availability
        </Button>
      ) : null}
      {loading && !items ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading provider availability…
        </p>
      ) : !error && items?.length === 0 ? (
        <p className="text-sm text-muted-foreground">No catalogue providers match this search.</p>
      ) : null}
      <div className="space-y-2">
        {items?.map((provider) => (
          <div
            key={provider.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3"
          >
            <div>
              <p className="font-medium">{provider.display_name}</p>
              <p className="text-xs text-muted-foreground">
                {provider.is_available
                  ? "Available to configured clients"
                  : "Unavailable platform-wide"}
              </p>
            </div>
            <Button variant="outline" size="sm" disabled={loading} onClick={() => change(provider)}>
              {provider.is_available ? "Disable" : "Make available"}
            </Button>
          </div>
        ))}
      </div>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}

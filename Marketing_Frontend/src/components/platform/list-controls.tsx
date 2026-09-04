import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { PlatformPageInfo } from "@/lib/use-platform-page";

export function PlatformListControls({
  pageInfo,
  loading,
  setPage,
  setQuery,
}: {
  pageInfo: PlatformPageInfo | null;
  loading: boolean;
  setPage: (page: number) => void;
  setQuery: (query: string) => void;
}) {
  const [search, setSearch] = useState("");
  return (
    <div className="my-4 flex flex-wrap items-center justify-between gap-3">
      <form
        className="flex w-full gap-2 sm:w-auto"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(search.trim());
        }}
      >
        <Input
          aria-label="Search this list"
          placeholder="Search…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="sm:w-64"
        />
        <Button type="submit" variant="outline" disabled={loading}>
          Search
        </Button>
      </form>
      <div className="flex flex-wrap items-center gap-2">
        <span role="status" className="text-xs text-muted-foreground">
          {loading
            ? "Loading page…"
            : pageInfo
              ? `${pageInfo.total} results · page ${pageInfo.page} of ${Math.max(1, pageInfo.total_pages)}`
              : "Results unavailable"}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={loading || !pageInfo?.previous_page}
          onClick={() => pageInfo?.previous_page && setPage(pageInfo.previous_page)}
        >
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={loading || !pageInfo?.next_page}
          onClick={() => pageInfo?.next_page && setPage(pageInfo.next_page)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

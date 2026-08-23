/**
 * Is what this brand learned actually reaching its work?
 *
 * The rest of the Learning tab shows what exists. This panel shows whether
 * any of it matters: for every rule and preference, whether it is in the
 * compiled Brand Brain (which is literally what a generation receives),
 * how many recorded generations used it, and when it last fired. A rule
 * that is active but ignored is the finding this panel exists to surface —
 * it renders with a reason, never as quietly healthy.
 *
 * The numbers state their own limits: counts come from generation traces,
 * so a zero means "not seen in the scanned window", never "never used".
 * That caveat is printed rather than implied.
 */
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Chip, Empty, InlineError, Loading, useSlice } from "@/components/marketing/brand-master-primitives";
import { SectionTitle } from "@/components/marketing/primitives";
import { fetchLearningUsage, type LearningUsageRow } from "@/lib/brand-master";

const REASON_LABEL: Record<string, string> = {
  DEACTIVATED: "Deactivated",
  RETIRED: "Retired",
  NOT_IN_COMPILED_BRAIN: "Not in the compiled brain",
};

function ago(value: string | null): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 60) return `${days} d ago`;
  return `${Math.floor(days / 30)} mo ago`;
}

function kindChip(row: LearningUsageRow) {
  if (row.kind === "PREFERENCE") return <Chip tone="ai">Preference</Chip>;
  if (row.hardness === "HARD") return <Chip tone="hard">Hard rule</Chip>;
  return <Chip tone="soft">{row.origin === "LEARNED" ? "Learned rule" : "Soft rule"}</Chip>;
}

function statusChip(row: LearningUsageRow) {
  if (row.in_force) return <Chip tone="user">In force</Chip>;
  return <Chip tone="warn">{REASON_LABEL[row.not_in_force_reason] ?? "Not in force"}</Chip>;
}

export function LearningUsagePanel({ brandId }: { brandId: string }) {
  const report = useSlice(() => fetchLearningUsage(brandId), true);

  if (report.loading && !report.data) return <Loading rows={2} />;
  if (report.error) {
    return <InlineError message={`Could not load learning usage: ${report.error}`} />;
  }
  const data = report.data;
  if (!data) return null;

  const rows = data.rows ?? [];

  return (
    <section>
      <SectionTitle
        label="Learning"
        title="Is it reaching the work?"
        description="Every rule and preference, with whether it sits in the compiled Brand Brain — which is exactly what a generation receives — and how often recent generations used it."
        action={
          <Button variant="ghost" size="sm" onClick={report.reload}>
            <RefreshCw className="size-4" /> Refresh
          </Button>
        }
      />

      {rows.length === 0 ? (
        <Empty
          title="Nothing learned yet"
          hint="State a rule, confirm a fact, or review some content — what accumulates here is what generation obeys."
        />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
            <Chip tone="user">{data.totals.in_force} in force</Chip>
            {data.totals.not_in_force > 0 ? (
              <Chip tone="warn">{data.totals.not_in_force} not reaching generation</Chip>
            ) : null}
            {data.totals.never_used > 0 ? (
              <Chip tone="soft">{data.totals.never_used} in force but not seen in a generation yet</Chip>
            ) : null}
          </div>

          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[40rem] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40 text-left text-[0.6875rem] tracking-wide text-muted-foreground uppercase">
                  <th className="px-3 py-2 font-medium">Instruction</th>
                  <th className="px-3 py-2 font-medium">Kind</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Used</th>
                  <th className="px-3 py-2 font-medium">Last used</th>
                  <th className="px-3 py-2 text-right font-medium">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-border/60 last:border-b-0">
                    <td className="max-w-[22rem] px-3 py-2">
                      <p className="truncate text-foreground" title={row.text}>
                        {row.text}
                      </p>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{kindChip(row)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{statusChip(row)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {row.generations_used > 0 ? (
                        `${row.generations_used}×`
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                      {ago(row.last_used_at)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                      {row.evidence_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-2 text-[0.6875rem] text-muted-foreground">
            Counted from the last {data.attribution.generations_scanned} recorded generation
            {data.attribution.generations_scanned === 1 ? "" : "s"} (window:{" "}
            {data.attribution.scan_limit}). Content generated before usage tracing shipped carries
            no attribution, so a zero means “not seen in this window”, never “never used”.
          </p>
        </>
      )}
    </section>
  );
}

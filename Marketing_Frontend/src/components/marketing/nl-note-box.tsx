/**
 * "Tell Scaleezy about your brand" — plain language in, proposal cards out.
 *
 * The note is kept verbatim the moment it is sent, but NOTHING reaches the
 * brand profile until a card is accepted: each Accept writes exactly one
 * record through the service that already owns that kind (a confirmed fact,
 * a preference, a soft rule), and the server says which one it became. The
 * parse is provider spend, so an unapproved client sees the same refusal
 * generation does — printed verbatim, never softened.
 *
 * `EnrichFromWebsite` is the sibling control: one bounded pass over the
 * brand's own site that captures pages as candidate sources. It reports what
 * it fetched, what was unchanged and what it created, and says plainly that
 * nothing was added to the profile — candidates wait to be confirmed.
 */
import { Check, Globe, Loader2, MessageSquareText, RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Chip, InlineError } from "@/components/marketing/brand-master-primitives";
import {
  acceptNoteProposal,
  enrichBrandFromSite,
  errorText,
  submitBrandNote,
  type EnrichReport,
  type NoteProposal,
  type NoteResult,
} from "@/lib/platform";

const KIND_COPY: Record<string, { label: string; tone: "user" | "ai" | "soft" | "warn" | "hard" }> =
  {
    FACT: { label: "Fact", tone: "user" },
    AUDIENCE: { label: "Audience", tone: "user" },
    PREFERENCE: { label: "Preference", tone: "ai" },
    TONE: { label: "Tone", tone: "ai" },
    SOFT_RULE: { label: "Soft rule", tone: "warn" },
  };

function ProposalCard({
  proposal,
  accepted,
  busy,
  onAccept,
}: {
  proposal: NoteProposal;
  accepted: string | null;
  busy: boolean;
  onAccept: () => void;
}) {
  const kind = KIND_COPY[proposal.kind] ?? {
    label: proposal.kind || "Proposal",
    tone: "soft" as const,
  };
  const claim = [proposal.category, proposal.attribute].filter(Boolean).join(" / ");
  return (
    <li className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={kind.tone}>{kind.label}</Chip>
            {claim ? (
              <span className="font-mono text-[0.6875rem] text-muted-foreground">
                {claim}
                {proposal.value ? ` = ${proposal.value}` : ""}
              </span>
            ) : null}
          </div>
          <p className="mt-2 text-sm text-foreground">{proposal.text || proposal.value}</p>
          {proposal.quote ? (
            <p className="mt-1.5 border-l-2 border-border pl-2 text-xs text-muted-foreground italic">
              "{proposal.quote}"
            </p>
          ) : null}
        </div>
        {accepted ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
            <Check className="size-3.5" /> {accepted}
          </span>
        ) : (
          <Button size="sm" variant="outline" onClick={onAccept} disabled={busy}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
            Accept
          </Button>
        )}
      </div>
    </li>
  );
}

export function NlNoteBox({ brandId, onChanged }: { brandId: string; onChanged?: () => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<NoteResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<Record<number, string>>({});
  const [acceptingIndex, setAcceptingIndex] = useState<number | null>(null);

  const submit = async () => {
    const body = text.trim();
    if (!body || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    setAccepted({});
    try {
      setResult(await submitBrandNote(brandId, body));
    } catch (e: unknown) {
      setError(errorText(e, "Scaleezy could not read that note right now."));
    } finally {
      setSubmitting(false);
    }
  };

  const accept = async (index: number, proposal: NoteProposal) => {
    if (!result || acceptingIndex !== null) return;
    setAcceptingIndex(index);
    setError(null);
    try {
      const saved = await acceptNoteProposal(brandId, result.note_id, proposal);
      setAccepted((prev) => ({ ...prev, [index]: saved.message || "Saved" }));
      toast.success(saved.message || "Saved.");
      onChanged?.();
    } catch (e: unknown) {
      setError(errorText(e, "That proposal could not be saved."));
    } finally {
      setAcceptingIndex(null);
    }
  };

  const reset = () => {
    setText("");
    setResult(null);
    setAccepted({});
    setError(null);
  };

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
            <MessageSquareText className="size-4.5" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <h3 className="text-base font-semibold tracking-tight text-foreground">
              Tell Scaleezy about your brand
            </h3>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Write it the way you would say it. Scaleezy turns it into cards — facts, preferences,
              rules — and nothing is saved until you accept a card.
            </p>
          </div>
        </div>

        {!result ? (
          <div className="space-y-3">
            <div>
              <Label htmlFor="nl-note" className="sr-only">
                Your note
              </Label>
              <Textarea
                id="nl-note"
                rows={4}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="e.g. We never discount publicly. Our buyers are boutique owners who care about fabric provenance more than price. Keep captions short and warm."
                disabled={submitting}
              />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                Your words are kept as a note; only accepted cards become brand intelligence.
              </p>
              <Button onClick={() => void submit()} disabled={submitting || !text.trim()}>
                {submitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Reading…
                  </>
                ) : (
                  <>
                    <Sparkles className="size-4" /> Propose cards
                  </>
                )}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-foreground">
              {result.note_text}
            </p>
            {result.proposals.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Scaleezy did not find anything it could turn into a card. The note itself is kept.
              </p>
            ) : (
              <ul className="space-y-2">
                {result.proposals.map((proposal, index) => (
                  <ProposalCard
                    key={`${proposal.kind}-${index}`}
                    proposal={proposal}
                    accepted={accepted[index] ?? null}
                    busy={acceptingIndex === index}
                    onAccept={() => void accept(index, proposal)}
                  />
                ))}
              </ul>
            )}
            {result.note ? <p className="text-xs text-muted-foreground">{result.note}</p> : null}
            <div className="flex justify-end">
              <Button variant="ghost" size="sm" onClick={reset}>
                Write another note
              </Button>
            </div>
          </div>
        )}

        <InlineError message={error} />
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------- enrichment */

function countOf(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

export function EnrichFromWebsite({
  brandId,
  onChanged,
}: {
  brandId: string;
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<EnrichReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const next = await enrichBrandFromSite(brandId);
      setReport(next);
      if (countOf(next.sources_created) > 0) onChanged?.();
    } catch (e: unknown) {
      setError(errorText(e, "Scaleezy could not read your website right now."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-gold/15 text-gold">
            <Globe className="size-4.5" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">Refresh from my website</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              One bounded pass over the brand's own site. Pages are captured as sources you can
              confirm facts from — nothing is added to the profile by itself.
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={() => void run()} disabled={busy}>
          <RefreshCw className={busy ? "size-4 animate-spin" : "size-4"} />
          {busy ? "Reading…" : "Refresh"}
        </Button>
      </div>

      {report ? (
        <div className="mt-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
          {report.skipped ? (
            <p className="text-foreground">Skipped{report.reason ? `: ${report.reason}` : "."}</p>
          ) : (
            <>
              <p className="text-foreground">
                {report.host ? (
                  <>
                    <span className="font-mono">{report.host}</span> ·{" "}
                  </>
                ) : null}
                {report.pages_fetched} page{report.pages_fetched === 1 ? "" : "s"} fetched ·{" "}
                {report.pages_unchanged ?? 0} unchanged · {countOf(report.sources_created)} new
                source
                {countOf(report.sources_created) === 1 ? "" : "s"}
                {countOf(report.errors)
                  ? ` · ${countOf(report.errors)} error${countOf(report.errors) === 1 ? "" : "s"}`
                  : ""}
              </p>
              {countOf(report.errors) ? (
                <ul className="mt-1 space-y-0.5 text-muted-foreground">
                  {(report.errors ?? []).slice(0, 5).map((entry, index) => (
                    <li key={index} className="break-all">
                      {typeof entry === "string"
                        ? entry
                        : `${String(entry["url"] ?? "")} — ${String(entry["error"] ?? "")}`}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
          {report.note ? <p className="mt-1 text-muted-foreground">{report.note}</p> : null}
        </div>
      ) : null}

      {error ? (
        <div className="mt-3">
          <InlineError message={error} />
        </div>
      ) : null}
    </div>
  );
}

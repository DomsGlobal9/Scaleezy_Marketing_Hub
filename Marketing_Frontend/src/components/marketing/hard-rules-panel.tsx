/**
 * Hard rules — brand law a human writes, as opposed to what Scaleezy learns.
 *
 * These are the only rules allowed to BLOCK a generation before any AI is
 * paid. Everything is empty by default: a brand that writes nothing here
 * generates exactly as before. Lists save on change; each chip is one rule.
 */
import { Loader2, Plus, ShieldCheck, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

interface Guardrails {
  forbidden_words: string[];
  banned_hashtags: string[];
  forbidden_imagery: string[];
  required_on_every_post: string[];
  approved_ctas: string[];
  language_rule: string;
}

const EMPTY: Guardrails = {
  forbidden_words: [],
  banned_hashtags: [],
  forbidden_imagery: [],
  required_on_every_post: [],
  approved_ctas: [],
  language_rule: "",
};

type ListKey = Exclude<keyof Guardrails, "language_rule">;

const LISTS: { key: ListKey; label: string; hint: string; placeholder: string }[] = [
  {
    key: "forbidden_words",
    label: "Never say",
    hint: "Words that must never appear in any caption or brief. A brief using one is refused before any AI is paid.",
    placeholder: "e.g. cheap",
  },
  {
    key: "forbidden_imagery",
    label: "Never show",
    hint: "Visual motifs that are refused in your briefs and written into the image instructions as banned.",
    placeholder: "e.g. butterflies",
  },
  {
    key: "banned_hashtags",
    label: "Banned hashtags",
    hint: "Stripped automatically if the AI ever writes one.",
    placeholder: "e.g. #sale",
  },
  {
    key: "required_on_every_post",
    label: "On every post",
    hint: "Lines every caption must carry, verbatim — your website, your tagline. Added automatically when missing.",
    placeholder: "e.g. yourbrand.com",
  },
  {
    key: "approved_ctas",
    label: "DM keywords",
    hint: "The only call-to-action keywords allowed. Every caption gets one.",
    placeholder: "e.g. PROTECT",
  },
];

function cleanFrom(raw: unknown): Guardrails {
  const source = (raw ?? {}) as Record<string, unknown>;
  const list = (key: string) =>
    Array.isArray(source[key]) ? (source[key] as unknown[]).map(String).filter(Boolean) : [];
  return {
    forbidden_words: list("forbidden_words"),
    banned_hashtags: list("banned_hashtags"),
    forbidden_imagery: list("forbidden_imagery"),
    required_on_every_post: list("required_on_every_post"),
    approved_ctas: list("approved_ctas"),
    language_rule:
      source["language_rule"] === "english_only" || source["language_rule"] === "hinglish_allowed"
        ? (source["language_rule"] as string)
        : "",
  };
}

export function HardRulesPanel({ brandId }: { brandId: string }) {
  const [rules, setRules] = useState<Guardrails | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<{ guardrails?: unknown }>(`/api/marketing/brands/${brandId}/`)
      .then((brand) => {
        if (!cancelled) setRules(cleanFrom(brand.guardrails));
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load hard rules.");
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  // Saves are chained: two quick chip-adds must not race each other's PATCH
  // of the whole object, or the slower response silently deletes the faster
  // chip. Each save also re-reads the freshest local state at send time.
  const latest = useRef<Guardrails | null>(null);
  latest.current = rules;
  const chain = useRef<Promise<void>>(Promise.resolve());

  const save = (mutate: (current: Guardrails) => Guardrails) => {
    if (!latest.current) return;
    setRules((current) => (current ? mutate(current) : current));
    setSaving(true);
    chain.current = chain.current.then(async () => {
      const next = latest.current;
      if (!next) return;
      try {
        const updated = await api<{ guardrails?: unknown }>(`/api/marketing/brands/${brandId}/`, {
          method: "PATCH",
          body: { guardrails: next },
        });
        setRules(cleanFrom(updated.guardrails));
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Could not save the rule.");
        // Reload the stored truth rather than guessing which edit failed.
        try {
          const brand = await api<{ guardrails?: unknown }>(`/api/marketing/brands/${brandId}/`);
          setRules(cleanFrom(brand.guardrails));
        } catch {
          /* keep the optimistic state; the next save retries */
        }
      } finally {
        setSaving(false);
      }
    });
  };

  const addTo = (key: ListKey) => {
    const term = (drafts[key] ?? "").trim();
    if (!term || !rules) return;
    setDrafts((d) => ({ ...d, [key]: "" }));
    if (rules[key].some((t) => t.toLowerCase() === term.toLowerCase())) return;
    save((current) => ({ ...current, [key]: [...current[key], term] }));
  };

  const removeFrom = (key: ListKey, term: string) => {
    save((current) => ({ ...current, [key]: current[key].filter((t) => t !== term) }));
  };

  if (error) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-destructive">{error}</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="size-4 text-primary" />
          Hard rules
          {saving ? <Loader2 className="size-3.5 animate-spin text-muted-foreground" /> : null}
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Enforced mechanically: a brief that breaks one is refused before any AI is paid, banned
          hashtags are stripped, required lines are added. The stated and learned rules below guide
          the AI&rsquo;s wording; these here are the ones the system enforces itself. Leave anything
          empty and nothing changes.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        {!rules ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading…
          </div>
        ) : (
          <>
            {LISTS.map(({ key, label, hint, placeholder }) => (
              <div key={key}>
                <p className="text-sm font-medium">{label}</p>
                <p className="text-xs text-muted-foreground">{hint}</p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {rules[key].map((term) => (
                    <span
                      key={term}
                      className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-2.5 py-0.5 text-xs"
                    >
                      {term}
                      <button
                        type="button"
                        aria-label={`Remove ${term}`}
                        onClick={() => removeFrom(key, term)}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <X className="size-3" />
                      </button>
                    </span>
                  ))}
                  <form
                    className="flex items-center gap-1"
                    onSubmit={(e) => {
                      e.preventDefault();
                      addTo(key);
                    }}
                  >
                    <Input
                      value={drafts[key] ?? ""}
                      onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
                      placeholder={placeholder}
                      maxLength={120}
                      className="h-7 w-40 text-xs"
                    />
                    <Button type="submit" size="sm" variant="outline" className="h-7 px-2">
                      <Plus className="size-3.5" />
                    </Button>
                  </form>
                </div>
              </div>
            ))}
            <div>
              <p className="text-sm font-medium">Language</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(
                  [
                    ["", "No rule"],
                    ["english_only", "English only"],
                    ["hinglish_allowed", "Hinglish allowed"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => save((current) => ({ ...current, language_rule: value }))}
                    className={
                      rules.language_rule === value
                        ? "rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                        : "rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-primary hover:text-foreground"
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

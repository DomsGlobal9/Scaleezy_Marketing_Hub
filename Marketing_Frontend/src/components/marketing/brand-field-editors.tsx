/**
 * The editors for the Brand columns that are JSON rather than text.
 *
 * Palette, fonts, competitors, products/services and social links were all
 * API-writable long before anything could edit them, so the only way to change
 * them was a hand-written PATCH. Each editor below writes the whole collection
 * back through `useBrandSettings().update`, which is optimistic and debounced —
 * so typing feels local while the record stays the only source of truth.
 *
 * Map keys (a palette role, a platform) are added and removed rather than
 * renamed in place: renaming per keystroke would write "i", "in", "ins"… as
 * separate roles and leave the JSONField full of debris that nothing renders.
 */
import { Plus, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { ProductService } from "@/lib/brand-settings";

export function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <Label className="text-xs tracking-wide uppercase">{label}</Label>
      <div className="mt-1.5">{children}</div>
      {hint ? <p className="mt-1.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function Toggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string | undefined;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-border px-4 py-3">
      <div className="min-w-0">
        <Label className="text-sm font-normal">{label}</Label>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}

/** Nothing here yet, said in the same voice as the rest of the product. */
function NothingYet({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-xl border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}

/* ------------------------------------------------------------------ palette */

/** Roles the poster layouts look for. Anything else is allowed, just untyped. */
const PALETTE_ROLES = ["primary", "light", "accent", "secondary", "dark", "muted"];

const isHex = (value: string) => /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value.trim());

export function PaletteEditor({
  value,
  disabled,
  onChange,
}: {
  value: Record<string, string>;
  disabled?: boolean;
  onChange: (next: Record<string, string>) => void;
}) {
  const entries = Object.entries(value);
  const unused = PALETTE_ROLES.filter((role) => !(role in value));
  const [role, setRole] = useState("");

  const add = () => {
    const key = role.trim().toLowerCase();
    if (!key || key in value) return;
    onChange({ ...value, [key]: "#221F3C" });
    setRole("");
  };

  const remove = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };

  return (
    <div className="space-y-3">
      {entries.length === 0 ? (
        <NothingYet>No colours yet. Add your primary brand colour to start.</NothingYet>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {entries.map(([key, colour]) => (
            <div key={key} className="flex items-center gap-2 rounded-xl border px-3 py-2">
              {/* A native colour well cannot express an unset or non-hex value,
                  so the text input stays authoritative and the well is a
                  shortcut that only appears once the value is a real hex. */}
              <input
                type="color"
                aria-label={`${key} colour`}
                className="size-7 shrink-0 cursor-pointer rounded border bg-transparent p-0 disabled:cursor-default"
                value={isHex(colour) ? colour : "#000000"}
                disabled={disabled}
                onChange={(e) => onChange({ ...value, [key]: e.target.value })}
              />
              <span className="w-20 shrink-0 truncate text-xs text-muted-foreground">{key}</span>
              <Input
                className="h-8 min-w-0 flex-1 font-mono text-xs"
                value={colour}
                disabled={disabled}
                onChange={(e) => onChange({ ...value, [key]: e.target.value })}
              />
              <Button
                variant="ghost"
                size="icon"
                className="size-7 shrink-0"
                disabled={disabled}
                aria-label={`Remove ${key}`}
                onClick={() => remove(key)}
              >
                <X className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="h-8 w-40"
          placeholder="Role, e.g. accent"
          value={role}
          disabled={disabled}
          onChange={(e) => setRole(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button size="sm" variant="outline" disabled={disabled || !role.trim()} onClick={add}>
          <Plus className="size-3.5" /> Add colour
        </Button>
        {unused.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={disabled}
            onClick={() => onChange({ ...value, [suggestion]: "#221F3C" })}
            className="rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            + {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- key / value */

/**
 * A flat string map. Used for fonts and social links, which the backend
 * validates as exactly that shape.
 */
export function KeyValueEditor({
  value,
  disabled,
  keyLabel,
  valuePlaceholder,
  suggestions = [],
  emptyHint,
  onChange,
}: {
  value: Record<string, string>;
  disabled?: boolean;
  keyLabel: string;
  valuePlaceholder: string;
  suggestions?: string[];
  emptyHint: string;
  onChange: (next: Record<string, string>) => void;
}) {
  const entries = Object.entries(value);
  const [draft, setDraft] = useState("");
  const unused = suggestions.filter((s) => !(s in value));

  const add = (raw: string) => {
    const key = raw.trim();
    if (!key || key in value) return;
    onChange({ ...value, [key]: "" });
    setDraft("");
  };

  const remove = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };

  return (
    <div className="space-y-3">
      {entries.length === 0 ? (
        <NothingYet>{emptyHint}</NothingYet>
      ) : (
        <ul className="space-y-2">
          {entries.map(([key, entry]) => (
            <li key={key} className="flex items-center gap-2 rounded-xl border px-3 py-2">
              <span className="w-24 shrink-0 truncate text-xs text-muted-foreground">{key}</span>
              <Input
                className="h-8 min-w-0 flex-1"
                placeholder={valuePlaceholder}
                value={entry}
                disabled={disabled}
                onChange={(e) => onChange({ ...value, [key]: e.target.value })}
              />
              <Button
                variant="ghost"
                size="icon"
                className="size-7 shrink-0"
                disabled={disabled}
                aria-label={`Remove ${key}`}
                onClick={() => remove(key)}
              >
                <X className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="h-8 w-44"
          placeholder={keyLabel}
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || !draft.trim()}
          onClick={() => add(draft)}
        >
          <Plus className="size-3.5" /> Add
        </Button>
        {unused.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={disabled}
            onClick={() => add(suggestion)}
            className="rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            + {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- tag list */

/** A list of plain strings. Competitors compile into the brain's positioning. */
export function TagListEditor({
  value,
  disabled,
  placeholder,
  emptyHint,
  onChange,
}: {
  value: string[];
  disabled?: boolean;
  placeholder: string;
  emptyHint: string;
  onChange: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const entry = draft.trim();
    // Case-insensitive: the brain sorts and dedupes on the raw string, so
    // "Acme" and "acme" would both survive and read as two rivals.
    if (!entry || value.some((v) => v.toLowerCase() === entry.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...value, entry]);
    setDraft("");
  };

  return (
    <div className="space-y-3">
      {value.length === 0 ? (
        <NothingYet>{emptyHint}</NothingYet>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {value.map((entry, index) => (
            <li
              key={entry}
              className="flex items-center gap-1.5 rounded-full border bg-secondary/40 py-1 pr-1 pl-3 text-sm"
            >
              <span className="truncate">{entry}</span>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Remove ${entry}`}
                className="grid size-5 place-items-center rounded-full text-muted-foreground hover:text-foreground"
                onClick={() => onChange(value.filter((_, i) => i !== index))}
              >
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="h-8 w-56"
          placeholder={placeholder}
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button size="sm" variant="outline" disabled={disabled || !draft.trim()} onClick={add}>
          <Plus className="size-3.5" /> Add
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------- products and services */

export function ProductsEditor({
  value,
  disabled,
  onChange,
}: {
  value: ProductService[];
  disabled?: boolean;
  onChange: (next: ProductService[]) => void;
}) {
  const patch = (index: number, row: Partial<ProductService>) =>
    onChange(value.map((entry, i) => (i === index ? { ...entry, ...row } : entry)));

  return (
    <div className="space-y-3">
      {value.length === 0 ? (
        <NothingYet>
          Nothing listed yet. Add what this brand actually sells — every generation reads it.
        </NothingYet>
      ) : (
        <ul className="space-y-3">
          {value.map((row, index) => (
            // The index is the key on purpose: the server strips every key it
            // does not recognise, so an id added client-side would not survive
            // a save and the list would remount on every refresh.
            <li key={index} className="space-y-2 rounded-xl border p-3">
              <div className="flex items-center gap-2">
                <Input
                  className="h-8 min-w-0 flex-1"
                  placeholder="Name — e.g. Single-origin subscription"
                  value={row.name}
                  disabled={disabled}
                  onChange={(e) => patch(index, { name: e.target.value })}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0"
                  disabled={disabled}
                  aria-label={`Remove ${row.name || "product"}`}
                  onClick={() => onChange(value.filter((_, i) => i !== index))}
                >
                  <X className="size-3.5" />
                </Button>
              </div>
              <Textarea
                rows={2}
                placeholder="What it is, who it is for, what makes it different."
                value={row.description}
                disabled={disabled}
                onChange={(e) => patch(index, { description: e.target.value })}
              />
            </li>
          ))}
        </ul>
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => onChange([...value, { name: "", description: "" }])}
      >
        <Plus className="size-3.5" /> Add product or service
      </Button>
      {value.some((row) => !row.name.trim()) ? (
        <p className="text-xs text-amber-600">
          A product without a name is refused by the server, so this list is not being saved yet.
        </p>
      ) : null}
    </div>
  );
}

// Keep this module component-only so React Fast Refresh can preserve state.

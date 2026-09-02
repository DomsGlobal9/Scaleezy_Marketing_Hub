import { Brain, FileImage, Link2, Loader2, Sparkles, Upload, X } from "lucide-react";
import { type ChangeEvent, type FormEvent, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export const INSPIRATION_UPLOAD_ACCEPT = ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp";
export const INSPIRATION_UPLOAD_MAX_BYTES = 15 * 1024 * 1024;
export const INSPIRATION_INSTRUCTION_MAX_LENGTH = 1000;

const SUPPORTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const DEFAULT_INSTRUCTION = "Create a similar poster";

type SourceMode = "upload" | "link";

export type CreateFromInspirationInput =
  | { source: "upload"; file: File; instruction: string }
  | { source: "link"; url: string; instruction: string };

interface CreateFromInspirationProps {
  brandId: string | null;
  awaitingApproval: boolean;
  error?: string | null;
  savedReference?: { title: string; instruction: string; retryAllowed: boolean } | null;
  onCancel: () => void;
  onSubmit: (input: CreateFromInspirationInput) => Promise<void>;
  onRetrySaved?: (instruction: string) => Promise<void>;
  onReplaceSaved?: () => void;
  onClearError?: () => void;
}

function validatePublicHttpsUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:") return "Use a public HTTPS link.";
    if (parsed.username || parsed.password)
      return "Links containing login details are not supported.";
    return null;
  } catch {
    return "Enter a complete public HTTPS link.";
  }
}

function validateImage(file: File): string | null {
  if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
    return "Choose a JPEG, PNG or WebP image.";
  }
  if (file.size > INSPIRATION_UPLOAD_MAX_BYTES) {
    return "The image must be 15 MB or smaller.";
  }
  return null;
}

/**
 * The one-step content entry point for an inspiration-led poster.
 *
 * Saving and generation stay outside this component so the Publishing route
 * can reuse its existing tenant-aware API, queue polling and draft preview.
 */
export function CreateFromInspiration({
  brandId,
  awaitingApproval,
  error,
  savedReference,
  onCancel,
  onSubmit,
  onRetrySaved,
  onReplaceSaved,
  onClearError,
}: CreateFromInspirationProps) {
  const [mode, setMode] = useState<SourceMode>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [instruction, setInstruction] = useState(
    savedReference?.instruction || DEFAULT_INSTRUCTION,
  );
  const [localError, setLocalError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const clearError = () => {
    setLocalError(null);
    onClearError?.();
  };

  const chooseMode = (next: SourceMode) => {
    setMode(next);
    clearError();
  };

  const chooseFile = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    event.target.value = "";
    clearError();
    if (!next) return;
    const validationError = validateImage(next);
    if (validationError) {
      setFile(null);
      setLocalError(validationError);
      return;
    }
    setFile(next);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    clearError();

    if (!brandId) {
      setLocalError("Select a client before creating content.");
      return;
    }
    if (awaitingApproval) {
      setLocalError("Generation unlocks once Scaleezy approves this client.");
      return;
    }

    const cleanInstruction = instruction.trim();
    if (!cleanInstruction) {
      setLocalError("Tell Scaleezy what to create.");
      return;
    }

    if (savedReference) {
      if (!savedReference.retryAllowed || !onRetrySaved) {
        setLocalError(
          "This poster may still be running. Check Review → Drafts before starting another.",
        );
        return;
      }
      setBusy(true);
      try {
        await onRetrySaved(cleanInstruction);
      } finally {
        setBusy(false);
      }
      return;
    }

    let input: CreateFromInspirationInput;
    if (mode === "upload") {
      if (!file) {
        setLocalError("Choose an inspiration image first.");
        return;
      }
      const validationError = validateImage(file);
      if (validationError) {
        setLocalError(validationError);
        return;
      }
      input = { source: "upload", file, instruction: cleanInstruction };
    } else {
      const cleanUrl = url.trim();
      const validationError = validatePublicHttpsUrl(cleanUrl);
      if (validationError) {
        setLocalError(validationError);
        return;
      }
      input = { source: "link", url: cleanUrl, instruction: cleanInstruction };
    }

    setBusy(true);
    try {
      await onSubmit(input);
    } finally {
      setBusy(false);
    }
  };

  const visibleError = localError || error;
  const canSubmit =
    !busy &&
    !!brandId &&
    !awaitingApproval &&
    instruction.trim().length > 0 &&
    (savedReference
      ? savedReference.retryAllowed && !!onRetrySaved
      : mode === "upload"
        ? !!file
        : url.trim().length > 0);

  return (
    <section className="surface-card overflow-hidden">
      <div className="border-b border-border bg-black px-5 py-6 text-white sm:px-8">
        <div className="flex items-start gap-4">
          <div className="grid size-12 shrink-0 place-items-center rounded-xl bg-primary text-black">
            <Sparkles className="size-6" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-[0.2em] text-primary uppercase">
              Create from inspiration
            </p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight">Make it yours</h2>
            <p className="mt-2 max-w-2xl text-sm text-white/70">
              Give Scaleezy one reference. It will read the creative direction, then create an
              original poster for this client instead of copying the source.
            </p>
          </div>
        </div>
      </div>

      <form className="space-y-6 p-5 sm:p-8" onSubmit={submit} noValidate>
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl border border-primary/35 bg-primary/8 px-4 py-3"
        >
          <Brain className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-foreground">
              Using this client&apos;s Brand Brain
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Brand voice, colours, knowledge, rules and learned preferences remain in control.
            </p>
          </div>
        </div>

        {savedReference ? (
          <div className="rounded-xl border border-primary/35 bg-primary/8 p-4">
            <div className="flex min-w-0 items-start gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary text-black">
                <FileImage className="size-5" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold tracking-wide text-primary uppercase">
                  Inspiration already saved
                </p>
                <p className="mt-1 truncate text-sm font-medium text-foreground">
                  {savedReference.title}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {savedReference.retryAllowed
                    ? "Retry uses this Brand Master reference. It will not upload or save a duplicate."
                    : "The previous request may still finish. Check Review → Drafts before starting another to avoid duplicate AI spend."}
                </p>
              </div>
              {onReplaceSaved ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    clearError();
                    onReplaceSaved();
                  }}
                >
                  Choose another
                </Button>
              ) : null}
            </div>
          </div>
        ) : (
          <>
            <fieldset>
              <legend className="text-sm font-semibold text-foreground">
                Choose one reference
              </legend>
              <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-secondary/60 p-1.5">
                <button
                  type="button"
                  aria-pressed={mode === "upload"}
                  onClick={() => chooseMode("upload")}
                  className={cn(
                    "flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    mode === "upload"
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Upload className="size-4" aria-hidden="true" /> Upload image
                </button>
                <button
                  type="button"
                  aria-pressed={mode === "link"}
                  onClick={() => chooseMode("link")}
                  className={cn(
                    "flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    mode === "link"
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Link2 className="size-4" aria-hidden="true" /> Paste page
                </button>
              </div>
            </fieldset>

            {mode === "upload" ? (
              <div className="space-y-2">
                <Label htmlFor="inspiration-file">Inspiration image</Label>
                <input
                  ref={fileInput}
                  id="inspiration-file"
                  type="file"
                  accept={INSPIRATION_UPLOAD_ACCEPT}
                  className="sr-only"
                  onChange={chooseFile}
                />
                {file ? (
                  <div className="flex min-w-0 items-center gap-3 rounded-xl border border-border bg-secondary/25 p-3">
                    <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/12 text-primary">
                      <FileImage className="size-5" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {(file.size / (1024 * 1024)).toFixed(1)} MB
                      </p>
                    </div>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      aria-label="Remove inspiration image"
                      onClick={() => {
                        setFile(null);
                        clearError();
                      }}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    className="h-auto min-h-28 w-full flex-col gap-2 border-dashed py-5"
                    onClick={() => fileInput.current?.click()}
                  >
                    <Upload className="size-5 text-primary" aria-hidden="true" />
                    <span>Choose an image</span>
                    <span className="text-xs font-normal text-muted-foreground">
                      JPEG, PNG or WebP · up to 15 MB
                    </span>
                  </Button>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                <Label htmlFor="inspiration-url">Public page or article</Label>
                <Input
                  id="inspiration-url"
                  type="url"
                  inputMode="url"
                  autoComplete="url"
                  placeholder="https://example.com/campaign-page"
                  value={url}
                  onChange={(event) => {
                    setUrl(event.target.value);
                    clearError();
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  Scaleezy reads public page text for copy and tone. For visual style, upload a
                  screenshot or image. Private or login-walled content cannot be read.
                </p>
              </div>
            )}
          </>
        )}

        <div className="space-y-2">
          <div className="flex items-end justify-between gap-3">
            <Label htmlFor="inspiration-instruction">What should Scaleezy create?</Label>
            <span className="text-xs tabular-nums text-muted-foreground" aria-hidden="true">
              {instruction.length}/{INSPIRATION_INSTRUCTION_MAX_LENGTH}
            </span>
          </div>
          <Textarea
            id="inspiration-instruction"
            rows={3}
            maxLength={INSPIRATION_INSTRUCTION_MAX_LENGTH}
            value={instruction}
            onChange={(event) => {
              setInstruction(event.target.value);
              clearError();
            }}
          />
          <p className="text-xs text-muted-foreground">
            Scaleezy uses the reference for direction only. Your Brand Brain governs the final
            result.
          </p>
        </div>

        {visibleError ? (
          <div
            role="alert"
            className="rounded-xl border border-destructive/40 bg-destructive/8 px-4 py-3 text-sm text-destructive"
          >
            {visibleError}
          </div>
        ) : null}

        {awaitingApproval ? (
          <p className="rounded-xl border border-gold/40 bg-gold/10 px-4 py-3 text-sm text-foreground">
            Generation unlocks once Scaleezy approves this client.
          </p>
        ) : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
          <Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" className="sm:ml-auto" disabled={!canSubmit}>
            {busy ? (
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles className="size-4" aria-hidden="true" />
            )}
            {busy
              ? savedReference
                ? "Retrying poster…"
                : "Saving inspiration…"
              : savedReference && !savedReference.retryAllowed
                ? "Check Drafts"
                : "Create similar poster"}
          </Button>
        </div>
      </form>
    </section>
  );
}

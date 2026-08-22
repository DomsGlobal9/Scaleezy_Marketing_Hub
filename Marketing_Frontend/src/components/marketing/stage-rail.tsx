/**
 * The stepper. One implementation, two callers.
 *
 * Teach Scaleezy and the guided onboarding wizard show the same journey at
 * different resolutions, and they used to be the only stepper in the repo —
 * duplicated, they would drift the moment one of them gained a step. Neither
 * owns progress: each caller passes what it derived from persisted data, so
 * this component decides nothing and stores nothing.
 */
import { ArrowRight, Check } from "lucide-react";

export interface StageRailStep {
  key: string;
  label: string;
  done: boolean;
  active: boolean;
  skipped?: boolean;
}

export function StageRail({
  steps,
  onSelect,
}: {
  steps: StageRailStep[];
  /** Given, every step becomes navigable — the wizard lets you go back. */
  onSelect?: (key: string) => void;
}) {
  return (
    <ol className="flex flex-wrap items-center gap-2">
      {steps.map((step, index) => {
        const className = `flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
          step.active
            ? "border-foreground bg-foreground text-background"
            : step.done
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700"
              : "border-border text-muted-foreground"
        }`;
        const body = (
          <>
            {step.done ? <Check className="size-3" /> : null}
            {step.label}
            {step.skipped && !step.done ? <span className="opacity-70">(skipped)</span> : null}
          </>
        );

        return (
          <li key={step.key} className="flex items-center gap-2">
            {onSelect ? (
              <button
                type="button"
                aria-current={step.active ? "step" : undefined}
                className={`${className} transition-colors hover:border-foreground/40`}
                onClick={() => onSelect(step.key)}
              >
                {body}
              </button>
            ) : (
              <span className={className}>{body}</span>
            )}
            {index < steps.length - 1 ? (
              <ArrowRight className="size-3 text-muted-foreground/50" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

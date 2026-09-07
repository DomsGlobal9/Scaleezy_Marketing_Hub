/**
 * Scroll-reveal for the marketing pages.
 *
 * The editorial sites this design follows animate almost every block into
 * view. Done naively that is a liability: hiding content with CSS and
 * revealing it with JavaScript means a crawler, a reader with JavaScript off,
 * or anyone whose observer never fires gets a blank page. Three rules keep it
 * safe:
 *
 *  1. The server renders everything visible. The hidden state is applied on
 *     the client only, so the HTML a crawler receives is complete.
 *  2. It is applied in useLayoutEffect, which runs before the browser paints,
 *     so there is no flash of content appearing and then hiding again.
 *  3. Anything already on screen at mount is never hidden at all, and anyone
 *     who asks for reduced motion is opted out entirely.
 *
 * The net effect is that the animation is decoration layered onto a page that
 * is already correct without it.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/** useLayoutEffect warns when it runs during SSR; on the server, do nothing. */
const useIsomorphicLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

export interface RevealProps {
  children: ReactNode;
  /** Milliseconds to stagger this element behind its siblings. */
  delay?: number;
  /** Direction the element travels from. */
  from?: "below" | "left" | "right" | "none";
  // Explicitly `| undefined`: the project sets exactOptionalPropertyTypes, so
  // an optional prop rejects a possibly-undefined value unless it says so, and
  // callers forward their own optional className.
  className?: string | undefined;
  as?: "div" | "section" | "li" | "article" | "figure";
}

export function Reveal({
  children,
  delay = 0,
  from = "below",
  className,
  as: Tag = "div",
}: RevealProps) {
  const ref = useRef<HTMLElement | null>(null);
  // Starts true so the server, and any client that cannot observe, renders
  // the finished state.
  const [shown, setShown] = useState(true);

  useIsomorphicLayoutEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion() || typeof IntersectionObserver === "undefined") return;

    // Already on screen when the page loads: leave it alone rather than
    // hiding it and animating it back in, which reads as a glitch.
    const rect = node.getBoundingClientRect();
    if (rect.top < window.innerHeight * 0.9) return;

    setShown(false);
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node || shown) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setShown(true);
            observer.disconnect();
          }
        }
      },
      // Fires a little before the element's top edge arrives, so the movement
      // finishes about when the reader's eye reaches it.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [shown]);

  const hiddenOffset =
    from === "left"
      ? "-translate-x-6"
      : from === "right"
        ? "translate-x-6"
        : from === "none"
          ? ""
          : "translate-y-8";

  return (
    <Tag
      // The ref types differ per tag; the element is only measured and observed.
      ref={ref as never}
      className={cn(
        "transition-[opacity,transform] duration-[900ms] ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none",
        shown ? "translate-x-0 translate-y-0 opacity-100" : cn("opacity-0", hiddenOffset),
        className,
      )}
      // Applied whenever there is a stagger, in both states. Clearing it on the
      // way to `shown` would remove the delay at the exact moment the
      // transition is meant to honour it, and every item in a row would move
      // together.
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </Tag>
  );
}

/**
 * A word that draws its own underline as it comes into view.
 *
 * The reference design marks one word per headline with a hand-drawn stroke.
 * It is drawn as a path with a dash offset animated to zero, so the line
 * appears to be written rather than faded in.
 */
export function Underlined({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [drawn, setDrawn] = useState(true);

  useIsomorphicLayoutEffect(() => {
    const node = ref.current;
    if (!node || prefersReducedMotion() || typeof IntersectionObserver === "undefined") return;
    if (node.getBoundingClientRect().top < window.innerHeight * 0.9) return;
    setDrawn(false);
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node || drawn) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setDrawn(true);
          observer.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [drawn]);

  return (
    <span ref={ref} className={cn("relative inline-block whitespace-nowrap", className)}>
      {children}
      <svg
        aria-hidden
        viewBox="0 0 200 14"
        preserveAspectRatio="none"
        className="absolute -bottom-[0.14em] left-0 h-[0.16em] w-full overflow-visible"
        fill="none"
      >
        <path
          d="M2 9C40 4 92 2 140 5c22 1.4 40 3.6 58 6"
          stroke="var(--color-primary)"
          strokeWidth="7"
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={drawn ? 0 : 1}
          className="transition-[stroke-dashoffset] duration-[900ms] ease-out motion-reduce:transition-none"
        />
      </svg>
    </span>
  );
}

/** A ring drawn around a word, for the full-bleed statement bands. */
export function Circled({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("relative inline-block whitespace-nowrap px-[0.18em]", className)}>
      {children}
      <svg
        aria-hidden
        viewBox="0 0 240 90"
        preserveAspectRatio="none"
        className="pointer-events-none absolute -inset-x-[0.12em] -inset-y-[0.22em] h-[calc(100%+0.44em)] w-[calc(100%+0.24em)]"
        fill="none"
      >
        <path
          d="M120 6C61 6 12 22 12 45c0 23 49 39 108 39s108-16 108-39C228 24 182 8 128 6"
          stroke="var(--color-primary)"
          strokeWidth="4"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

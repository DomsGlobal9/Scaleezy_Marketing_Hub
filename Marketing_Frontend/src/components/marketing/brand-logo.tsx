import { cn } from "@/lib/utils";

/**
 * The Scaleezy wordmark.
 *
 * Two files, because the supplied asset is lime and *white* on transparency and
 * therefore disappears on a light surface. `scaleezy-wordmark-dark.webp` is the
 * same artwork with only the white half recoloured to the brand ink; the lime
 * is identical in both, so the mark reads the same either way.
 *
 * `tone` names the surface the mark sits on, not the colour of the mark:
 * tone="dark" is the file for dark headers, tone="light" for white ones.
 */
export function ScaleezyLogo({
  className,
  priority = false,
  tone = "dark",
}: {
  className?: string;
  priority?: boolean;
  tone?: "dark" | "light";
}) {
  return (
    <img
      src={
        tone === "light" ? "/brand/scaleezy-wordmark-dark.webp" : "/brand/scaleezy-wordmark.webp"
      }
      width={512}
      height={143}
      alt="Scaleezy"
      className={cn("h-auto w-[9.75rem] object-contain", className)}
      loading={priority ? "eager" : "lazy"}
      fetchPriority={priority ? "high" : "auto"}
      decoding="async"
    />
  );
}

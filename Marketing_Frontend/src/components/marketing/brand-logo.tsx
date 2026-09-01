import { cn } from "@/lib/utils";

export function ScaleezyLogo({
  className,
  priority = false,
}: {
  className?: string;
  priority?: boolean;
}) {
  return (
    <img
      src="/brand/scaleezy-wordmark.webp"
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

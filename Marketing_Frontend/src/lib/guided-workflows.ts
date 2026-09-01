import type { BrandDto } from "@/lib/brand-settings";

export interface GuidedPolicyText {
  name: string;
  objective: string;
  campaign_brief: string;
}

export interface GuidedResearchText {
  query: string;
  objectives: string;
}

const clean = (value: unknown) =>
  typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";

const clip = (value: string, limit: number) =>
  value.length <= limit ? value : `${value.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;

const namesFrom = (value: unknown) => {
  if (!Array.isArray(value)) return [];
  return value
    .flatMap((entry) => {
      if (typeof entry === "string") return clean(entry) ? [clean(entry)] : [];
      if (!entry || typeof entry !== "object") return [];
      const name = clean((entry as { name?: unknown }).name);
      return name ? [name] : [];
    })
    .slice(0, 3);
};

const joinNatural = (items: string[]) => {
  if (items.length < 2) return items[0] ?? "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items.at(-1)}`;
};

const POLICY_NAME_LIMIT = 120;

export function nextGuidedPolicyName(base: string, existingNames: string[]): string {
  const root = clean(base) || "Guided growth";
  const taken = new Set(existingNames.map((name) => clean(name).toLowerCase()).filter(Boolean));
  const first = clip(root, POLICY_NAME_LIMIT);
  if (!taken.has(first.toLowerCase())) return first;

  let index = 2;
  while (index < 10_000) {
    const suffix = ` ${index}`;
    const candidate = `${root.slice(0, POLICY_NAME_LIMIT - suffix.length).trimEnd()}${suffix}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
    index += 1;
  }
  return first;
}

export function buildGuidedPolicyText(brand: BrandDto): GuidedPolicyText {
  const brandName = clean(brand.name) || "This brand";
  const industry = clean(brand.industry);
  const audience = clean(brand.audience) || "the right customers";
  const products = namesFrom(brand.products_services);
  const offering = joinNatural(products) || "the brand's offer";
  const tone = clean(brand.brand_tone);
  const tagline = clean(brand.tagline);
  const description = clip(clean(brand.description), 280);
  const cta = clean(brand.cta_keyword);

  const direction = [
    `Create one immediately useful content idea for ${audience}${industry ? ` in ${industry}` : ""}.`,
    description ? `Ground it in this business context: ${description}.` : "",
    `Connect the audience insight naturally to ${offering}.`,
    tone ? `Write in a ${tone} brand voice.` : "Keep the voice clear, specific, and human.",
    tagline ? `Use “${tagline}” only when it strengthens the message.` : "",
    cta ? `End with a clear invitation built around “${cta}”.` : "End with one clear next step.",
    "Use Brand Master facts and routed context, create an original concept, and never copy an inspiration reference.",
  ]
    .filter(Boolean)
    .join(" ");

  return {
    name: nextGuidedPolicyName(`${brandName} guided growth`, []),
    objective: `Build awareness and qualified engagement for ${brandName} by turning ${offering} into useful, on-brand social content for ${audience}.`,
    campaign_brief: direction,
  };
}

export function buildGuidedResearchText(brand: BrandDto): GuidedResearchText {
  const brandName = clean(brand.name) || "this brand";
  const industry = clean(brand.industry);
  const audience = clip(clean(brand.audience), 180) || "the right customers";
  const products = namesFrom(brand.products_services);
  const productContext = products.length ? `, especially for ${joinNatural(products)}` : "";

  return {
    query: clip(
      `Find current public creative references and campaign ideas for ${brandName}${industry ? ` in ${industry}` : ""}, relevant to ${audience}${productContext}. Include posters, social posts, carousels, short-form video concepts, hooks, offers, and visual systems. Bring in useful ideas from adjacent or unexpected industries, with cited sources for inspiration rather than copying.`,
      1000,
    ),
    objectives: "campaign concepts, hooks and copy angles, visual direction, format ideas",
  };
}

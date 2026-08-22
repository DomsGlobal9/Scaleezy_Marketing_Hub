/**
 * Products & Audience — what this brand sells and who it sells to.
 *
 * Its own surface rather than more of Brand basics: these are first-party
 * business claims, and the backend treats them that way. `description` becomes
 * brain.identity.description and `audience` becomes brain.audiences.stated,
 * sitting beside the pains and objections that were derived from evidence
 * rather than replacing them. Everything on this page moves brain_version the
 * moment it saves.
 */
import { useEffect, useRef, useState } from "react";

import { Textarea } from "@/components/ui/textarea";
import { BrandError, SavingHint } from "@/components/marketing/brand-basics";
import { Field, ProductsEditor } from "@/components/marketing/brand-field-editors";
import { SectionTitle } from "@/components/marketing/primitives";
import { useBrandSettings, type BrandEditor, type ProductService } from "@/lib/brand-settings";

export function ProductsAudienceSection({ editor }: { editor: BrandEditor }) {
  const { settings, update, loading, saving } = editor;

  /**
   * The products list is edited locally and only sent once every row has a
   * name. The serializer rejects a nameless row outright, so writing through
   * on each keystroke would fire a 400 for every character typed into a row
   * the user had only just added.
   */
  const [products, setProducts] = useState<ProductService[]>(settings.productsServices);
  const seeded = useRef(false);
  useEffect(() => {
    if (loading || seeded.current) return;
    seeded.current = true;
    setProducts(settings.productsServices);
  }, [loading, settings.productsServices]);

  const onProducts = (next: ProductService[]) => {
    setProducts(next);
    if (next.every((row) => row.name.trim())) update({ productsServices: next });
  };

  return (
    <div className="space-y-8">
      <section>
        <SectionTitle
          title="What this brand is"
          description="A plain description in your own words. Every generation reads it, whatever the task."
          action={<SavingHint saving={saving} />}
        />
        <div className="mt-4">
          <Textarea
            rows={4}
            placeholder="A small-batch roastery selling single-origin coffee to people who care where it came from."
            value={settings.description}
            disabled={loading}
            onChange={(e) => update({ description: e.target.value })}
          />
        </div>
      </section>

      <section>
        <SectionTitle
          title="Who it is for"
          description="Stated audience. Kept beside the pains and objections Scaleezy infers from your knowledge — it never overwrites them."
        />
        <div className="mt-4">
          <Textarea
            rows={4}
            placeholder="Home brewers in metro India, 25–40, who already own a grinder and read the roast date."
            value={settings.audience}
            disabled={loading}
            onChange={(e) => update({ audience: e.target.value })}
          />
        </div>
      </section>

      <section>
        <SectionTitle
          title="Products & services"
          description="What is actually for sale. Named things generation can be specific about instead of writing around."
        />
        <div className="mt-4">
          <Field label="Catalogue">
            <ProductsEditor value={products} disabled={loading} onChange={onProducts} />
          </Field>
        </div>
      </section>
    </div>
  );
}

export function ProductsAudiencePanel({
  onSaved,
  brandId,
}: {
  onSaved?: () => void;
  brandId?: string | null;
}) {
  const editor = useBrandSettings({
    ...(onSaved ? { onSaved } : {}),
    ...(brandId !== undefined ? { brandId } : {}),
  });

  return (
    <div className="space-y-8">
      <BrandError error={editor.error} />
      <ProductsAudienceSection editor={editor} />
    </div>
  );
}

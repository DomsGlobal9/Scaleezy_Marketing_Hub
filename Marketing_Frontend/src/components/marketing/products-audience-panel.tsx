/**
 * Brand profile — the whole first-party brand record on one form: identity,
 * voice, logo, visual identity, market context, poster defaults, then what
 * the brand sells and who it sells to.
 *
 * Products & Audience used to be its own tab, but it never had an endpoint of
 * its own — every field here is the same Brand PATCH through the same
 * `useBrandSettings` instance, so it is one form with one save queue and one
 * commit point. `description` becomes brain.identity.description and
 * `audience` becomes brain.audiences.stated, sitting beside the pains and
 * objections that were derived from evidence rather than replacing them.
 * Everything on this page moves brain_version the moment it saves.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Textarea } from "@/components/ui/textarea";
import {
  BrandError,
  BrandSaveControl,
  ClientBasicsSection,
  LogoSection,
  MarketSection,
  PosterDefaultsSection,
  SavingHint,
  VisualIdentitySection,
  VoiceSection,
} from "@/components/marketing/brand-basics";
import { Field, ProductsEditor } from "@/components/marketing/brand-field-editors";
import { SectionTitle } from "@/components/marketing/primitives";
import type { BrandEditor, ProductService } from "@/lib/brand-settings";

const productsEqual = (left: ProductService[], right: ProductService[]) =>
  left.length === right.length &&
  left.every(
    (row, index) =>
      row.name === right[index]?.name && row.description === right[index]?.description,
  );

export function ProductsAudienceSection({
  editor,
  onDraftStateChange,
}: {
  editor: BrandEditor;
  onDraftStateChange?: (dirty: boolean, blockedReason: string | null) => void;
}) {
  const { settings, update, loading, saving, saveState } = editor;

  /**
   * The products list is edited locally and only sent once every row has a
   * name. The serializer rejects a nameless row outright, so writing through
   * on each keystroke would fire a 400 for every character typed into a row
   * the user had only just added.
   */
  const [products, setProducts] = useState<ProductService[]>(settings.productsServices);
  const seeded = useRef(false);
  useEffect(() => {
    if (loading) return;
    if (!seeded.current) {
      seeded.current = true;
      setProducts(settings.productsServices);
      return;
    }
    // Read back the canonical, trimmed server value after a successful save,
    // but never erase an incomplete local row the API correctly refuses.
    if (saveState === "saved") {
      setProducts((current) =>
        current.some((row) => !row.name.trim()) ? current : settings.productsServices,
      );
    }
  }, [loading, saveState, settings.productsServices]);

  const hasUnnamedProduct = products.some((row) => !row.name.trim());
  const hasLocalDraft = !productsEqual(products, settings.productsServices);
  const draftBlock = hasUnnamedProduct
    ? "Give every product or service a name before this catalogue can be saved."
    : null;

  useEffect(() => {
    onDraftStateChange?.(hasLocalDraft, draftBlock);
  }, [draftBlock, hasLocalDraft, onDraftStateChange]);

  useEffect(() => {
    if (!hasLocalDraft) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [hasLocalDraft]);

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

export function BrandProfilePanel({ editor }: { editor: BrandEditor }) {
  const [draftState, setDraftState] = useState({
    dirty: false,
    blockedReason: null as string | null,
  });
  const onDraftStateChange = useCallback((dirty: boolean, blockedReason: string | null) => {
    setDraftState((current) =>
      current.dirty === dirty && current.blockedReason === blockedReason
        ? current
        : { dirty, blockedReason },
    );
  }, []);

  return (
    <div className="space-y-8">
      <BrandSaveControl
        editor={editor}
        extraDirty={draftState.dirty}
        blockedReason={draftState.blockedReason}
      />
      <BrandError error={editor.error} />
      <ClientBasicsSection editor={editor} />
      <VoiceSection editor={editor} />
      <LogoSection editor={editor} />
      <VisualIdentitySection editor={editor} />
      <MarketSection editor={editor} />
      <PosterDefaultsSection editor={editor} />
      <ProductsAudienceSection editor={editor} onDraftStateChange={onDraftStateChange} />
    </div>
  );
}

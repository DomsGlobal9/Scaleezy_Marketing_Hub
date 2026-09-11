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
 * Creative identity changes update the compiled brain; administrative contact
 * fields are saved on the brand without becoming generation instructions.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Textarea } from "@/components/ui/textarea";
import {
  AdminDetailsSection,
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
          title="What you sell, and to whom"
          description="In your own words. Every post starts from this."
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
          title="Who buys from you"
          description="Optional, but it sharpens every caption."
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
          title="What is on sale"
          description="Name the products or services so posts can be specific."
        />
        <div className="mt-4">
          <Field label="Products and services">
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
      <ProductsAudienceSection editor={editor} onDraftStateChange={onDraftStateChange} />
      <LogoSection editor={editor} />
      <VisualIdentitySection editor={editor} />
      <VoiceSection editor={editor} />
      {/* Records and fine-tuning. Nothing here is needed for a good first
          poster, so it stays folded until someone wants it. */}
      <details className="rounded-xl border border-border p-4">
        <summary className="cursor-pointer list-none text-sm font-semibold text-foreground">
          More details
          <span className="ml-2 font-normal text-muted-foreground">
            — business records, competitors, links, poster extras
          </span>
        </summary>
        <div className="mt-6 space-y-8">
          <AdminDetailsSection editor={editor} />
          <MarketSection editor={editor} />
          <PosterDefaultsSection editor={editor} />
        </div>
      </details>
    </div>
  );
}

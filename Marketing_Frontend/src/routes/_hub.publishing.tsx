import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Clock,
  ExternalLink,
  Loader2,
  RotateCcw,
  Send,
  Sparkles,
  Upload,
  FileImage,
  RefreshCw,
  Edit3,
  ZoomIn,
  X,
  Wand2,
  CheckCircle,
  ArrowLeft,
  Image as ImageIcon,
  Images,
  Plus,
  Trash2,
  UserRound,
  Video,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  PageHeader,
  PlatformIcon,
  SectionTitle,
  StatusBadge,
} from "@/components/marketing/primitives";
import { CreativeCommand, type CreativeSelection } from "@/components/marketing/creative-command";
import {
  CreateFromInspiration,
  type CreateFromInspirationInput,
} from "@/components/marketing/create-from-inspiration";
import { PosterStudio, useLayoutCatalogue } from "@/components/marketing/poster-studio";
import { cn } from "@/lib/utils";
import { useBrandSettings } from "@/lib/brand-settings";
import {
  asList,
  createInspiration,
  fetchBrandAmbassadors,
  fetchBrandTemplates,
  fetchCurrentBrand,
  type Inspiration,
  type InspirationInput,
  uploadBrandAmbassador,
  uploadInspiration,
} from "@/lib/brand-master";
import { api, apiFetch, apiPost, ApiError } from "@/lib/api";
import { readSelectedWorkspaceId } from "@/lib/workspace";
import {
  canCreateGeneration,
  canDiscardRejectedDelivery,
  generationDecision,
  hasSavedGenerationImage,
} from "@/lib/generation-state";

export const Route = createFileRoute("/_hub/publishing")({
  head: () => ({
    meta: [
      { title: "Create Studio — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "Create brand-aware posters, carousels and videos, then review and publish them from one place.",
      },
      { property: "og:title", content: "Create Studio — Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content: "Independent publishing jobs per platform with retry for failed channels only.",
      },
    ],
  }),
  component: PublishingPage,
});

type WorkflowStep =
  "inspiration_form" | "ai_form" | "ai_generating" | "manual_upload" | "preview" | "publish_setup";

/** What the AI is asked to produce. Drives the extra fields on the brief. */
type ContentType = "poster" | "video" | "carousel";
type CreativeMode = "AI_ORIGINAL" | "BRAND_TEMPLATE" | "REFERENCE";
const MAX_CREATIVE_BRIEF_CHARS = 1000;

/** One carousel slide. `description` is the brief for that specific position. */
interface CarouselSlide {
  id: string;
  description: string;
  previewUrl?: string | undefined;
}

interface DraftAsset {
  id?: string | undefined;
  generationId?: string | undefined;
  mediaWarning?: string | undefined;
  /** ContentItem row the backend persisted for this generation. */
  contentItemId?: string | undefined;
  name: string;
  type: string;
  dimensions: string;
  created: string;
  source: "ai" | "upload";
  contentType: ContentType;
  campaign?: string | undefined;
  tone?: string | undefined;
  postTitle: string;
  postDescription: string;
  postHashtags: string;
  previewUrl?: string | undefined;
  /** Honest partial state when provider output survived but a chosen template did not render. */
  compositionWarning?: string | undefined;
  /** Populated for carousels — one entry per slide, in order. */
  slides?: CarouselSlide[];
}

interface ContentItemDto {
  id: string;
  asset: string | null;
  headline: string;
  caption: string;
  hashtags: string;
  preview_url: string;
  content_format: "POSTER" | "CAROUSEL" | "VIDEO";
  status: string;
  ai_provider: string;
  slides?: Array<{ position?: number; description?: string; preview_url?: string }>;
  layout_plugin?: string;
}

interface PublishingAccount {
  id: string;
  platform: string;
  status: string;
  publishing_enabled?: boolean;
  publishingEnabled?: boolean;
  account_name?: string;
  username?: string;
}

interface PublishingJobItemDto {
  id: string;
  social_connection: PublishingAccount;
  queued_at: string;
  external_post_url?: string;
  external_post_id?: string;
  status: string;
  error_message?: string;
}

interface PublishingJobDto {
  items?: PublishingJobItemDto[];
  content_headline?: string;
  content_preview_url?: string;
}

interface PublishingHistoryRow {
  id: string;
  content: string;
  previewUrl?: string | undefined;
  platform: string;
  account: string;
  date: string;
  url?: string | undefined;
  status: string;
  postId?: string | undefined;
  error?: string | undefined;
}

/** Jobs fetched per history page; each job adds one table row per channel. */
const HISTORY_PAGE_SIZE = 20;

function toHistoryRows(jobs: PublishingJobDto[]): PublishingHistoryRow[] {
  const rows: PublishingHistoryRow[] = [];
  jobs.forEach((job) => {
    (job.items ?? []).forEach((item) => {
      rows.push({
        id: item.id,
        // The post's own headline. Every row used to read the same
        // hardcoded string, so the table could not tell one post from
        // another.
        content: job.content_headline?.trim() || "Untitled post",
        previewUrl: job.content_preview_url || undefined,
        platform: item.social_connection.platform,
        account:
          item.social_connection.account_name ||
          item.social_connection.username ||
          "Connected account",
        date: new Date(item.queued_at).toLocaleString(),
        // The platform permalink, so "View" opens the real post rather
        // than being a button that does nothing.
        url: item.external_post_url,
        status: item.status.charAt(0).toUpperCase() + item.status.slice(1).toLowerCase(),
        postId: item.external_post_id,
        error: item.error_message,
      });
    });
  });
  return rows;
}

/** True when the paginated envelope says another page exists. */
function hasNextPage(data: unknown): boolean {
  return (
    !Array.isArray(data) &&
    !!data &&
    typeof data === "object" &&
    (data as { next?: unknown }).next != null
  );
}

const CONTENT_TYPES: {
  id: ContentType;
  label: string;
  hint: string;
  icon: typeof ImageIcon;
}[] = [
  {
    id: "poster",
    label: "Poster",
    hint: "A single still image",
    icon: ImageIcon,
  },
  {
    id: "video",
    label: "Video",
    hint: "Generated by your routed video AI",
    icon: Video,
  },
  {
    id: "carousel",
    label: "Carousel",
    hint: "Multiple ordered slides",
    icon: Images,
  },
];

const CREATIVE_SOURCES: {
  id: CreativeMode;
  label: string;
  hint: string;
  icon: typeof ImageIcon;
}[] = [
  {
    id: "AI_ORIGINAL",
    label: "AI original",
    hint: "Scaleezy creates a fresh direction from your brief and Brand Brain.",
    icon: Sparkles,
  },
  {
    id: "BRAND_TEMPLATE",
    label: "Your templates",
    hint: "Match one of the poster templates you uploaded in Brand Master.",
    icon: Images,
  },
  {
    id: "REFERENCE",
    label: "Use inspiration",
    hint: "Upload your own or choose any saved or platform reference.",
    icon: Wand2,
  },
];

/** Where the poster will run — drives the generated aspect ratio server-side
 * and the copy's platform manners. Every other size still exports from the
 * result. */
const POSTER_PLATFORMS: { id: string; label: string; hint: string }[] = [
  { id: "instagram_post", label: "Instagram post", hint: "4:5" },
  { id: "instagram_story", label: "Story / Reel", hint: "9:16" },
  { id: "facebook", label: "Facebook", hint: "4:5" },
  { id: "linkedin", label: "LinkedIn", hint: "16:9" },
  { id: "x", label: "X", hint: "16:9" },
  { id: "print", label: "Print", hint: "A4" },
];

/** Quality tiers. Ultra bills 2 generation units — the founder's pricing. */
const QUALITY_TIERS: { id: string; label: string; hint: string }[] = [
  { id: "1K", label: "Standard", hint: "fastest" },
  { id: "2K", label: "High", hint: "sharp for social" },
  { id: "4K", label: "Ultra", hint: "print-grade · 2 units" },
];

/** Per-brand memory for the quick choices, so the second visit is brief-only. */
const studioDefaultsKey = (brandId: string) => `scaleezy.studio.${brandId}`;

const VIDEO_DURATIONS = ["10 seconds", "15 seconds", "30 seconds", "60 seconds"];
const VIDEO_ASPECTS = ["9:16 (Reels / Shorts)", "1:1 (Feed)", "16:9 (YouTube)"];
const VIDEO_STYLES = [
  "Product showcase",
  "Lifestyle / model walkthrough",
  "Offer announcement",
  "Behind the scenes",
  "Customer testimonial",
];

/** Guidance shown per slide position so the user knows what belongs where. */
const SLIDE_PLACEHOLDERS = [
  "Hook — the headline that stops the scroll (e.g. hero shot with the offer)",
  "The product — a clear look at what you are selling",
  "Detail — fabric, fit, craftsmanship or a close-up",
  "Social proof — a review, rating or customer photo",
  "Call to action — where and how to buy",
];

const slidePlaceholder = (index: number) =>
  SLIDE_PLACEHOLDERS[index] ?? `Slide ${index + 1} — describe what should appear here`;

const newSlide = (): CarouselSlide => ({
  id: `slide-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
  description: "",
});

/** Which flow the shared "AI is working" step is showing, so its copy can be true. */
type WorkingKind = "generate" | "captions" | "video";

interface InspirationGenerationOptions {
  inspirationId: string;
  inspirationTitle: string;
  instruction: string;
}

class InspirationGenerationFlowError extends Error {
  queued: boolean;
  retryAllowed: boolean;

  constructor(message: string, queued: boolean, retryAllowed: boolean) {
    super(message);
    this.name = "InspirationGenerationFlowError";
    this.queued = queued;
    this.retryAllowed = retryAllowed;
  }
}

class GenerationRequestFailedError extends Error {
  constructor(
    message: string,
    readonly retryAllowed: boolean,
  ) {
    super(message);
    this.name = "GenerationRequestFailedError";
  }
}

/**
 * Whether the backend would actually publish to this account.
 *
 * The publisher skips any connection with publishing_enabled off
 * (apps/publishing/views.py) and cannot post to an expired token, so ticking
 * such a row bought the user a "job created" toast and no post. Both the
 * checkbox and the pruning effect read this, so they can never disagree.
 */
const canPublishTo = (acc: PublishingAccount, isVideoAsset: boolean): boolean => {
  const status = String(acc.status ?? "").toUpperCase();
  const enabled = (acc.publishing_enabled ?? acc.publishingEnabled) !== false;
  const formatMismatch = acc.platform === "YOUTUBE" && !isVideoAsset;
  return status === "CONNECTED" && enabled && !formatMismatch;
};

/**
 * The generated-poster preview and its full-size lightbox, with the open
 * state kept here on purpose. It used to live at the top of the studio
 * component beside ~40 other hooks, so one click re-rendered the entire
 * studio — brief, pickers, template grids, slides, history — before the
 * dialog could paint (a 208ms INP block measured in production). Owning
 * the state means a click re-renders only this subtree.
 */
function PosterPreviewLightbox({ previewUrl }: { previewUrl: string }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <img
        src={previewUrl}
        alt="Generated Poster"
        loading="lazy"
        decoding="async"
        onClick={() => setOpen(true)}
        className="absolute inset-0 h-full w-full cursor-pointer object-cover transition-transform duration-500 group-hover:scale-105"
      />
      <div className="absolute inset-0 bg-black/40 opacity-0 transition-opacity duration-300 group-hover:opacity-100 flex items-center justify-center pointer-events-none">
        <div className="flex items-center gap-2 text-white bg-black/50 px-4 py-2 rounded-full backdrop-blur-md">
          <ZoomIn className="size-4" />
          <span className="text-sm font-medium">View Full Size</span>
        </div>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[90vw] md:max-w-3xl lg:max-w-4xl p-1 bg-transparent border-none shadow-none">
          <DialogTitle className="sr-only">Full Size Poster Preview</DialogTitle>
          <img
            src={previewUrl}
            alt="Full size poster"
            decoding="async"
            className="w-full h-auto max-h-[90vh] object-contain rounded-lg"
          />
        </DialogContent>
      </Dialog>
    </>
  );
}

function PublishingPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<WorkflowStep>("ai_form");
  const [asset, setAsset] = useState<DraftAsset | null>(null);
  const [contentSaving, setContentSaving] = useState(false);
  const [contentLocked, setContentLocked] = useState(false);
  // A pending client may do everything here except spend money. Knowing that
  // BEFORE the seven-field brief is filled in is the difference between a
  // disabled button with a reason and a red toast after the work.
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const [referenceImageBase64, setReferenceImageBase64] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [uploadIntention, setUploadIntention] = useState<"reference" | "final" | null>(null);
  const [isGeneratingCaptions, setIsGeneratingCaptions] = useState(false);
  // Three different flows share the "AI is working" step; without this the
  // panel told a video uploader we were analysing their image.
  const [workingKind, setWorkingKind] = useState<WorkingKind>("generate");
  const [productionProgress, setProductionProgress] = useState("");
  // Lets the user stop waiting on a queued generation, which otherwise holds
  // the screen for the full ten-minute polling ceiling.
  const generationAbort = useRef<AbortController | null>(null);
  const generationAttempt = useRef<{
    id: string;
    payload: Record<string, unknown>;
    inspiration: InspirationGenerationOptions | undefined;
    contentType: ContentType;
    creativeMode: CreativeMode;
    campaignName: string;
    slides: CarouselSlide[];
  } | null>(null);
  const [generationPending, setGenerationPending] = useState(false);
  const [retryingImage, setRetryingImage] = useState(false);

  // AI brief state
  const [campaignName, setCampaignName] = useState("");
  const [product, setProduct] = useState("");
  const [audience, setAudience] = useState("");
  const [location, setLocation] = useState("");
  const [occasion, setOccasion] = useState("");
  const [offer, setOffer] = useState("");
  const [brandTone, setBrandTone] = useState("");
  const [creativeBrief, setCreativeBrief] = useState("");
  const [creativeMode, setCreativeMode] = useState<CreativeMode | null>(null);
  const [creativeSelections, setCreativeSelections] = useState<CreativeSelection[]>([]);
  // The brand's uploaded BRAND_TEMPLATE inspirations — what "Your templates"
  // offers. null = not loaded yet; the id is the one the user picked.
  const [brandTemplates, setBrandTemplates] = useState<Inspiration[] | null>(null);
  const [brandTemplatesError, setBrandTemplatesError] = useState("");
  const [creativeTemplateId, setCreativeTemplateId] = useState("");
  const [templatesAttempt, setTemplatesAttempt] = useState(0);
  // The founder's flow additions: target platform (drives aspect + copy
  // manners), quality tier (Ultra bills 2 units), and template fidelity
  // (EXACT recreates the design, INSPIRED borrows only its flavour). All
  // three are remembered per brand.
  const [posterPlatform, setPosterPlatform] = useState("instagram_post");
  const [imageQuality, setImageQuality] = useState("4K");
  const [templateFidelity, setTemplateFidelity] = useState<"EXACT" | "INSPIRED">("EXACT");

  // The brand's model/ambassador photos. null = loading; the toggle defaults
  // ON — the founder's rule is that the model fronts every creative.
  const [ambassadors, setAmbassadors] = useState<Inspiration[] | null>(null);
  const [featureModel, setFeatureModel] = useState(true);
  const [ambassadorUploading, setAmbassadorUploading] = useState(false);
  const ambassadorInputRef = useRef<HTMLInputElement>(null);
  const [inspirationFlowError, setInspirationFlowError] = useState<string | null>(null);
  const [activeInspirationGeneration, setActiveInspirationGeneration] =
    useState<InspirationGenerationOptions | null>(null);
  const [inspirationRetryAllowed, setInspirationRetryAllowed] = useState(false);

  // What to generate, plus the per-type extras
  const [contentType, setContentType] = useState<ContentType>("poster");
  const [videoDuration, setVideoDuration] = useState(VIDEO_DURATIONS[1]!);
  const [videoAspect, setVideoAspect] = useState(VIDEO_ASPECTS[0]!);
  const [videoStyle, setVideoStyle] = useState(VIDEO_STYLES[0]!);
  const [videoScript, setVideoScript] = useState("");
  const [slides, setSlides] = useState<CarouselSlide[]>([newSlide(), newSlide(), newSlide()]);

  // Also the brand's logo + poster defaults, so the studio's logo chip is a
  // live control over the same setting Brand Master edits, not a copy.
  const {
    brandId,
    settings: brandKit,
    update: updateBrandKit,
    loading: brandKitLoading,
  } = useBrandSettings();

  // Remembered quick choices, per brand: the second visit should be
  // brief-only, with platform, quality and fidelity already set.
  useEffect(() => {
    if (!brandId) return;
    try {
      const saved = JSON.parse(localStorage.getItem(studioDefaultsKey(brandId)) || "{}");
      if (POSTER_PLATFORMS.some((p) => p.id === saved.platform))
        setPosterPlatform(saved.platform);
      if (QUALITY_TIERS.some((q) => q.id === saved.quality)) setImageQuality(saved.quality);
      if (saved.fidelity === "INSPIRED" || saved.fidelity === "EXACT")
        setTemplateFidelity(saved.fidelity);
    } catch {
      /* corrupted defaults are just defaults */
    }
  }, [brandId]);
  useEffect(() => {
    if (!brandId) return;
    try {
      localStorage.setItem(
        studioDefaultsKey(brandId),
        JSON.stringify({
          platform: posterPlatform,
          quality: imageQuality,
          fidelity: templateFidelity,
        }),
      );
    } catch {
      /* private mode — remembering is a convenience, not a requirement */
    }
  }, [brandId, posterPlatform, imageQuality, templateFidelity]);
  // The built-in layout catalogue no longer feeds creation; it survives only
  // for the manual Poster Studio on an already generated item.
  const layoutCatalogue = useLayoutCatalogue(Boolean(asset?.contentItemId));
  const creativeBrand = useRef<string | null>(null);

  // Load the brand's uploaded templates for the "Your templates" direction,
  // and the ambassador photos for the "Feature your model" toggle.
  useEffect(() => {
    if (!brandId) return;
    let cancelled = false;
    setBrandTemplatesError("");
    fetchBrandTemplates(brandId)
      .then((rows) => {
        if (!cancelled) {
          setBrandTemplates(rows.filter((row) => row.lifecycle_status !== "ARCHIVED"));
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setBrandTemplatesError(
            reason instanceof Error ? reason.message : "Your templates could not load.",
          );
        }
      });
    fetchBrandAmbassadors(brandId)
      .then((rows) => {
        if (!cancelled) setAmbassadors(rows);
      })
      .catch(() => {
        // The toggle simply stays hidden; generation runs without the photo.
        if (!cancelled) setAmbassadors([]);
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, templatesAttempt]);

  // Founder directive: with no uploaded templates, AI original is the default
  // direction rather than an unmade choice.
  useEffect(() => {
    if (brandTemplates !== null && brandTemplates.length === 0 && creativeMode === null) {
      setCreativeMode("AI_ORIGINAL");
    }
  }, [brandTemplates, creativeMode]);

  const chooseCreativeMode = (next: CreativeMode) => {
    setCreativeMode(next);
    if (next !== "BRAND_TEMPLATE") setCreativeTemplateId("");
  };

  useEffect(() => {
    if (contentType !== "poster" && creativeMode === "BRAND_TEMPLATE") {
      setCreativeMode(null);
      setCreativeTemplateId("");
    }
  }, [contentType, creativeMode]);

  useEffect(() => {
    if (creativeBrand.current && creativeBrand.current !== brandId) {
      // A queued result belongs to the client that started it. Stop polling
      // and clear every browser-only reference when the active client changes
      // so the old client's result can never appear in the new client's UI.
      generationAbort.current?.abort();
      generationAttempt.current = null;
      setGenerationPending(false);
      setCreativeSelections([]);
      setReferenceImageBase64("");
      setAsset(null);
      setInspirationFlowError(null);
      setActiveInspirationGeneration(null);
      setInspirationRetryAllowed(false);
      setCampaignName("");
      setProduct("");
      setAudience("");
      setLocation("");
      setOccasion("");
      setOffer("");
      setBrandTone("");
      setCreativeBrief("");
      setCreativeMode(null);
      setCreativeTemplateId("");
      setBrandTemplates(null);
      setVideoScript("");
      setSlides([newSlide(), newSlide(), newSlide()]);
      setStep("ai_form");
    }
    creativeBrand.current = brandId;
  }, [brandId]);

  const addSlide = () => setSlides((prev) => [...prev, newSlide()]);
  const removeSlide = (id: string) =>
    setSlides((prev) => (prev.length <= 1 ? prev : prev.filter((s) => s.id !== id)));
  const updateSlide = (id: string, description: string) =>
    setSlides((prev) => prev.map((s) => (s.id === id ? { ...s, description } : s)));
  const moveSlide = (index: number, direction: -1 | 1) =>
    setSlides((prev) => {
      const target = index + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const [moved] = next.splice(index, 1);
      next.splice(target, 0, moved!);
      return next;
    });

  // Publishing State
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<"now" | "schedule">("now");
  // Scheduled publishing: the moment is sent to the backend as scheduled_at.
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("");
  const [running, setRunning] = useState(false);
  const [publishingHistory, setPublishingHistory] = useState<PublishingHistoryRow[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyLoadingMore, setHistoryLoadingMore] = useState(false);
  const historyPage = useRef(1);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [retryingSlide, setRetryingSlide] = useState<number | null>(null);
  const [accounts, setAccounts] = useState<PublishingAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void fetchCurrentBrand()
      .then((brand) => {
        if (cancelled) return;
        setAwaitingApproval(brand?.status === "PENDING");
        if (!brand) return;
        setAudience((current) => current || brand.audience || "");
        setLocation((current) => current || brand.location || "");
        setBrandTone((current) => current || brand.brand_tone || "");
        const firstProduct = Array.isArray(brand.products_services)
          ? brand.products_services.find((row) => {
              if (!row || typeof row !== "object") return false;
              return typeof (row as { name?: unknown }).name === "string";
            })
          : undefined;
        const firstProductName =
          firstProduct && typeof firstProduct === "object"
            ? String((firstProduct as { name?: unknown }).name || "")
            : "";
        setProduct((current) => current || firstProductName);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  /** (Re)loads the first page of history; "Load more" appends the rest. */
  const loadHistory = useCallback(async () => {
    try {
      // ?page_size= opts in to the {count, next, previous, results}
      // envelope so history stops fetching every job ever published.
      // An older deployment ignores the params and answers the bare
      // array it always has — asList reads both.
      const res = await apiFetch(`/api/marketing/publishing/jobs/?page_size=${HISTORY_PAGE_SIZE}`);
      const data = await res.json();
      const jobs = asList<PublishingJobDto>(data);
      if (
        !jobs.length &&
        !Array.isArray(data) &&
        !(
          data &&
          typeof data === "object" &&
          Array.isArray((data as { results?: unknown }).results)
        )
      ) {
        setHistoryError(true);
        return;
      }
      historyPage.current = 1;
      setPublishingHistory(toHistoryRows(jobs));
      setHistoryHasMore(hasNextPage(data));
      setHistoryError(false);
    } catch (err) {
      console.error("Failed to load history:", err);
      // An empty table and a failed fetch used to look identical. They are
      // not the same thing, and only one of them is worth retrying.
      setHistoryError(true);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const loadMoreHistory = async () => {
    setHistoryLoadingMore(true);
    try {
      const page = historyPage.current + 1;
      const res = await apiFetch(
        `/api/marketing/publishing/jobs/?page_size=${HISTORY_PAGE_SIZE}&page=${page}`,
      );
      if (!res.ok) throw new Error(`History page ${page} failed (${res.status}).`);
      const data = await res.json();
      historyPage.current = page;
      setPublishingHistory((prev) => [...prev, ...toHistoryRows(asList<PublishingJobDto>(data))]);
      setHistoryHasMore(hasNextPage(data));
    } catch (err) {
      console.error("Failed to load more history:", err);
      toast.error("Could not load more history.");
    } finally {
      setHistoryLoadingMore(false);
    }
  };

  /**
   * Re-queues one failed item. The worker skips items already published.
   *
   * The retry action is registered on the jobs router with detail=False, so it
   * lives under .../jobs/items/<id>/retry/. Posting to .../items/<id>/retry/
   * simply 404s, which is why every retry used to fail.
   */
  const retryItem = async (itemId: string) => {
    setRetrying(itemId);
    try {
      await apiPost(`/api/marketing/publishing/jobs/items/${itemId}/retry/`, {});
      toast.success("Queued for retry.");
      await loadHistory();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not retry that post.");
    } finally {
      setRetrying(null);
    }
  };

  const regenerateSlide = async (position: number) => {
    if (!asset?.contentItemId || contentLocked) return;
    setRetryingSlide(position);
    try {
      const item = await apiPost<ContentItemDto>(
        `/api/marketing/content/${asset.contentItemId}/regenerate-slide/`,
        { position },
      );
      setAsset((current) =>
        current
          ? {
              ...current,
              id: item.asset ?? current.id,
              previewUrl: item.preview_url || current.previewUrl,
              slides: (item.slides ?? []).map((slide, index) => ({
                id: current.slides?.[index]?.id ?? `saved-slide-${index}`,
                description: slide.description ?? "",
                previewUrl: slide.preview_url,
              })),
            }
          : current,
      );
      toast.success(`Slide ${position} regenerated. Other slides and copy were preserved.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not regenerate that slide.");
    } finally {
      setRetryingSlide(null);
    }
  };

  const refreshComposedPoster = async () => {
    if (!asset?.contentItemId) return;
    // `onRendered` calls this only after the replacement composition was
    // saved successfully. Resolve the partial-failure warning immediately;
    // a follow-up preview refresh failure must not resurrect stale guidance.
    setAsset((current) => (current ? { ...current, compositionWarning: undefined } : current));
    try {
      const item = await api<ContentItemDto>(`/api/marketing/content/${asset.contentItemId}/`);
      setAsset((current) =>
        current
          ? {
              ...current,
              id: item.asset ?? current.id,
              previewUrl: item.preview_url || current.previewUrl,
            }
          : current,
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not refresh the poster.");
    }
  };

  useEffect(() => {
    // Fetch connected accounts for publishing
    apiFetch("/api/marketing/social-accounts/")
      .then((res) => res.json())
      .then((data) => {
        const rows = asList<PublishingAccount>(
          data && typeof data === "object" && "success" in (data as object)
            ? (data as { data?: unknown }).data
            : data,
        );
        if (rows.length || Array.isArray(data) || data) setAccounts(rows);
      })
      .catch(console.error)
      .finally(() => setAccountsLoading(false));

    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    const contentId = new URLSearchParams(window.location.search).get("content_item_id");
    if (!contentId) return;

    let cancelled = false;
    void api<ContentItemDto>(`/api/marketing/content/${contentId}/`)
      .then((item) => {
        if (cancelled) return;
        if (item.status !== "APPROVED") {
          throw new Error(
            `Content is ${item.status.replaceAll("_", " ").toLowerCase()}, not approved.`,
          );
        }
        const mappedType: ContentType =
          item.content_format === "VIDEO"
            ? "video"
            : item.content_format === "CAROUSEL"
              ? "carousel"
              : "poster";
        setAsset({
          id: item.asset ?? undefined,
          contentItemId: item.id,
          name: item.headline || "Approved content",
          type: mappedType === "video" ? "VIDEO" : "IMAGE",
          dimensions: "Approved version",
          created: "Ready to publish",
          source: item.ai_provider ? "ai" : "upload",
          contentType: mappedType,
          campaign: item.headline,
          postTitle: item.headline,
          postDescription: item.caption,
          postHashtags: item.hashtags,
          previewUrl: item.preview_url || undefined,
          ...(mappedType === "carousel" && Array.isArray(item.slides)
            ? {
                slides: item.slides.map((slide, index) => ({
                  id: `saved-slide-${index}`,
                  description: slide.description ?? "",
                  previewUrl: slide.preview_url,
                })),
              }
            : {}),
        });
        setContentLocked(true);
        setStep("publish_setup");
      })
      .catch((error: unknown) => {
        toast.error(error instanceof Error ? error.message : "Could not open approved content.");
        window.history.replaceState(null, "", "/publishing");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const isVideoAsset = asset?.contentType === "video";

  useEffect(() => {
    // A tick made before the media changed must not survive into the payload.
    // Swapping a video for a poster leaves the YouTube row disabled but its id
    // still selected, and the backend then reports success for a post it never
    // made. Same for a stale selection carried over from an earlier publish.
    setSelected((prev) => {
      const next = prev.filter((id) =>
        accounts.some((a) => a.id === id && canPublishTo(a, isVideoAsset)),
      );
      return next.length === prev.length ? prev : next;
    });
  }, [accounts, isVideoAsset]);

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  /**
   * The saved asset: its id AND the URL it was actually stored at.
   *
   * The URL is what matters. A freshly picked photo lives in the browser as a
   * `data:` URL, and that was being sent on to ContentItem.preview_url, which
   * is a URLField(max_length=1000) — wrong scheme and thousands of characters
   * too long, so saving an uploaded poster failed every time. The asset
   * upload below has always produced a real URL; nothing was passing it on.
   */
  const ensureDraftAsset = async (draft: DraftAsset): Promise<{ id: string; fileUrl: string }> => {
    if (draft.id) return { id: draft.id, fileUrl: draft.previewUrl ?? "" };
    const workspaceId = readSelectedWorkspaceId();
    if (!workspaceId) throw new Error("Select a client before saving content.");
    if (!draft.previewUrl) throw new Error("Attach or generate media before saving this draft.");

    if (draft.previewUrl.startsWith("data:")) {
      const blob = await (await fetch(draft.previewUrl)).blob();
      const form = new FormData();
      form.append("file", blob, draft.name || "content-media");
      form.append("workspace_id", workspaceId);
      form.append("source", draft.source === "ai" ? "AI_GENERATED" : "MANUAL_UPLOAD");
      const response = await apiFetch("/api/marketing/assets/upload/", {
        method: "POST",
        body: form,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || payload?.success === false || !payload?.data?.id) {
        throw new Error(payload?.message || "Could not save the media asset.");
      }
      return {
        id: String(payload.data.id),
        fileUrl: String(payload.data.file_url ?? ""),
      };
    }

    // Generated media already has a persisted asset id. A URL alone must not
    // become a trusted publishing asset: integrations may download its bytes.
    throw new Error(
      "This media has no saved asset. Open its saved draft in Content or upload the file before saving.",
    );
  };

  const saveContentDraft = async ({ submit = false }: { submit?: boolean } = {}) => {
    if (!asset || contentLocked) return;
    setContentSaving(true);
    try {
      if (!asset.id && asset.contentItemId && asset.mediaWarning) {
        if (submit) throw new Error("Finish the missing image before submitting for review.");
        await api(`/api/marketing/content/${asset.contentItemId}/`, {
          method: "PATCH",
          body: {
            headline: asset.postTitle,
            caption: asset.postDescription,
            hashtags: asset.postHashtags,
          },
        });
        toast.success("Copy saved. Retry the missing image when ready.");
        return;
      }
      const { id: assetId, fileUrl } = await ensureDraftAsset(asset);
      // Never send a data: URL to the server. It is not a URL the model can
      // store, and it is not one anything else could load either.
      const storedUrl = (url: string | undefined | null) =>
        url && !url.startsWith("data:") ? url : "";
      const contentFormat =
        asset.contentType === "video"
          ? "VIDEO"
          : asset.contentType === "carousel"
            ? "CAROUSEL"
            : "POSTER";
      const body = {
        asset: assetId,
        content_format: contentFormat,
        headline: asset.postTitle,
        caption: asset.postDescription,
        hashtags: asset.postHashtags,
        preview_url: storedUrl(asset.previewUrl) || storedUrl(fileUrl),
        slides: (asset.slides ?? []).map((slide, index) => ({
          position: index + 1,
          description: slide.description,
          preview_url: storedUrl(slide.previewUrl),
        })),
      };

      let contentId = asset.contentItemId;
      if (contentId) {
        await api<ContentItemDto>(`/api/marketing/content/${contentId}/`, {
          method: "PATCH",
          body,
        });
      } else {
        const created = await api<ContentItemDto>("/api/marketing/content/", {
          method: "POST",
          body,
        });
        contentId = created.id;
      }

      if (!contentId) throw new Error("The draft was saved without a content id.");
      setAsset({ ...asset, id: assetId, contentItemId: contentId });

      if (submit) {
        await apiPost(`/api/marketing/content/${contentId}/submit/`, {});
        toast.success("Submitted for review.");
        window.location.assign("/review");
      } else {
        toast.success("Draft saved. You can reopen it from Review → Drafts.");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save this draft.");
    } finally {
      setContentSaving(false);
    }
  };

  const runJobs = async (ids: string[]) => {
    if (ids.length === 0) return;
    let scheduledAt: string | null = null;
    if (mode === "schedule") {
      const when = new Date(`${scheduleDate}T${scheduleTime}`);
      if (!scheduleDate || !scheduleTime || Number.isNaN(when.getTime())) {
        toast.error("Pick a date and time to schedule.");
        return;
      }
      if (when.getTime() <= Date.now()) {
        toast.error("The scheduled time must be in the future.");
        return;
      }
      scheduledAt = when.toISOString();
    }
    setRunning(true);
    toast(mode === "schedule" ? "Scheduling…" : "Publishing started.");

    try {
      const wsId = readSelectedWorkspaceId();
      const assetId = asset?.id ?? null;
      const contentItemId = asset?.contentItemId ?? null;
      if (!wsId || !assetId || !contentItemId || !contentLocked) {
        throw new Error("Open an approved saved version from Review before publishing.");
      }

      const res = await apiFetch("/api/marketing/publishing/jobs/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: wsId,
          asset_id: assetId,
          publish_mode: mode === "now" ? "NOW" : "SCHEDULED",
          ...(scheduledAt ? { scheduled_at: scheduledAt } : {}),
          social_connection_ids: ids,
          content_item_id: contentItemId,
        }),
      });

      const data = await res.json();

      if (data.success) {
        toast.success(
          mode === "schedule"
            ? "Scheduled. It will publish at the chosen time."
            : "Publishing job created.",
        );
        // The run is over; carrying these ticks back to step one would put
        // them on the next post as well.
        setSelected([]);
        // And the lock goes with it. `contentLocked` is set when arriving
        // from Review with an approved item — it was never cleared, so the
        // NEXT post generated in this session was born locked and unsavable,
        // still captioned "This is the approved version". Releasing it here
        // is what makes a second post possible without a page reload.
        setContentLocked(false);
        if (typeof window !== "undefined" && window.location.search) {
          window.history.replaceState({}, "", window.location.pathname);
        }
        setStep("ai_form");
      } else {
        toast.error(data.message || "Failed to publish.");
      }
    } catch (err: unknown) {
      console.error(err);
      toast.error(err instanceof Error ? err.message : "Network error while publishing.");
    } finally {
      setRunning(false);
      await loadHistory();
    }
  };

  /**
   * Waits for a queued generation to finish.
   *
   * The request row is the progress record: it moves PENDING -> GENERATING ->
   * COMPLETED, and the result is fetched once it lands. Polling stops at the
   * ceiling rather than forever, so a stuck worker surfaces as an error
   * instead of a spinner nobody can escape. The signal is the escape hatch
   * before that ceiling — ten minutes is a long time to trap someone.
   */
  const pollGeneration = async (generationId: string, signal: AbortSignal) => {
    const started = Date.now();
    const CEILING_MS = 10 * 60 * 1000;
    const EVERY_MS = 3000;

    while (Date.now() - started < CEILING_MS) {
      await new Promise((resolve) => setTimeout(resolve, EVERY_MS));
      if (signal.aborted) throw new DOMException("Cancelled", "AbortError");

      const res = await apiFetch(`/api/marketing/ai-generation/${generationId}/`, { signal });
      const json = await res.json();
      if (!res.ok || json.success === false) {
        throw new Error(
          json.message || "Could not check generation status. Resume this attempt to check again.",
        );
      }
      const request = json.data ?? json;
      const execution = request?.execution;
      const progress = request?.progress;
      if (progress?.content_type === "carousel" && progress.total_slides) {
        setProductionProgress(
          `Copy ready · ${progress.completed_slides}/${progress.total_slides} slides saved.`,
        );
      } else if (progress?.content_type === "video") {
        setProductionProgress(
          progress.video_complete
            ? "Video saved. Finalising the preview…"
            : progress.copy_complete
              ? "Copy ready · your video provider is producing the clip."
              : "Building the copy and video direction…",
        );
      }

      const decision = generationDecision(request);
      if (decision === "wait") {
        if (execution?.state === "RETRY_PENDING")
          setProductionProgress(
            "A worker retry is queued. Your existing generation is still running.",
          );
        continue;
      }
      if (decision === "failed") {
        throw new GenerationRequestFailedError(
          request.error_message || "Generation failed.",
          execution?.retry_allowed === true,
        );
      }

      const resultRes = await apiFetch(`/api/marketing/ai-generation/${generationId}/results/`, {
        signal,
      });
      const resultJson = await resultRes.json();
      if (!resultRes.ok || resultJson.success === false)
        throw new Error("Could not load the saved generation. Resume to try again.");
      const result = resultJson.data ?? {};
      const metadata = result.metadata ?? {};
      if (!metadata.contentItemId)
        throw new Error("The generation has no saved draft yet. Resume to check again.");

      return {
        postTitle: metadata.postTitle ?? "",
        postDescription: result.generated_text ?? "",
        postHashtags: metadata.postHashtags ?? "",
        posterImageUrl: metadata.videoUrl ? "" : (result.generated_asset_url ?? ""),
        videoUrl: metadata.videoUrl ?? "",
        slideImageUrls: metadata.slideImageUrls ?? [],
        metadata,
        contentItemId: metadata.contentItemId ?? null,
        assetId: metadata.assetId ?? null,
      };
    }

    // The backend sweeps stuck generations at the same ten-minute mark: one
    // rescue re-run, then an honest FAILED. So past the ceiling the truth is
    // "it may still land in your drafts" — not "keep watching this spinner".
    throw new Error(
      "Generation is taking longer than expected. If it finishes, it will appear in Review → Drafts.",
    );
  };

  /** Stops the wait. Anything already queued keeps running on the server. */
  const cancelGeneration = () => {
    generationAbort.current?.abort();
  };

  const handleGenerate = async (inspiration?: InspirationGenerationOptions) => {
    const pending = generationAttempt.current;
    if (pending) inspiration = pending.inspiration;
    const requestedContentType: ContentType =
      pending?.contentType ?? (inspiration ? "poster" : contentType);
    const requestedMode: CreativeMode =
      pending?.creativeMode ?? (inspiration ? "REFERENCE" : creativeMode!);
    if (!inspiration && !pending) {
      if (!creativeMode) {
        toast.error("Choose how Scaleezy should design this content.");
        return;
      }
      if (creativeMode === "BRAND_TEMPLATE" && !creativeTemplateId) {
        toast.error("Choose one of your templates before generation.");
        return;
      }
      if (
        creativeMode === "REFERENCE" &&
        !referenceImageBase64 &&
        creativeSelections.length === 0
      ) {
        toast.error("Upload or choose at least one inspiration.");
        return;
      }
      if (!creativeBrief.trim() && !campaignName.trim() && !product.trim() && !offer.trim()) {
        toast.error("Tell Scaleezy what you want to create.");
        return;
      }
    }
    const startedBrandId = brandId;
    const controller = new AbortController();
    let queued = false;
    setActiveInspirationGeneration(inspiration ?? null);
    if (inspiration) setInspirationRetryAllowed(false);
    generationAbort.current = controller;
    setProductionProgress("");
    setWorkingKind("generate");
    setStep("ai_generating");
    try {
      // Everything generates on the queue now. Video and carousels always
      // did (gateway timeouts); posters were the last synchronous path, and
      // one of them held a whole web worker for the length of a provider
      // call — the entire deployment could serve about six posters a minute
      // and nothing else while it did. The queue costs a few seconds of
      // polling latency and returns the identical payload.
      const endpoint = "/api/marketing/ai-generation/generate-async/";

      const requestedCampaignName =
        pending?.campaignName ?? (inspiration?.inspirationTitle || campaignName);
      const generationPayload = inspiration
        ? {
            creativeMode: requestedMode,
            campaignName: requestedCampaignName,
            product: "",
            audience: "",
            location: "",
            occasion: "",
            offer: "",
            brandTone: "",
            inspirationSelections: [
              {
                sourceType: "BRAND",
                id: inspiration.inspirationId,
                role: "PRIMARY",
                direction: "USE",
                focusAreas: [],
              } satisfies CreativeSelection,
            ],
            layout: "",
            contentType: requestedContentType,
            instruction: inspiration.instruction,
            analyzeBeforeGenerationIds: [inspiration.inspirationId],
          }
        : {
            // A chosen brand template travels exactly like a create-from-
            // inspiration selection: REFERENCE mode plus one PRIMARY/USE
            // BRAND selection, analysed before generation if needed. The
            // backend never learns a separate template mode.
            creativeMode: requestedMode === "BRAND_TEMPLATE" ? "REFERENCE" : requestedMode,
            campaignName,
            product,
            audience,
            location,
            occasion,
            offer,
            brandTone,
            instruction: creativeBrief,
            featureAmbassador: featureModel && (ambassadors?.length ?? 0) > 0,
            platform: requestedContentType === "poster" ? posterPlatform : "",
            imageQuality: requestedContentType === "poster" ? imageQuality : "",
            templateFidelity,
            referenceImageBase64: requestedMode === "REFERENCE" ? referenceImageBase64 : "",
            inspirationSelections:
              requestedMode === "REFERENCE"
                ? creativeSelections
                : requestedMode === "BRAND_TEMPLATE"
                  ? [
                      {
                        sourceType: "BRAND",
                        id: creativeTemplateId,
                        role: "PRIMARY",
                        direction: "USE",
                        focusAreas: [],
                      } satisfies CreativeSelection,
                    ]
                  : [],
            layout: "",
            ...(requestedMode === "BRAND_TEMPLATE"
              ? { analyzeBeforeGenerationIds: [creativeTemplateId] }
              : {}),
            contentType: requestedContentType,
            ...(requestedContentType === "video"
              ? {
                  videoDuration,
                  videoAspect,
                  videoStyle,
                  videoScript,
                }
              : {}),
            ...(requestedContentType === "carousel"
              ? {
                  slides: slides.map((s, i) => ({
                    position: i + 1,
                    description: s.description.trim() || slidePlaceholder(i),
                  })),
                }
              : {}),
          };

      const attempt = pending ?? {
        id: crypto.randomUUID(),
        payload: generationPayload,
        inspiration,
        contentType: requestedContentType,
        creativeMode: requestedMode,
        campaignName: requestedCampaignName,
        slides: [...slides],
      };
      generationAttempt.current = attempt;
      setGenerationPending(true);
      const res = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        // The inspiration-led branch intentionally contains IDs only. The
        // worker re-resolves and analyzes the saved reference; browser base64
        // never enters durable generation state.
        body: JSON.stringify({ ...attempt.payload, requestId: attempt.id }),
      });
      const json = await res.json();
      if (!json.success) {
        const code = String(json.error?.code || "");
        const definitelyNotRunning = canDiscardRejectedDelivery(Boolean(pending), res.status, code);
        if (definitelyNotRunning) {
          generationAttempt.current = null;
          setGenerationPending(false);
        }
        throw new InspirationGenerationFlowError(
          json.message || "Generation failed",
          false,
          definitelyNotRunning,
        );
      }
      queued = true;
      const d = await pollGeneration(json.data.generationId, controller.signal);
      generationAttempt.current = null;
      setGenerationPending(false);

      const returnedSlides: string[] = Array.isArray(d.slideImageUrls) ? d.slideImageUrls : [];

      const label =
        requestedContentType === "video"
          ? "Video"
          : requestedContentType === "carousel"
            ? "Carousel"
            : "Poster";
      const fileType = requestedContentType === "video" ? "VIDEO" : "JPG";

      setAsset({
        id: d.assetId || undefined,
        generationId: json.data.generationId,
        mediaWarning:
          d.metadata?.media?.status === "FAILED"
            ? String(d.metadata.media.error || "The image failed. Your copy is saved.")
            : undefined,
        name: `${requestedCampaignName || "Untitled"} ${label}.${requestedContentType === "video" ? "mp4" : "jpg"}`,
        type: fileType,
        dimensions:
          requestedContentType === "video"
            ? videoAspect
            : requestedContentType === "carousel"
              ? `1080×1080 · ${slides.length} slides`
              : "1080×1350",
        created: new Date().toLocaleDateString("en-GB", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        }),
        source: "ai",
        contentType: requestedContentType,
        campaign: requestedCampaignName,
        tone: "",
        postTitle: d.postTitle || `${requestedCampaignName || "Untitled"} Announcement`,
        postDescription: d.postDescription || "",
        postHashtags: d.postHashtags || "",
        previewUrl: d.posterImageUrl || d.videoUrl || undefined,
        compositionWarning:
          d.metadata?.composition?.status === "FAILED"
            ? String(
                d.metadata.composition.error ||
                  "The selected template could not be applied. Your generated draft was kept.",
              )
            : undefined,
        // Row the backend persisted for this generation; sent on publish
        // so the approval gate can be enforced.
        contentItemId: d.contentItemId || undefined,
        ...(requestedContentType === "carousel"
          ? {
              slides: attempt.slides.map((s, i) => ({
                ...s,
                description: s.description.trim() || slidePlaceholder(i),
                previewUrl: returnedSlides[i],
              })),
            }
          : {}),
      });
      setStep("preview");
    } catch (err: unknown) {
      if (err instanceof GenerationRequestFailedError && err.retryAllowed) {
        generationAttempt.current = null;
        setGenerationPending(false);
      }
      // A client switch owns the reset. Do not let the cancelled old-client
      // promise reopen any creation screen under the newly selected client.
      if (startedBrandId && creativeBrand.current && startedBrandId !== creativeBrand.current)
        return;

      if (inspiration) {
        if (err instanceof InspirationGenerationFlowError) throw err;
        const message =
          err instanceof Error && err.name === "AbortError"
            ? "Stopped waiting for the poster."
            : err instanceof Error
              ? err.message
              : "The poster could not be generated.";
        throw new InspirationGenerationFlowError(
          message,
          queued,
          // A queued request may still be retried by the durable task runner
          // after its application row briefly reports FAILED. Never offer a
          // second user-triggered request while that ownership is ambiguous.
          err instanceof GenerationRequestFailedError && err.retryAllowed,
        );
      }
      if (err instanceof Error && err.name === "AbortError") {
        toast("Stopped waiting. Anything already queued keeps running.");
        setStep("ai_form");
        return;
      }
      console.error("AI generation error:", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to generate content. Please try again.",
      );
      setStep("ai_form");
    } finally {
      if (generationAbort.current === controller) generationAbort.current = null;
    }
  };

  const retryMissingImage = async () => {
    if (!asset?.generationId || retryingImage) return;
    const id = asset.generationId;
    const selectedClient = readSelectedWorkspaceId();
    setRetryingImage(true);
    try {
      try {
        await apiPost(`/api/marketing/ai-generation/${id}/retry-image/`, {});
      } catch (error) {
        // A previous retry may still own the task, or may already have saved
        // its image after a lost response. Read that same generation instead.
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
      }
      const result = await pollGeneration(id, new AbortController().signal);
      if (readSelectedWorkspaceId() !== selectedClient) return;
      if (!hasSavedGenerationImage(result)) {
        throw new Error(
          result.metadata?.media?.error || "The image was not saved. Your copy is unchanged.",
        );
      }
      setAsset((current) =>
        current?.generationId === id
          ? {
              ...current,
              id: result.assetId || undefined,
              previewUrl: result.posterImageUrl || undefined,
              mediaWarning:
                result.metadata?.media?.status === "FAILED"
                  ? result.metadata.media.error
                  : undefined,
              compositionWarning:
                result.metadata?.composition?.status === "FAILED"
                  ? result.metadata.composition.error
                  : undefined,
            }
          : current,
      );
      toast.success("Image saved. Your existing copy was preserved.");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Image retry failed. Your copy is unchanged.",
      );
    } finally {
      setRetryingImage(false);
    }
  };

  const handleCreateFromInspiration = async (input: CreateFromInspirationInput) => {
    const startedBrandId = brandId;
    if (!startedBrandId) {
      setInspirationFlowError("Select a client before creating content.");
      return;
    }

    setInspirationFlowError(null);
    let savedTitle = "Inspiration-led poster";
    let savedId: string | null = null;

    try {
      const title =
        input.source === "upload"
          ? input.file.name
          : new URL(input.url).hostname.replace(/^www\./, "");
      const inspirationInput: InspirationInput = {
        title,
        inspiration_type: input.source === "upload" ? "IMAGE" : "REFERENCE",
        annotation: "Campaign reference saved from Content. Use as creative direction, not a copy.",
        external_platform: "",
        usage_scope: "FULL_REFERENCE",
        focus_areas: [],
      };

      const saved =
        input.source === "upload"
          ? await uploadInspiration(startedBrandId, input.file, inspirationInput)
          : await createInspiration(startedBrandId, {
              ...inspirationInput,
              reference_url: input.url,
            });

      savedId = saved.id;
      savedTitle = saved.title || title;
      if (!savedId) throw new Error("The inspiration was saved without an id.");

      await handleGenerate({
        inspirationId: savedId,
        inspirationTitle: savedTitle,
        instruction: input.instruction,
      });
    } catch (error) {
      // Switching client cancels this flow; its old-client promise must not
      // render an error or reopen a form in the new client.
      if (creativeBrand.current !== startedBrandId) return;

      const message = error instanceof Error ? error.message : "The poster could not be created.";
      const queued = error instanceof InspirationGenerationFlowError && error.queued;
      const retryAllowed = error instanceof InspirationGenerationFlowError && error.retryAllowed;
      setInspirationRetryAllowed(retryAllowed);
      const honestMessage = savedId
        ? retryAllowed
          ? `Your inspiration was saved in Brand Master, but the poster is not running. You can retry without uploading it again. ${message}`
          : queued
            ? `Your inspiration was saved and the poster was queued. It may still appear in Review → Drafts, so retry is disabled to prevent duplicate AI spend. ${message}`
            : `Your inspiration was saved, but Scaleezy could not confirm whether the poster was queued. Check Review → Drafts before starting another. ${message}`
        : message;
      setInspirationFlowError(honestMessage);
      toast.error(honestMessage);
      setStep("inspiration_form");
    }
  };

  const handleRetrySavedInspiration = async (instruction: string) => {
    if (!activeInspirationGeneration) {
      setInspirationFlowError("Choose an inspiration before creating the poster.");
      return;
    }
    if (!inspirationRetryAllowed) {
      setInspirationFlowError(
        "This request may still be running. Check Review → Drafts before starting another.",
      );
      return;
    }

    const startedBrandId = brandId;
    const retry = { ...activeInspirationGeneration, instruction };
    setActiveInspirationGeneration(retry);
    setInspirationFlowError(null);
    try {
      await handleGenerate(retry);
    } catch (error) {
      if (startedBrandId && creativeBrand.current !== startedBrandId) return;
      const message = error instanceof Error ? error.message : "The poster could not be created.";
      const queued = error instanceof InspirationGenerationFlowError && error.queued;
      const retryAllowed = error instanceof InspirationGenerationFlowError && error.retryAllowed;
      setInspirationRetryAllowed(retryAllowed);
      const honestMessage = retryAllowed
        ? `Your inspiration remains saved in Brand Master and the poster is not running. You can retry. ${message}`
        : queued
          ? `The poster was queued and may still appear in Review → Drafts, so retry is disabled to prevent duplicate AI spend. ${message}`
          : `Scaleezy could not confirm whether the poster was queued. Check Review → Drafts before starting another. ${message}`;
      setInspirationFlowError(honestMessage);
      toast.error(honestMessage);
      setStep("inspiration_form");
    }
  };

  const handleRegenerateAll = async () => {
    if (!activeInspirationGeneration) {
      await handleGenerate();
      return;
    }

    const startedBrandId = brandId;
    try {
      await handleGenerate(activeInspirationGeneration);
    } catch (error) {
      if (startedBrandId && creativeBrand.current !== startedBrandId) return;
      const message =
        error instanceof Error ? error.message : "The poster could not be regenerated.";
      const queued = error instanceof InspirationGenerationFlowError && error.queued;
      toast.error(
        queued
          ? `The regeneration was queued and may still appear in Review → Drafts. ${message}`
          : message,
      );
      setStep("preview");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const input = e.target;
    const file = input.files?.[0];
    // Cleared straight away, not on success: an input still holding the same
    // file fires no change event, so re-picking a file after removing it or
    // after a failed upload used to do nothing at all.
    input.value = "";
    if (!file) return;

    const isVideo = file.type.startsWith("video/");

    if (isVideo) {
      if (uploadIntention === "reference") {
        toast.error("Video cannot be used as a reference for AI generation.");
        return;
      }

      setIsGeneratingCaptions(true);
      setWorkingKind("video");
      setStep("ai_generating");
      try {
        const wsId = readSelectedWorkspaceId();
        if (!wsId) throw new Error("No workspace found.");

        const formData = new FormData();
        formData.append("file", file);
        formData.append("workspace_id", wsId);
        formData.append("source", "MANUAL_UPLOAD");

        const uploadRes = await apiFetch("/api/marketing/assets/upload/", {
          method: "POST",
          body: formData,
        });
        const uploadData = await uploadRes.json();
        if (!uploadData.success) throw new Error("Upload failed.");

        const assetId = uploadData.data.id;
        const fileUrl = uploadData.data.file_url;

        // Analyze video
        const analyzeRes = await apiFetch("/api/marketing/ai-generation/analyze-video/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ asset_id: assetId }),
        });
        const analyzeData = await analyzeRes.json();
        if (!analyzeData.success) throw new Error(analyzeData.message);

        const d = analyzeData.data;

        setAsset({
          id: assetId,
          name: file.name,
          type: "MP4",
          dimensions: "Original",
          created: new Date().toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "short",
            year: "numeric",
          }),
          source: "upload",
          contentType: "video",
          campaign: d.campaignName || "Uploaded Video",
          tone: "",
          postTitle: d.postTitle || "",
          postDescription: d.postDescription || "",
          postHashtags: d.postHashtags || "",
          previewUrl: fileUrl,
        });
        toast.success("Video analyzed successfully!");
        setStep("preview");
      } catch (e) {
        console.error("Failed to process video", e);
        toast.error("Failed to process video.");
        setStep("ai_form");
      } finally {
        setIsGeneratingCaptions(false);
      }
      return;
    }

    // Convert file to base64 for images
    const reader = new FileReader();
    reader.onload = async (event) => {
      const base64String = event.target?.result as string;
      setReferenceImageBase64(base64String);

      if (uploadIntention === "reference") {
        setStep("ai_form");
        setIsAnalyzing(true);
        try {
          const res = await apiFetch("/api/marketing/ai-generation/analyze-image/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ referenceImageBase64: base64String }),
          });
          const json = await res.json();
          if (json.success && json.data) {
            const d = json.data;
            if (d.campaignName) setCampaignName(d.campaignName);
            if (d.product) setProduct(d.product);
            if (d.occasion) setOccasion(d.occasion);
            if (d.brandTone) setBrandTone(d.brandTone);
            toast.success("AI auto-filled your campaign details!");
          } else {
            // apiFetch does not throw on a non-2xx, so a failed analysis used
            // to stop the spinner and leave the form blank with no explanation.
            toast.error(json.message || "Could not read that image. Fill the brief in yourself.");
          }
        } catch (e) {
          console.error("Failed to analyze image", e);
          toast.error("Could not read that image. Fill the brief in yourself.");
        } finally {
          setIsAnalyzing(false);
        }
      } else if (uploadIntention === "final") {
        setIsGeneratingCaptions(true);
        setWorkingKind("captions");
        setStep("ai_generating"); // Re-use the loading step
        try {
          const res = await apiFetch("/api/marketing/ai-generation/generate-captions/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ referenceImageBase64: base64String }),
          });
          const json = await res.json();
          if (!json.success) throw new Error(json.message);

          const d = json.data;
          setAsset({
            name: `Final_Poster.jpg`,
            type: "JPG",
            dimensions: "Original",
            created: new Date().toLocaleDateString("en-GB", {
              day: "2-digit",
              month: "short",
              year: "numeric",
            }),
            source: "upload",
            contentType: "poster",
            campaign: d.postTitle || "Final Poster",
            tone: "",
            postTitle: d.postTitle || "",
            postDescription: d.postDescription || "",
            postHashtags: d.postHashtags || "",
            previewUrl: base64String,
          });
          toast.success("Captions generated successfully!");
          setStep("preview");
        } catch (e) {
          console.error("Failed to generate captions", e);
          toast.error("Failed to generate captions.");
          setStep("ai_form");
        } finally {
          setIsGeneratingCaptions(false);
        }
      }
    };
    reader.readAsDataURL(file);
  };

  const workingMessage =
    workingKind === "captions"
      ? "Reading your poster to write the caption and hashtags."
      : workingKind === "video"
        ? "Uploading your video and watching it to write the caption."
        : activeInspirationGeneration
          ? "Reading the inspiration and creating an original poster with this client's Brand Brain."
          : creativeMode === "REFERENCE" && referenceImageBase64
            ? "Analysing your reference image to craft the marketing asset."
            : `Drafting your ${contentType} from the campaign brief.`;

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Create Studio"
        subtitle="Describe the outcome, choose the creative direction, and let Scaleezy build it with your Brand Brain."
        backTo="/"
      />

      <div className="grid gap-6">
        {generationPending && step !== "ai_generating" ? (
          <div role="status" className="rounded-xl border border-border p-4 text-sm">
            An earlier generation may still be running. Resume it before starting another.
            <Button
              variant="outline"
              className="ml-3"
              onClick={() =>
                void handleGenerate(generationAttempt.current?.inspiration).catch(
                  (error: unknown) =>
                    toast.error(
                      error instanceof Error ? error.message : "Could not resume generation.",
                    ),
                )
              }
            >
              Resume generation
            </Button>
          </div>
        ) : null}
        {step === "inspiration_form" && (
          <CreateFromInspiration
            key={brandId ?? "no-brand"}
            brandId={brandId}
            awaitingApproval={awaitingApproval}
            error={inspirationFlowError}
            savedReference={
              activeInspirationGeneration
                ? {
                    title: activeInspirationGeneration.inspirationTitle,
                    instruction: activeInspirationGeneration.instruction,
                    retryAllowed: inspirationRetryAllowed,
                  }
                : null
            }
            onClearError={() => setInspirationFlowError(null)}
            onSubmit={handleCreateFromInspiration}
            onRetrySaved={handleRetrySavedInspiration}
            onReplaceSaved={() => {
              setActiveInspirationGeneration(null);
              setInspirationRetryAllowed(false);
              setInspirationFlowError(null);
            }}
            onCancel={() => {
              setInspirationFlowError(null);
              setStep("ai_form");
            }}
          />
        )}

        {/* STEP 1A: GEMINI FORM */}
        {step === "ai_form" && (
          <section className="surface-card overflow-hidden">
            <div className="border-b border-border bg-secondary/70 p-5 sm:px-8 sm:py-6">
              <div className="flex items-center gap-4">
                <div className="flex size-12 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Sparkles className="size-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                    CREATE SOMETHING GREAT
                  </h2>
                  <p className="mt-1 text-xs font-semibold tracking-widest text-muted-foreground uppercase">
                    YOU CHOOSE THE DIRECTION · SCALEEZY DOES THE WORK
                  </p>
                </div>
              </div>
            </div>

            <div className="p-5 sm:p-8">
              {creativeMode === "REFERENCE" && referenceImageBase64 && (
                <div className="mb-6 flex items-start gap-4 rounded-lg border border-primary/30 bg-primary/6 p-4">
                  <div className="relative w-24 h-24 rounded-lg overflow-hidden shrink-0 border border-border">
                    <img
                      src={referenceImageBase64}
                      alt="Reference"
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-foreground flex items-center gap-2">
                      Reference Image Uploaded
                      {isAnalyzing && (
                        <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
                      )}
                    </h3>
                    <p className="text-sm text-muted-foreground mt-1">
                      {isAnalyzing
                        ? "Scaleezy is analyzing your image to auto-fill the details..."
                        : "Scaleezy will analyze this image and use your configured AI routing to write the caption and create a polished marketing poster."}
                    </p>
                    <button
                      onClick={() => setReferenceImageBase64("")}
                      className="text-xs text-red-500 font-medium flex items-center gap-1 mt-2 hover:underline"
                    >
                      <X className="size-3" /> Remove image
                    </button>
                  </div>
                </div>
              )}

              {/* WHAT TO GENERATE */}
              <div className="mb-8">
                <Label className="text-xs tracking-wide uppercase">What should we create?</Label>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  {CONTENT_TYPES.map((ct) => {
                    const active = contentType === ct.id;
                    return (
                      <button
                        key={ct.id}
                        type="button"
                        onClick={() => setContentType(ct.id)}
                        aria-pressed={active}
                        className={cn(
                          "flex items-center gap-3 rounded-xl border p-4 text-left transition-colors",
                          active
                            ? "border-primary bg-primary/6"
                            : "border-border hover:bg-secondary/60",
                        )}
                      >
                        <span
                          className={cn(
                            "grid size-10 shrink-0 place-items-center rounded-lg",
                            active
                              ? "bg-primary text-primary-foreground"
                              : "bg-secondary text-muted-foreground",
                          )}
                        >
                          <ct.icon className="size-5" />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-sm font-semibold text-foreground">
                            {ct.label}
                          </span>
                          <span className="block text-xs text-muted-foreground">{ct.hint}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {contentType === "poster" ? (
                <div className="mb-8">
                  <Label className="text-xs tracking-wide uppercase">Where will it run?</Label>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Sets the shape and the caption's manners. Every other size still exports
                    from the result.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {POSTER_PLATFORMS.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        aria-pressed={posterPlatform === p.id}
                        onClick={() => setPosterPlatform(p.id)}
                        className={cn(
                          "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                          posterPlatform === p.id
                            ? "border-primary bg-black text-white"
                            : "border-border bg-background text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {p.label} <span className="opacity-60">· {p.hint}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mb-8 space-y-2">
                <Label htmlFor="creative-brief">What should Scaleezy create?</Label>
                <Textarea
                  id="creative-brief"
                  rows={5}
                  value={creativeBrief}
                  onChange={(event) => setCreativeBrief(event.target.value)}
                  maxLength={MAX_CREATIVE_BRIEF_CHARS}
                  placeholder="Example: Launch our summer linen collection with a premium, energetic poster. Highlight 25% off this weekend and drive people to shop online."
                  className="resize-y text-base"
                />
                <div className="flex items-start justify-between gap-3 text-xs text-muted-foreground">
                  <p>
                    Audience, location, tone and product are filled from Brand Master when
                    available.
                  </p>
                  <span className="shrink-0 tabular-nums" aria-live="polite">
                    {creativeBrief.length}/{MAX_CREATIVE_BRIEF_CHARS}
                  </span>
                </div>
              </div>

              <div className="mb-8">
                <Label className="text-xs tracking-wide uppercase">
                  Choose the creative direction
                </Label>
                <p className="mt-1 text-sm text-muted-foreground">
                  Nothing is selected automatically. This choice applies only to this content.
                </p>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  {CREATIVE_SOURCES.map((source) => {
                    const templatesEmpty =
                      brandTemplates !== null &&
                      brandTemplates.length === 0 &&
                      !brandTemplatesError;
                    const disabled =
                      source.id === "BRAND_TEMPLATE" &&
                      (contentType !== "poster" || templatesEmpty);
                    const disabledHint =
                      contentType !== "poster"
                        ? "Templates are available for posters."
                        : "No templates uploaded yet — add them in Brand Master → Templates.";
                    const active = creativeMode === source.id;
                    return (
                      <button
                        key={source.id}
                        type="button"
                        disabled={disabled}
                        aria-pressed={active}
                        onClick={() => chooseCreativeMode(source.id)}
                        // One horizontal row per card: comfortable to thumb
                        // through on a phone, still a tidy 3-up grid on
                        // desktop.
                        className={cn(
                          "flex items-center gap-3 rounded-xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45 md:p-4",
                          active
                            ? "border-primary bg-black text-white ring-1 ring-primary"
                            : "border-border bg-background hover:border-primary",
                        )}
                      >
                        <span
                          className={cn(
                            "grid size-10 shrink-0 place-items-center rounded-lg",
                            active ? "bg-primary text-black" : "bg-secondary text-foreground",
                          )}
                        >
                          <source.icon className="size-5" />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-sm font-semibold">{source.label}</span>
                          <span
                            className={cn(
                              "mt-0.5 block text-xs",
                              active ? "text-white/65" : "text-muted-foreground",
                            )}
                          >
                            {disabled ? disabledHint : source.hint}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                {creativeMode === "BRAND_TEMPLATE" ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-muted-foreground">
                      How closely?
                    </span>
                    {(
                      [
                        ["EXACT", "Match it exactly"],
                        ["INSPIRED", "Just take inspiration"],
                      ] as const
                    ).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        aria-pressed={templateFidelity === value}
                        onClick={() => setTemplateFidelity(value)}
                        className={cn(
                          "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                          templateFidelity === value
                            ? "border-primary bg-primary text-black"
                            : "border-border bg-background text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {label}
                      </button>
                    ))}
                    <span className="text-[0.6875rem] text-muted-foreground">
                      {templateFidelity === "EXACT"
                        ? "Same layout, new content."
                        : "Its colours, type and mood — a fresh layout every time."}
                    </span>
                  </div>
                ) : null}
                <button
                  type="button"
                  onClick={() => {
                    setUploadIntention("final");
                    fileInputRef.current?.click();
                  }}
                  className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-foreground underline decoration-primary decoration-2 underline-offset-4"
                >
                  <Upload className="size-4" /> I already have finished media
                </button>
              </div>

              {contentType === "poster" ? (
                <div className="mb-8">
                  <Label className="text-xs tracking-wide uppercase">Image quality</Label>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {QUALITY_TIERS.map((tier) => (
                      <button
                        key={tier.id}
                        type="button"
                        aria-pressed={imageQuality === tier.id}
                        onClick={() => setImageQuality(tier.id)}
                        className={cn(
                          "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                          imageQuality === tier.id
                            ? "border-primary bg-black text-white"
                            : "border-border bg-background text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {tier.label} <span className="opacity-60">· {tier.hint}</span>
                      </button>
                    ))}
                  </div>
                  <p className="mt-1.5 text-[0.6875rem] text-muted-foreground">
                    Better quality uses more of your plan: Ultra counts as 2 generation units
                    and takes a little longer. Standard and High count as 1.
                  </p>
                </div>
              ) : null}

              {/* MODEL & LOGO — the two brand assets that ride every poster,
                  as live controls rather than settings buried elsewhere. */}
              <div className="mb-8 grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-border p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <UserRound className="size-4 shrink-0 text-primary" />
                      <h3 className="truncate text-sm font-semibold text-foreground">
                        Your model
                      </h3>
                    </div>
                    {(ambassadors?.length ?? 0) > 0 ? (
                      <button
                        type="button"
                        role="switch"
                        aria-checked={featureModel}
                        onClick={() => setFeatureModel((v) => !v)}
                        className={cn(
                          "shrink-0 rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                          featureModel
                            ? "border-primary bg-primary text-black"
                            : "border-border text-muted-foreground",
                        )}
                      >
                        {featureModel ? "In this creative" : "Off"}
                      </button>
                    ) : null}
                  </div>
                  <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
                    {(ambassadors ?? []).map((row) => (
                      <img
                        key={row.id}
                        src={row.file_url ?? ""}
                        alt={row.title}
                        title={row.title}
                        className={cn(
                          "size-12 shrink-0 rounded-full border-2 object-cover",
                          featureModel ? "border-primary" : "border-border opacity-50",
                        )}
                      />
                    ))}
                    <button
                      type="button"
                      disabled={ambassadorUploading || !brandId}
                      onClick={() => ambassadorInputRef.current?.click()}
                      className="grid size-12 shrink-0 place-items-center rounded-full border-2 border-dashed border-border text-muted-foreground transition-colors hover:border-primary hover:text-foreground disabled:opacity-50"
                      aria-label="Add a model photo"
                    >
                      {ambassadorUploading ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Plus className="size-4" />
                      )}
                    </button>
                    <input
                      ref={ambassadorInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file || !brandId) return;
                        setAmbassadorUploading(true);
                        uploadBrandAmbassador(brandId, file)
                          .then((row) => {
                            setAmbassadors((prev) => [row as Inspiration, ...(prev ?? [])]);
                            setFeatureModel(true);
                            toast.success("Model photo added — they'll front your creatives.");
                          })
                          .catch((err: unknown) =>
                            toast.error(
                              err instanceof Error ? err.message : "The photo could not be saved.",
                            ),
                          )
                          .finally(() => setAmbassadorUploading(false));
                      }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {(ambassadors?.length ?? 0) > 0
                      ? "The same face fronts every creative. The newest photo is the one used."
                      : "Add your model or brand ambassador once — every poster features them."}
                  </p>
                </div>

                <div className="rounded-xl border border-border p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      {brandKit.logoUrl ? (
                        <img
                          src={brandKit.logoUrl}
                          alt="Brand logo"
                          className="size-6 shrink-0 rounded object-contain"
                        />
                      ) : (
                        <ImageIcon className="size-4 shrink-0 text-primary" />
                      )}
                      <h3 className="truncate text-sm font-semibold text-foreground">Logo</h3>
                    </div>
                    {brandKit.logoUrl ? (
                      <button
                        type="button"
                        role="switch"
                        aria-checked={brandKit.showLogoOnPosters}
                        disabled={brandKitLoading}
                        onClick={() =>
                          updateBrandKit(
                            { showLogoOnPosters: !brandKit.showLogoOnPosters },
                            { immediate: true },
                          )
                        }
                        className={cn(
                          "shrink-0 rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                          brandKit.showLogoOnPosters
                            ? "border-primary bg-primary text-black"
                            : "border-border text-muted-foreground",
                        )}
                      >
                        {brandKit.showLogoOnPosters ? "On posters" : "Off"}
                      </button>
                    ) : null}
                  </div>
                  <p className="mt-3 text-xs text-muted-foreground">
                    {brandKit.logoUrl ? (
                      "Saved with your brand kit — this switch is the same one Brand Master uses. Templates keep their own logo placement."
                    ) : (
                      <>
                        No logo uploaded yet.{" "}
                        <Link
                          to="/brand-master"
                          className="font-medium text-foreground underline underline-offset-2"
                        >
                          Add it in Brand Master
                        </Link>{" "}
                        and it appears here.
                      </>
                    )}
                  </p>
                </div>
              </div>

              {/* CAMPAIGN DETAILS — tap-first: the common occasions and offers
                  are chips, the long tail stays typable. */}
              <div className="mb-2 rounded-xl border border-border bg-secondary/20 p-4">
                <h3 className="text-sm font-semibold text-foreground">Campaign details</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  Optional — tap what fits, type what doesn't. Anything left blank is filled
                  from Brand Master.
                </p>
                <div className="mt-4 space-y-4">
                  <div className="space-y-2">
                    <Label className="text-xs tracking-wide uppercase">Occasion</Label>
                    <div className="flex flex-wrap gap-1.5">
                      {[
                        "Diwali",
                        "Wedding season",
                        "New arrival",
                        "Weekend sale",
                        "Festive offer",
                        "Anniversary",
                      ].map((chip) => (
                        <button
                          key={chip}
                          type="button"
                          aria-pressed={occasion === chip}
                          onClick={() => setOccasion(occasion === chip ? "" : chip)}
                          className={cn(
                            "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                            occasion === chip
                              ? "border-primary bg-primary text-black"
                              : "border-border bg-background text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {chip}
                        </button>
                      ))}
                    </div>
                    <Input
                      value={occasion}
                      onChange={(e) => setOccasion(e.target.value)}
                      placeholder="…or type your own occasion"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs tracking-wide uppercase">Offer</Label>
                    <div className="flex flex-wrap gap-1.5">
                      {["10% off", "20% off", "Buy 1 Get 1", "Free styling session"].map(
                        (chip) => (
                          <button
                            key={chip}
                            type="button"
                            aria-pressed={offer === chip}
                            onClick={() => setOffer(offer === chip ? "" : chip)}
                            className={cn(
                              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                              offer === chip
                                ? "border-primary bg-primary text-black"
                                : "border-border bg-background text-muted-foreground hover:text-foreground",
                            )}
                          >
                            {chip}
                          </button>
                        ),
                      )}
                    </div>
                    <Input
                      value={offer}
                      onChange={(e) => setOffer(e.target.value)}
                      placeholder="…or type the exact offer"
                    />
                  </div>
                  <details>
                    <summary className="cursor-pointer text-xs font-semibold text-muted-foreground hover:text-foreground">
                      More details — campaign name, product, audience, location, tone
                    </summary>
                    <div className="mt-4 grid gap-4 sm:grid-cols-2">
                      <div className="space-y-2">
                        <Label>Campaign / promotion name</Label>
                        <Input
                          value={campaignName}
                          onChange={(e) => setCampaignName(e.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Product or collection</Label>
                        <Input value={product} onChange={(e) => setProduct(e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <Label>Target audience</Label>
                        <Input value={audience} onChange={(e) => setAudience(e.target.value)} />
                      </div>
                      <div className="space-y-2">
                        <Label>Location</Label>
                        <Input value={location} onChange={(e) => setLocation(e.target.value)} />
                      </div>
                      <div className="space-y-2 sm:col-span-2">
                        <Label>Brand tone</Label>
                        <Input value={brandTone} onChange={(e) => setBrandTone(e.target.value)} />
                      </div>
                    </div>
                  </details>
                </div>
              </div>

              {/* VIDEO-ONLY FIELDS */}
              {contentType === "video" && (
                <div className="mt-8 rounded-xl border border-border p-5">
                  <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <Video className="size-4 text-primary" />
                      <h3 className="text-sm font-semibold text-foreground">Video settings</h3>
                    </div>
                    <span className="shrink-0 rounded-full border border-border bg-secondary/60 px-2.5 py-0.5 text-xs text-muted-foreground">
                      Uses your VIDEO route
                    </span>
                  </div>

                  <div className="mt-4 grid gap-5 sm:grid-cols-3">
                    <div className="space-y-2">
                      <Label>Duration</Label>
                      <Select value={videoDuration} onValueChange={setVideoDuration}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {VIDEO_DURATIONS.map((d) => (
                            <SelectItem key={d} value={d}>
                              {d}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Aspect ratio</Label>
                      <Select value={videoAspect} onValueChange={setVideoAspect}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {VIDEO_ASPECTS.map((a) => (
                            <SelectItem key={a} value={a}>
                              {a}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Style</Label>
                      <Select value={videoStyle} onValueChange={setVideoStyle}>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {VIDEO_STYLES.map((s) => (
                            <SelectItem key={s} value={s}>
                              {s}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="mt-5 space-y-2">
                    <Label>Script / voiceover notes (optional)</Label>
                    <Textarea
                      rows={3}
                      placeholder="What should be said or shown, scene by scene."
                      value={videoScript}
                      onChange={(e) => setVideoScript(e.target.value)}
                    />
                  </div>
                </div>
              )}

              {/* CAROUSEL-ONLY FIELDS */}
              {contentType === "carousel" && (
                <div className="mt-8 rounded-xl border border-border p-5">
                  <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Images className="size-4 text-primary" />
                        <h3 className="text-sm font-semibold text-foreground">Carousel slides</h3>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Describe what belongs in each position. Slides are generated and saved in
                        this order.
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full border border-border bg-secondary/60 px-2.5 py-0.5 text-xs text-muted-foreground">
                      {slides.length} slide{slides.length === 1 ? "" : "s"}
                    </span>
                  </div>

                  <div className="mt-4 space-y-3">
                    {slides.map((slide, i) => (
                      <div
                        key={slide.id}
                        className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 rounded-xl border border-border bg-secondary/20 p-3"
                      >
                        {/* No drag handle here: reordering is the Move buttons
                            below, and a grip icon only invited a gesture the
                            list has never supported. */}
                        <div className="flex flex-col items-center gap-1 pt-1">
                          <span className="grid size-7 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                            {i + 1}
                          </span>
                        </div>

                        <div className="min-w-0">
                          <Textarea
                            rows={2}
                            placeholder={slidePlaceholder(i)}
                            value={slide.description}
                            onChange={(e) => updateSlide(slide.id, e.target.value)}
                          />
                          <div className="mt-2 flex flex-wrap items-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              disabled={i === 0}
                              onClick={() => moveSlide(i, -1)}
                            >
                              Move up
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              disabled={i === slides.length - 1}
                              onClick={() => moveSlide(i, 1)}
                            >
                              Move down
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              disabled={slides.length <= 1}
                              onClick={() => removeSlide(slide.id)}
                            >
                              <Trash2 className="size-4" /> Remove
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-4"
                    onClick={addSlide}
                  >
                    <Plus className="size-4" /> Add slide
                  </Button>
                </div>
              )}

              {creativeMode === "REFERENCE" ? (
                <div className="mt-8 rounded-xl border border-dashed border-primary/50 bg-primary/5 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-foreground">
                        Bring your own reference
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {contentType === "poster"
                          ? "Upload an image, paste a public URL, or choose any number of saved references below."
                          : "Upload an image now or choose any number of saved references below."}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          setUploadIntention("reference");
                          fileInputRef.current?.click();
                        }}
                      >
                        <Upload className="size-4" /> Use image now
                      </Button>
                      {contentType === "poster" ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => {
                            setInspirationFlowError(null);
                            setStep("inspiration_form");
                          }}
                        >
                          <ExternalLink className="size-4" /> Save reference &amp; create poster
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : null}

              {creativeMode === "BRAND_TEMPLATE" && brandTemplatesError ? (
                <div
                  role="alert"
                  className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
                >
                  <span>{brandTemplatesError}</span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setTemplatesAttempt((current) => current + 1)}
                  >
                    Retry templates
                  </Button>
                </div>
              ) : creativeMode === "BRAND_TEMPLATE" && brandTemplates === null ? (
                <div
                  role="status"
                  className="mt-5 flex items-center gap-2 rounded-xl border border-border p-4 text-sm text-muted-foreground"
                >
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Loading your
                  templates…
                </div>
              ) : creativeMode === "BRAND_TEMPLATE" &&
                brandTemplates !== null &&
                brandTemplates.length === 0 ? (
                <div
                  role="status"
                  className="mt-5 rounded-xl border border-border p-4 text-sm text-muted-foreground"
                >
                  No templates uploaded yet. Add your poster designs under{" "}
                  <Link
                    to="/brand-master"
                    search={{ tab: "templates" }}
                    className="font-medium text-foreground underline underline-offset-2"
                  >
                    Brand Master → Templates
                  </Link>
                  , or choose “AI original”.
                </div>
              ) : creativeMode === "BRAND_TEMPLATE" || creativeMode === "REFERENCE" ? (
                <CreativeCommand
                  brandId={brandId}
                  selections={creativeSelections}
                  onSelectionsChange={setCreativeSelections}
                  templates={brandTemplates ?? []}
                  templateId={creativeTemplateId}
                  onTemplateChange={setCreativeTemplateId}
                  showTemplates={creativeMode === "BRAND_TEMPLATE"}
                  showReferences={creativeMode === "REFERENCE"}
                />
              ) : null}

              {awaitingApproval ? (
                <div
                  role="status"
                  className="mt-8 flex items-start gap-3 rounded-xl border border-gold/40 bg-gold/10 px-4 py-3 text-sm"
                >
                  <Sparkles className="mt-0.5 size-4 shrink-0 text-gold" />
                  <p>
                    <span className="font-medium text-foreground">Awaiting Scaleezy approval</span>
                    <span className="text-muted-foreground">
                      {" "}
                      — generation unlocks once this client is approved. Everything you write here
                      is kept, so you can set the brief up now.
                    </span>
                  </p>
                </div>
              ) : null}

              {/* On a phone the button rides above the thumb instead of
                  scrolling away below a long form. */}
              <div className="mt-8 flex items-center gap-4 max-sm:sticky max-sm:bottom-3 max-sm:z-20 max-sm:rounded-xl max-sm:border max-sm:border-border max-sm:bg-background/95 max-sm:p-3 max-sm:shadow-lg max-sm:backdrop-blur">
                <Button
                  onClick={() => void handleGenerate()}
                  disabled={
                    !canCreateGeneration({
                      awaitingApproval,
                      pending: generationPending,
                      mode: creativeMode,
                      brief: [creativeBrief, campaignName, product, offer],
                      hasReference: Boolean(referenceImageBase64 || creativeSelections.length),
                      templateId: creativeTemplateId,
                    })
                  }
                  title={
                    awaitingApproval
                      ? "Generation unlocks once Scaleezy approves this client."
                      : undefined
                  }
                  className="gap-2 max-sm:flex-1"
                >
                  <Sparkles className="size-4" />{" "}
                  {generationPending ? "Resume generation" : "Create now"}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setCreativeBrief("");
                    setCreativeMode(null);
                    setCreativeTemplateId("");
                    setCreativeSelections([]);
                    setReferenceImageBase64("");
                  }}
                >
                  Clear
                </Button>
              </div>
            </div>
          </section>
        )}

        {/* STEP 1A: GEMINI GENERATING */}
        {step === "ai_generating" && (
          <section className="surface-card flex min-h-[400px] flex-col items-center justify-center border-primary/30 bg-primary/6 p-12 text-center">
            <Loader2 className="mb-6 size-12 animate-spin text-primary" />
            <h3 className="text-2xl font-semibold text-foreground">AI is working...</h3>
            <p className="mt-3 text-muted-foreground max-w-md text-base">
              {productionProgress || workingMessage}
            </p>
            {workingKind === "generate" ? (
              <Button variant="ghost" className="mt-6" onClick={cancelGeneration}>
                Cancel
              </Button>
            ) : null}
          </section>
        )}

        {/* STEP 1B: MANUAL UPLOAD SELECTION */}
        {step === "manual_upload" && (
          <section className="surface-card p-5 sm:p-8">
            <div className="flex items-center gap-3 mb-6">
              <button
                onClick={() => setStep("ai_form")}
                className="text-muted-foreground hover:text-foreground transition-colors p-2 -ml-2 rounded-full hover:bg-secondary/50"
                aria-label="Go back"
              >
                <ArrowLeft className="size-5" />
              </button>
              <h2 className="text-xl font-semibold tracking-tight text-foreground">
                CHOOSE UPLOAD TYPE
              </h2>
            </div>

            <div className="grid gap-6 sm:grid-cols-2">
              <button
                onClick={() => {
                  setUploadIntention("reference");
                  fileInputRef.current?.click();
                }}
                className="group relative flex flex-col items-center justify-center gap-4 rounded-2xl border border-border bg-card p-8 text-center transition-all hover:border-primary hover:bg-primary/5"
              >
                <div className="flex size-14 items-center justify-center rounded-full bg-primary/10 text-primary shadow-sm group-hover:bg-primary group-hover:text-white transition-colors">
                  <Wand2 className="size-6" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">Reference Image</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Scaleezy will use this image as inspiration and your configured AI routing to
                    generate a new, polished poster.
                  </p>
                </div>
                <div className=" cursor-pointer mt-4 rounded-full bg-background px-6 py-2 text-sm font-medium text-foreground border border-border transition-transform group-hover:scale-105 shadow-sm">
                  Upload Reference
                </div>
              </button>

              <button
                onClick={() => {
                  setUploadIntention("final");
                  fileInputRef.current?.click();
                }}
                className="group relative flex flex-col items-center justify-center gap-4 rounded-2xl border border-border bg-card p-8 text-center transition-all hover:border-green-600 hover:bg-green-600/5"
              >
                <div className="flex size-14 items-center justify-center rounded-full bg-green-600/10 text-green-600 shadow-sm group-hover:bg-green-600 group-hover:text-white transition-colors">
                  <CheckCircle className="size-6" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">Final Ready Poster</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Skip image generation. Have Scaleezy write captions and hashtags for this exact
                    poster.
                  </p>
                </div>
                <div className="cursor-pointer mt-4 rounded-full bg-background px-6 py-2 text-sm font-medium text-foreground border border-border transition-transform group-hover:scale-105 shadow-sm">
                  Upload Final Poster
                </div>
              </button>
            </div>

            <div className="mt-8 flex justify-center">
              <Button variant="ghost" onClick={() => setStep("ai_form")}>
                Cancel
              </Button>
            </div>
          </section>
        )}

        {/* CONTENT PREVIEW & PUBLISHING SETUP */}
        {(step === "preview" || step === "publish_setup") && asset && (
          <div className="space-y-4">
            <button
              onClick={() => {
                setContentLocked(false);
                setSelected([]);
                setAsset(null);
                setStep("ai_form");
              }}
              className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors w-fit p-2 pr-4 -ml-2 rounded-full hover:bg-secondary/50 text-sm font-medium"
            >
              {/* Renamed: this rewinds the wizard to step one. The dashboard
                  link is the one in the page header. */}
              <ArrowLeft className="size-4" /> Start over
            </button>
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
              {/* LEFT: CONTENT PREVIEW */}
              <section className="surface-card p-5 sm:p-8 animate-in fade-in">
                <p className="label-eyebrow text-primary">CONTENT PREVIEW</p>
                {asset.mediaWarning ? (
                  <div
                    role="alert"
                    className="mt-4 rounded-xl border border-amber-400/50 p-4 text-sm"
                  >
                    <strong>Copy saved; image needs attention.</strong> {asset.mediaWarning}
                    {asset.generationId ? (
                      <Button
                        className="mt-3"
                        variant="outline"
                        disabled={retryingImage}
                        onClick={() => void retryMissingImage()}
                      >
                        {retryingImage ? "Retrying image…" : "Retry image only"}
                      </Button>
                    ) : null}
                  </div>
                ) : null}

                {asset.compositionWarning ? (
                  <div
                    role="alert"
                    className="mt-4 rounded-xl border border-amber-400/50 bg-amber-50 px-4 py-3 text-sm text-amber-950"
                  >
                    <strong>Template needs attention.</strong> {asset.compositionWarning} Choose a
                    template below to finish the poster; no AI generation was repeated.
                  </div>
                ) : null}

                <div className="mt-4 rounded-xl border border-border overflow-hidden bg-background">
                  <div
                    className={cn(
                      "group relative flex items-end overflow-hidden bg-secondary p-6",
                      asset.previewUrl ? "h-auto min-h-[280px]" : "h-64",
                    )}
                  >
                    {asset.previewUrl ? (
                      asset.contentType === "video" ? (
                        <video
                          src={asset.previewUrl}
                          controls
                          className="absolute inset-0 h-full w-full object-contain bg-black"
                        />
                      ) : (
                        <PosterPreviewLightbox previewUrl={asset.previewUrl} />
                      )
                    ) : (
                      <p className="relative z-10 font-display text-3xl text-white mix-blend-overlay">
                        {asset.campaign}
                      </p>
                    )}
                  </div>

                  <div className="p-6">
                    {asset.source === "ai" ? (
                      <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/8 px-3 py-1.5 text-xs font-semibold text-foreground">
                        {activeInspirationGeneration ? (
                          <>
                            <Wand2 className="size-3.5" /> Created from inspiration
                          </>
                        ) : (
                          <>
                            <Sparkles className="size-3.5" /> Generated with AI
                          </>
                        )}
                      </div>
                    ) : (
                      <div className="inline-flex items-center gap-2 rounded-full bg-secondary px-3 py-1.5 text-xs font-medium text-muted-foreground mb-5">
                        <Upload className="size-3.5" /> Uploaded manually
                      </div>
                    )}

                    <div className="flex items-start gap-4 mb-6">
                      <div className="rounded-lg bg-secondary p-3 text-muted-foreground">
                        <FileImage className="size-8" />
                      </div>
                      <div>
                        <h3 className="font-semibold text-lg text-foreground">{asset.name}</h3>
                        <p className="text-sm text-muted-foreground mt-1">
                          {asset.type} • {asset.dimensions} • {asset.created}
                        </p>
                      </div>
                    </div>

                    <div className="space-y-4 pt-4 border-t border-border">
                      <div className="space-y-2">
                        <Label htmlFor="content-post-title">Post Title</Label>
                        <Input
                          id="content-post-title"
                          value={asset.postTitle}
                          disabled={contentLocked}
                          onChange={(e) => setAsset({ ...asset, postTitle: e.target.value })}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="content-post-caption">Post Description / Caption</Label>
                        <Textarea
                          id="content-post-caption"
                          rows={4}
                          value={asset.postDescription}
                          disabled={contentLocked}
                          onChange={(e) => setAsset({ ...asset, postDescription: e.target.value })}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="content-post-hashtags">Hashtags</Label>
                        <Input
                          id="content-post-hashtags"
                          value={asset.postHashtags}
                          disabled={contentLocked}
                          onChange={(e) => setAsset({ ...asset, postHashtags: e.target.value })}
                        />
                      </div>
                    </div>

                    {/* CAROUSEL SLIDE ORDER */}
                    {asset.contentType === "carousel" && asset.slides?.length ? (
                      <div className="mt-6 border-t border-border pt-6">
                        <div className="flex items-center gap-2">
                          <Images className="size-4 text-primary" />
                          <h4 className="text-sm font-semibold text-foreground">
                            Slide order ({asset.slides.length})
                          </h4>
                        </div>
                        <ol className="mt-3 space-y-2">
                          {asset.slides.map((slide, i) => (
                            <li
                              key={slide.id}
                              className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 rounded-xl border border-border bg-secondary/20 p-3"
                            >
                              {slide.previewUrl ? (
                                <img
                                  src={slide.previewUrl}
                                  alt={`Slide ${i + 1}`}
                                  loading="lazy"
                                  decoding="async"
                                  className="size-12 shrink-0 rounded-lg border border-border object-cover"
                                />
                              ) : (
                                <span className="grid size-12 shrink-0 place-items-center rounded-lg bg-primary/10 text-sm font-semibold text-foreground">
                                  {i + 1}
                                </span>
                              )}
                              <div className="min-w-0 space-y-2">
                                <Textarea
                                  rows={2}
                                  disabled={contentLocked}
                                  value={slide.description}
                                  onChange={(event) => {
                                    const description = event.target.value;
                                    setAsset((current) => {
                                      if (!current?.slides) return current;
                                      return {
                                        ...current,
                                        slides: current.slides.map((candidate) =>
                                          candidate.id === slide.id
                                            ? { ...candidate, description }
                                            : candidate,
                                        ),
                                      };
                                    });
                                  }}
                                />
                                {!contentLocked && asset.contentItemId ? (
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    disabled={retryingSlide !== null}
                                    onClick={() => void regenerateSlide(i + 1)}
                                  >
                                    {retryingSlide === i + 1 ? (
                                      <Loader2 className="size-4 animate-spin" />
                                    ) : (
                                      <RefreshCw className="size-4" />
                                    )}
                                    Retry only this slide
                                  </Button>
                                ) : null}
                              </div>
                            </li>
                          ))}
                        </ol>
                      </div>
                    ) : null}

                    {asset.contentType === "poster" &&
                    asset.source === "ai" &&
                    asset.contentItemId &&
                    !contentLocked ? (
                      <PosterStudio
                        contentItemId={asset.contentItemId}
                        layouts={layoutCatalogue.layouts}
                        sizes={layoutCatalogue.sizes}
                        onRendered={() => void refreshComposedPoster()}
                      />
                    ) : null}

                    {!contentLocked ? (
                      <div className="flex flex-wrap gap-2 pt-6 mt-6 border-t border-border">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setStep(
                              asset.source === "ai"
                                ? activeInspirationGeneration
                                  ? "inspiration_form"
                                  : "ai_form"
                                : "manual_upload",
                            )
                          }
                        >
                          <Edit3 className="mr-2 size-4" /> Edit / Replace Media
                        </Button>
                        {asset.source === "ai" && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void handleRegenerateAll()}
                          >
                            <RefreshCw className="mr-2 size-4" /> Regenerate All
                          </Button>
                        )}
                      </div>
                    ) : (
                      <p className="mt-6 rounded-xl border border-emerald-500/25 bg-emerald-500/8 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
                        This is the approved version. Its copy and media are locked while
                        publishing.
                      </p>
                    )}
                  </div>
                </div>

                {step === "preview" && !contentLocked && (
                  <div className="mt-8 grid gap-3 sm:grid-cols-2">
                    <Button
                      variant="outline"
                      className="h-12"
                      disabled={contentSaving || retryingImage}
                      onClick={() => void saveContentDraft()}
                    >
                      {contentSaving ? <Loader2 className="size-4 animate-spin" /> : null}
                      Save draft
                    </Button>
                    <Button
                      className="h-12"
                      disabled={contentSaving || retryingImage || Boolean(asset.mediaWarning)}
                      onClick={() => void saveContentDraft({ submit: true })}
                    >
                      {contentSaving ? <Loader2 className="size-4 animate-spin" /> : null}
                      Submit for review
                    </Button>
                  </div>
                )}
              </section>

              {/* RIGHT: SELECT SOCIAL ACCOUNTS
                  Shown at preview too, disabled, rather than appearing only
                  after a round-trip through Review. The path was invisible:
                  `publish_setup` is reachable solely via a URL parameter, so
                  somebody on the Publishing page could not see that
                  publishing existed, let alone what unlocks it. */}
              {step === "preview" && (
                <section className="surface-card p-5 opacity-70 sm:p-8">
                  <p className="label-eyebrow text-primary">SELECT WHERE TO PUBLISH</p>
                  <p className="mt-4 rounded-xl border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
                    Submit this for review first. Once it is approved, publishing unlocks here.
                  </p>
                </section>
              )}
              {step === "publish_setup" && (
                <section className="surface-card p-5 sm:p-8 animate-in fade-in slide-in-from-bottom-4">
                  <p className="label-eyebrow text-primary">SELECT WHERE TO PUBLISH</p>
                  <div className="mt-4 space-y-2">
                    {accountsLoading ? (
                      <p className="flex items-center gap-2 rounded-xl border border-dashed border-border px-3 py-6 text-sm text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" /> Loading your connected accounts…
                      </p>
                    ) : accounts.length === 0 ? (
                      <p className="rounded-xl border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
                        No social accounts connected yet. Connect one first and it will appear here.
                      </p>
                    ) : (
                      accounts.map((acc) => {
                        const isYoutube = acc.platform === "YOUTUBE";
                        const isFormatMismatch = isYoutube && !isVideoAsset;
                        const publishingOff =
                          (acc.publishing_enabled ?? acc.publishingEnabled) === false;

                        const disabled = !canPublishTo(acc, isVideoAsset);
                        return (
                          <label
                            key={acc.id}
                            className={cn(
                              "grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-3",
                              selected.includes(acc.id) && "border-primary bg-primary/5",
                              disabled && "opacity-60 cursor-not-allowed",
                            )}
                            title={
                              isFormatMismatch
                                ? "YouTube only supports video uploads"
                                : publishingOff
                                  ? "Publishing is switched off for this account"
                                  : ""
                            }
                          >
                            <Checkbox
                              checked={selected.includes(acc.id)}
                              disabled={disabled}
                              onCheckedChange={() => toggle(acc.id)}
                            />
                            <PlatformIcon platform={acc.platform} className="size-9" />
                            <span className="min-w-0">
                              <span className="block truncate text-sm font-medium text-foreground">
                                {acc.account_name || acc.username || "Connected account"}
                              </span>
                              <span className="block truncate text-xs text-muted-foreground">
                                {acc.username}
                                {isFormatMismatch && (
                                  <span className="ml-2 text-destructive text-[10px] font-semibold uppercase">
                                    Video Only
                                  </span>
                                )}
                                {publishingOff && (
                                  <span className="ml-2 text-destructive text-[10px] font-semibold uppercase">
                                    Publishing Off
                                  </span>
                                )}
                              </span>
                            </span>
                            <StatusBadge status={acc.status} className="justify-self-end" />
                          </label>
                        );
                      })
                    )}
                  </div>

                  <p className="mt-3 text-sm text-muted-foreground">
                    Need to connect a new account? Go to the Social Media Accounts tab.
                  </p>

                  <p className="label-eyebrow mt-10 text-primary">CHOOSE TIMING</p>
                  <div className="mt-4 flex gap-2">
                    {(["now", "schedule"] as const).map((m) => (
                      <Button
                        key={m}
                        variant={mode === m ? "default" : "outline"}
                        onClick={() => setMode(m)}
                      >
                        {m === "now" ? "Publish Now" : "Schedule"}
                      </Button>
                    ))}
                  </div>
                  {mode === "schedule" ? (
                    <div className="mt-4 grid gap-3 sm:grid-cols-3">
                      <div>
                        <Label className="text-xs tracking-wide uppercase">Date</Label>
                        <Input
                          type="date"
                          className="mt-1.5"
                          value={scheduleDate}
                          onChange={(e) => setScheduleDate(e.target.value)}
                        />
                      </div>
                      <div>
                        <Label className="text-xs tracking-wide uppercase">Time</Label>
                        <Input
                          type="time"
                          className="mt-1.5"
                          value={scheduleTime}
                          onChange={(e) => setScheduleTime(e.target.value)}
                        />
                      </div>
                      <p className="self-end pb-2 text-xs text-muted-foreground">
                        In your local time zone ({Intl.DateTimeFormat().resolvedOptions().timeZone}
                        ).
                      </p>
                    </div>
                  ) : null}

                  <p className="mt-4 text-xs text-muted-foreground">
                    Only connected accounts with publishing enabled can be selected.
                  </p>

                  <Button
                    className="mt-8 w-full h-14 text-lg bg-primary hover:bg-primary/90 text-primary-foreground"
                    disabled={!selected.length || running}
                    onClick={() => runJobs(selected)}
                  >
                    <Send className="mr-2 size-5" />
                    PUBLISH TO SELECTED PLATFORMS
                  </Button>
                </section>
              )}
            </div>
          </div>
        )}
      </div>

      {/* PUBLISHING HISTORY */}
      <section className="mt-12">
        <SectionTitle title="RECENT PUBLISHING ACTIVITY" />
        <div className="surface-card overflow-hidden mt-4">
          <div className="hidden overflow-x-auto lg:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs tracking-wide text-muted-foreground uppercase">
                  {[
                    "Content",
                    "Platform",
                    "Account",
                    "Published/Scheduled At",
                    "Status",
                    "Post ID",
                    "Error",
                    "",
                  ].map((h) => (
                    <th key={h} className="px-4 py-3 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {historyLoading || publishingHistory.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-sm text-muted-foreground">
                      {historyLoading
                        ? "Loading recent activity…"
                        : historyError
                          ? "Could not load your publishing activity. Refresh to try again."
                          : "Nothing published yet. Your posts will be listed here."}
                    </td>
                  </tr>
                ) : null}
                {publishingHistory.map((row, i) => (
                  <tr key={i} className="border-b border-border/70 last:border-0">
                    <td className="max-w-[240px] px-4 py-3 font-medium">
                      <span className="flex items-center gap-2">
                        {row.previewUrl ? (
                          <img
                            src={row.previewUrl}
                            alt=""
                            loading="lazy"
                            className="size-8 shrink-0 rounded border border-border object-cover"
                          />
                        ) : null}
                        <span className="truncate">{row.content}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3">{row.platform}</td>
                    <td className="px-4 py-3">{row.account}</td>
                    <td className="px-4 py-3 whitespace-nowrap">{row.date}</td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        status={row.status}
                        tone={
                          row.status === "Published"
                            ? "success"
                            : row.status === "Failed"
                              ? "danger"
                              : "neutral"
                        }
                      />
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{row.postId}</td>
                    <td className="max-w-[220px] truncate px-4 py-3 text-muted-foreground">
                      {row.error}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {row.status === "Failed" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={retrying === row.id}
                          onClick={() => retryItem(row.id)}
                        >
                          <RotateCcw className="size-4" />
                          {retrying === row.id ? "Retrying…" : "Retry"}
                        </Button>
                      ) : row.status === "Published" && row.url ? (
                        <Button size="sm" variant="ghost" asChild>
                          <a href={row.url} target="_blank" rel="noreferrer">
                            <ExternalLink className="size-4" /> View
                          </a>
                        </Button>
                      ) : row.status === "Published" ? (
                        <span className="text-xs text-muted-foreground">Published</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          <Clock className="mr-1 inline size-3" /> Waiting
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="divide-y divide-border lg:hidden">
            {historyLoading || publishingHistory.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">
                {historyLoading
                  ? "Loading recent activity…"
                  : historyError
                    ? "Could not load your publishing activity. Refresh to try again."
                    : "Nothing published yet. Your posts will be listed here."}
              </p>
            ) : null}
            {publishingHistory.map((row, i) => (
              <div key={i} className="p-4">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-foreground">
                    {row.content}
                  </p>
                  <StatusBadge
                    status={row.status}
                    tone={
                      row.status === "Published"
                        ? "success"
                        : row.status === "Failed"
                          ? "danger"
                          : "neutral"
                    }
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {row.platform} · {row.account} · {row.date}
                </p>
                {/* error_message is null on everything that did not fail, and
                    null !== "—" put an empty red line on every card. */}
                {row.error ? <p className="mt-2 text-xs text-destructive">{row.error}</p> : null}
              </div>
            ))}
          </div>
          {historyHasMore ? (
            <div className="border-t border-border p-3 text-center">
              <Button
                size="sm"
                variant="outline"
                disabled={historyLoadingMore}
                onClick={() => void loadMoreHistory()}
              >
                {historyLoadingMore ? "Loading…" : "Load more"}
              </Button>
            </div>
          ) : null}
        </div>
      </section>

      {/* Hidden file input always available globally */}
      <input
        type="file"
        className="hidden"
        ref={fileInputRef}
        onChange={handleFileUpload}
        accept="image/*,video/mp4"
      />
    </div>
  );
}

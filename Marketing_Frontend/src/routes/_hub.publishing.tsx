import { createFileRoute } from "@tanstack/react-router";
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
  Phone,
  Plus,
  Trash2,
  Video,
  BookOpen,
  Palette,
  Layers,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
import { cn } from "@/lib/utils";
import { useBrandSettings } from "@/lib/brand-settings";
import { api, apiFetch, apiPost } from "@/lib/api";
import { readSelectedWorkspaceId } from "@/lib/workspace";

export const Route = createFileRoute("/_hub/publishing")({
  head: () => ({
    meta: [
      { title: "Publishing — Scaleezy Marketing Hub" },
      {
        name: "description",
        content:
          "Create or upload your marketing content, select your social channels, and publish everywhere from one place.",
      },
      { property: "og:title", content: "Publishing — Scaleezy Marketing Hub" },
      {
        property: "og:description",
        content: "Independent publishing jobs per platform with retry for failed channels only.",
      },
    ],
  }),
  component: PublishingPage,
});

type WorkflowStep =
  | "create_or_upload"
  | "ai_form"
  | "ai_generating"
  | "manual_upload"
  | "preview"
  | "publish_setup";

/** What the AI is asked to produce. Drives the extra fields on the brief. */
type ContentType = "poster" | "video" | "carousel";

/** One carousel slide. `description` is the brief for that specific position. */
interface CarouselSlide {
  id: string;
  description: string;
  previewUrl?: string | undefined;
}

interface DraftAsset {
  id?: string | undefined;
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
}

interface PublishingHistoryRow {
  id: string;
  content: string;
  platform: string;
  account: string;
  date: string;
  url?: string | undefined;
  status: string;
  postId?: string | undefined;
  error?: string | undefined;
}

const CONTENT_TYPES: {
  id: ContentType;
  label: string;
  hint: string;
  icon: typeof ImageIcon;
  available: boolean;
}[] = [
  {
    id: "poster",
    label: "Poster",
    hint: "A single still image",
    icon: ImageIcon,
    available: true,
  },
  {
    // No adapter implements Capability.VIDEO - apps/ai/adapters/base.py declares
    // generate_video and nothing overrides it - so the video branch reached the
    // same text-and-poster call as everything else and the result was a still
    // image named .mp4. Offered as a roadmap tile, not as a capability.
    id: "video",
    label: "Video",
    hint: "Not available yet",
    icon: Video,
    available: false,
  },
  {
    id: "carousel",
    label: "Carousel",
    hint: "Multiple ordered slides",
    icon: Images,
    available: true,
  },
];

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

function useSessionState<T>(key: string, initialValue: T): [T, (val: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => {
    try {
      const item = sessionStorage.getItem(key);
      return item ? JSON.parse(item) : initialValue;
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback((value: T | ((prev: T) => T)) => {
    setState((prevState) => {
      const nextValue = value instanceof Function ? value(prevState) : value;
      try {
        sessionStorage.setItem(key, JSON.stringify(nextValue));
      } catch (e) {
        console.warn("Failed to save state to sessionStorage", e);
      }
      return nextValue;
    });
  }, [key]);

  return [state, setValue];
}

function PublishingPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useSessionState<WorkflowStep>("pub_step", "create_or_upload");
  const [asset, setAsset] = useSessionState<DraftAsset | null>("pub_asset", null);
  const [contentSaving, setContentSaving] = useState(false);
  const [contentLocked, setContentLocked] = useState(false);
  const [showFullImage, setShowFullImage] = useState(false);
  const [referenceImageBase64, setReferenceImageBase64] = useSessionState<string>("pub_ref_img", "");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [uploadIntention, setUploadIntention] = useState<"reference" | "final" | null>(null);
  const [isGeneratingCaptions, setIsGeneratingCaptions] = useState(false);
  // Three different flows share the "AI is working" step; without this the
  // panel told a video uploader we were analysing their image.
  const [workingKind, setWorkingKind] = useState<WorkingKind>("generate");
  // Lets the user stop waiting on a queued generation, which otherwise holds
  // the screen for the full ten-minute polling ceiling.
  const generationAbort = useRef<AbortController | null>(null);

  // Recovery effect for transient state loss
  useEffect(() => {
    if (step === "ai_generating") {
      setStep("ai_form");
    }
  }, []);

  // AI brief state
  const [campaignName, setCampaignName] = useSessionState("pub_campaign", "");
  const [product, setProduct] = useSessionState("pub_product", "");
  const [audience, setAudience] = useSessionState("pub_audience", "");
  const [location, setLocation] = useSessionState("pub_location", "");
  const [occasion, setOccasion] = useSessionState("pub_occasion", "");
  const [offer, setOffer] = useSessionState("pub_offer", "");
  const [brandTone, setBrandTone] = useSessionState("pub_tone", "");
  const [customInstructions, setCustomInstructions] = useSessionState("pub_custom", "");

  // What to generate, plus the per-type extras
  const [contentType, setContentType] = useSessionState<ContentType>("pub_contentType", "poster");
  const [videoDuration, setVideoDuration] = useSessionState("pub_videoDur", VIDEO_DURATIONS[1]!);
  const [videoAspect, setVideoAspect] = useSessionState("pub_videoAsp", VIDEO_ASPECTS[0]!);
  const [videoStyle, setVideoStyle] = useSessionState("pub_videoStyle", VIDEO_STYLES[0]!);
  const [videoScript, setVideoScript] = useSessionState("pub_videoScript", "");
  const [slides, setSlides] = useSessionState<CarouselSlide[]>("pub_slides", [newSlide(), newSlide(), newSlide()]);

  // Poster add-ons, defaulted from the workspace brand kit
  const { settings: brand } = useBrandSettings();
  const [includeLogo, setIncludeLogo] = useState(false);
  const [includePhone, setIncludePhone] = useState(false);
  const [phoneOverride, setPhoneOverride] = useState("");

  // Adopt the brand-kit defaults once they load from storage
  useEffect(() => {
    setIncludeLogo(brand.showLogoOnPosters);
    setIncludePhone(brand.showPhoneOnPosters);
    setPhoneOverride(brand.phoneNumber);
  }, [brand.showLogoOnPosters, brand.showPhoneOnPosters, brand.phoneNumber]);

  // Auto-populate AI form with Brand Master context
  useEffect(() => {
    if (brand.brandTone && !brandTone) setBrandTone(brand.brandTone);
    if (brand.location && !location) setLocation(brand.location);
    if (brand.audience && !audience) setAudience(brand.audience);
    if (!campaignName && brand.name) setCampaignName(`${brand.name} Spotlight`);
  }, [brand.brandTone, brand.location, brand.audience, brand.name]);

  const fillFromBrandMaster = () => {
    if (brand.brandTone) setBrandTone(brand.brandTone);
    if (brand.location) setLocation(brand.location);
    if (brand.audience) setAudience(brand.audience);
    if (brand.ctaKeyword || brand.tagline) setOffer(brand.ctaKeyword || brand.tagline);
    if (brand.name) setCampaignName(`${brand.name} Spotlight`);
    if (brand.productsServices && brand.productsServices.length > 0 && brand.productsServices[0]) {
      setProduct(brand.productsServices[0].name || "");
    }
    toast.success("Loaded all details from Brand Master!");
  };

  const hasLogo = !!brand.logoUrl;

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
  const [retrying, setRetrying] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<PublishingAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);

  const loadHistory = useCallback(async () => {
    try {
      const res = await apiFetch("/api/marketing/publishing/jobs/");
      const data = await res.json();
      if (!Array.isArray(data)) {
        setHistoryError(true);
        return;
      }
      const historyRows: PublishingHistoryRow[] = [];
      (data as PublishingJobDto[]).forEach((job) => {
        (job.items ?? []).forEach((item) => {
          historyRows.push({
            id: item.id,
            content: "Generated Marketing Post", // No text on asset currently, fallback
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
      setPublishingHistory(historyRows);
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

  useEffect(() => {
    // Fetch connected accounts for publishing
    apiFetch("/api/marketing/social-accounts/")
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setAccounts(data);
        }
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
          throw new Error(`Content is ${item.status.replaceAll("_", " ").toLowerCase()}, not approved.`);
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

  const ensureDraftAsset = async (draft: DraftAsset): Promise<string> => {
    if (draft.id) return draft.id;
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
      return String(payload.data.id);
    }

    const saved = await api<{ id: string }>("/api/marketing/assets/", {
      method: "POST",
      body: {
        file_name: draft.name || "content-media",
        file_url: draft.previewUrl,
        asset_type: draft.contentType === "video" ? "VIDEO" : "IMAGE",
        source: draft.source === "ai" ? "AI_GENERATED" : "MANUAL_UPLOAD",
      },
    });
    if (!saved.id) throw new Error("The media was saved without an id.");
    return saved.id;
  };

  const saveContentDraft = async ({ submit = false }: { submit?: boolean } = {}) => {
    if (!asset || contentLocked) return;
    setContentSaving(true);
    try {
      const assetId = await ensureDraftAsset(asset);
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
        preview_url: asset.previewUrl ?? "",
        slides: (asset.slides ?? []).map((slide, index) => ({
          position: index + 1,
          description: slide.description,
          preview_url: slide.previewUrl ?? "",
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
      } else {
        toast.error(data.message || "Failed to publish.");
      }
    } catch (err: unknown) {
      console.error(err);
      toast.error(err instanceof Error ? err.message : "Network error while publishing.");
    } finally {
      setRunning(false);
      await loadHistory();
      setStep("create_or_upload");
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
      const request = json.data ?? json;

      if (request?.status === "FAILED") {
        throw new Error(request.error_message || "Generation failed.");
      }
      if (request?.status !== "COMPLETED") continue;

      const resultRes = await apiFetch(`/api/marketing/ai-generation/${generationId}/results/`, {
        signal,
      });
      const resultJson = await resultRes.json();
      const result = resultJson.data ?? {};
      const metadata = result.metadata ?? {};

      return {
        postTitle: metadata.postTitle ?? "",
        postDescription: result.generated_text ?? "",
        postHashtags: metadata.postHashtags ?? "",
        posterImageUrl: result.generated_asset_url ?? "",
        metadata,
        contentItemId: metadata.contentItemId ?? null,
        assetId: metadata.assetId ?? null,
      };
    }

    throw new Error("Generation is taking longer than expected. Check back shortly.");
  };

  /** Stops the wait. Anything already queued keeps running on the server. */
  const cancelGeneration = () => {
    generationAbort.current?.abort();
  };

  const handleGenerate = async () => {
    const controller = new AbortController();
    generationAbort.current = controller;
    setWorkingKind("generate");
    setStep("ai_generating");
    try {
      // Video and multi-slide carousels run long enough to hit a gateway
      // timeout on the synchronous endpoint, and when they do the work is
      // lost even if the server finished it. Those go on the queue and are
      // polled; a poster still comes back in one request.
      const background = contentType === "video" || contentType === "carousel";
      const endpoint = background
        ? "/api/marketing/ai-generation/generate-async/"
        : "/api/marketing/ai-generation/generate/";

      const res = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          campaignName,
          product,
          audience,
          location,
          occasion,
          offer,
          brandTone,
          custom_instructions: customInstructions,
          referenceImageBase64,
          contentType,
          includeLogo: includeLogo && hasLogo,
          includePhone: includePhone,
          phoneNumber: phoneOverride || brand.phoneNumber || brand.contactPhone || "",
          ...(contentType === "carousel"
            ? {
                slides: slides.map((s, i) => ({
                  position: i + 1,
                  description: s.description.trim() || slidePlaceholder(i),
                })),
              }
            : {}),
        }),
      });
      const json = await res.json();
      if (!json.success) {
        throw new Error(json.message || "Generation failed");
      }
      const d = background
        ? await pollGeneration(json.data.generationId, controller.signal)
        : json.data;

      // The backend returns one image today. For a carousel, keep the ordered
      // slide plan and attach any per-slide images it does send back.
      const returnedSlides: string[] = Array.isArray(d.slideImageUrls) ? d.slideImageUrls : [];

      // Only poster and carousel can be generated, so the produced file is
      // always a still. Naming it .mp4 was the last place the UI still claimed
      // a clip had been made.
      const label = contentType === "carousel" ? "Carousel" : "Poster";

      setAsset({
        id: d.assetId || undefined,
        name: `${campaignName || "Untitled"} ${label}.jpg`,
        type: "JPG",
        dimensions:
          contentType === "carousel" ? `1080×1080 · ${slides.length} slides` : "1080×1350",
        created: new Date().toLocaleDateString("en-GB", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        }),
        source: "ai",
        contentType,
        campaign: campaignName,
        tone: "from-[#F7F3EE] to-[#7C3AED]/20",
        postTitle: d.postTitle || `${campaignName} Announcement`,
        postDescription: d.postDescription || "",
        postHashtags: d.postHashtags || "",
        previewUrl: d.posterImageUrl || d.videoUrl || undefined,
        // Row the backend persisted for this generation; sent on publish
        // so the approval gate can be enforced.
        contentItemId: d.contentItemId || undefined,
        ...(contentType === "carousel"
          ? {
              slides: slides.map((s, i) => ({
                ...s,
                description: s.description.trim() || slidePlaceholder(i),
                previewUrl: returnedSlides[i],
              })),
            }
          : {}),
      });
      setStep("preview");
    } catch (err: unknown) {
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
      generationAbort.current = null;
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
          tone: "from-blue-500/20 to-purple-500/20",
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
        setStep("create_or_upload");
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
            tone: "from-blue-500/20 to-purple-500/20",
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
          setStep("create_or_upload");
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
        : referenceImageBase64
          ? "Analysing your reference image to craft the marketing asset."
          : `Drafting your ${contentType} from the campaign brief.`;

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Publishing"
        subtitle="Create or upload your marketing content, select your social channels, and publish everywhere from one place."
        backTo="/"
      />

      <div className="grid gap-6">
        {/* STEP 1: CREATE OR UPLOAD */}
        {step === "create_or_upload" && (
          <section className="surface-card p-5 sm:p-8">
            <h2 className="mb-6 text-xl font-semibold tracking-tight text-foreground">
              CREATE YOUR CONTENT
            </h2>

            <div className="grid gap-6 sm:grid-cols-2">
              <button
                onClick={() => {
                  setReferenceImageBase64("");
                  setStep("ai_form");
                }}
                className="group relative flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-[#7C3AED]/20 bg-[#F7F3EE] p-8 text-center transition-all hover:border-[#7C3AED] hover:shadow-md"
              >
                <div className="flex size-14 items-center justify-center rounded-full bg-[#7C3AED] text-white shadow-lg">
                  <Sparkles className="size-6" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-[#7C3AED]">✨ Generate with AI</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Create marketing content using AI.
                  </p>
                </div>
                <div className="mt-4 rounded-full bg-[#7C3AED] px-6 py-2 text-sm font-medium text-white transition-transform group-hover:scale-105 shadow-sm">
                  Generate Content
                </div>
              </button>

              <button
                onClick={() => setStep("manual_upload")}
                className="group relative flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-border bg-secondary/30 p-8 text-center transition-all hover:border-primary/50 hover:bg-secondary/50"
              >
                <div className="flex size-14 items-center justify-center rounded-full bg-background text-muted-foreground shadow-sm group-hover:text-primary">
                  <Upload className="size-6" />
                </div>
                <div>
                  <h3 className="text-lg  font-semibold text-foreground">
                    ↑ Upload Media (Image / Video)
                  </h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Upload a reference image or a final ready media file.
                  </p>
                </div>
                <div className="cursor-pointer mt-4 rounded-full bg-background px-6 py-2 text-sm font-medium text-foreground border border-border transition-transform group-hover:scale-105 shadow-sm">
                  Upload Media
                </div>
              </button>
            </div>
          </section>
        )}

        {/* STEP 1A: GEMINI FORM */}
        {step === "ai_form" && (
          <section className="surface-card overflow-hidden">
            <div className="border-b border-[#7C3AED]/10 bg-[#F7F3EE] p-5 sm:px-8 sm:py-6">
              <div className="flex items-center gap-4">
                <button
                  onClick={() => setStep("create_or_upload")}
                  className="text-[#7C3AED]/70 hover:text-[#7C3AED] transition-colors p-2 -ml-2 rounded-full hover:bg-white/50"
                  aria-label="Go back"
                >
                  <ArrowLeft className="size-5" />
                </button>
                <div className="flex size-12 items-center justify-center rounded-xl bg-[#7C3AED] text-white shadow-sm">
                  <Sparkles className="size-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-semibold tracking-tight text-[#7C3AED]">
                    GENERATE WITH AI
                  </h2>
                  <p className="text-xs font-semibold tracking-widest text-[#7C3AED]/70 uppercase mt-1">
                    POWERED BY AI
                  </p>
                </div>
              </div>
            </div>

            <div className="p-5 sm:p-8">
              {/* Brand Master Intelligence Connected Banner */}
              <div className="mb-6 rounded-2xl border border-[#7C3AED]/20 bg-gradient-to-br from-[#7C3AED]/5 via-[#F7F3EE] to-white p-4 sm:p-5 shadow-sm">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-[#7C3AED]/10 pb-3.5">
                  <div className="flex items-center gap-2.5">
                    <div className="flex size-8 items-center justify-center rounded-lg bg-[#7C3AED] text-white shadow-xs">
                      <BookOpen className="size-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                        Brand Master Intelligence Connected
                        <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20 text-[10px] px-1.5 py-0">
                          Active
                        </Badge>
                      </h3>
                      <p className="text-xs text-muted-foreground">
                        Scaleezy automatically injects your Brand Master identity, tone, and visual guidelines into this generation.
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={fillFromBrandMaster}
                    className="shrink-0 h-8 text-xs border-[#7C3AED]/30 text-[#7C3AED] hover:bg-[#7C3AED]/10"
                  >
                    <Sparkles className="size-3.5 mr-1 text-[#7C3AED]" /> Auto-fill with Brand Master
                  </Button>
                </div>

                {/* Brand Points Summary */}
                <div className="mt-3.5 flex flex-wrap items-center gap-2 text-xs">
                  {brand.name && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-white dark:bg-card px-2.5 py-1 border border-border/80 text-foreground font-medium shadow-xs">
                      <span className="text-muted-foreground font-normal">Brand:</span> {brand.name}
                    </span>
                  )}
                  {brand.industry && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-white dark:bg-card px-2.5 py-1 border border-border/80 text-foreground font-medium shadow-xs">
                      <span className="text-muted-foreground font-normal">Industry:</span> {brand.industry}
                    </span>
                  )}
                  {brand.brandTone && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-white dark:bg-card px-2.5 py-1 border border-border/80 text-foreground font-medium shadow-xs">
                      <span className="text-muted-foreground font-normal">Tone:</span> {brand.brandTone}
                    </span>
                  )}
                  {brand.location && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-white dark:bg-card px-2.5 py-1 border border-border/80 text-foreground font-medium shadow-xs">
                      <span className="text-muted-foreground font-normal">Location:</span> {brand.location}
                    </span>
                  )}
                  {brand.tagline && (
                    <span className="inline-flex items-center gap-1 rounded-md bg-white dark:bg-card px-2.5 py-1 border border-border/80 text-foreground font-medium shadow-xs max-w-xs truncate">
                      <span className="text-muted-foreground font-normal">Tagline:</span> {brand.tagline}
                    </span>
                  )}
                  {brand.palette && Object.keys(brand.palette).length > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-md bg-white dark:bg-card px-2.5 py-1 border border-border/80 text-foreground font-medium shadow-xs">
                      <Palette className="size-3 text-muted-foreground" />
                      <span className="text-muted-foreground font-normal">Palette:</span>
                      <span className="flex items-center gap-1">
                        {Object.entries(brand.palette).slice(0, 3).map(([role, col]) => (
                          <span
                            key={role}
                            className="size-3 rounded-full border border-black/10 shadow-xs inline-block"
                            style={{ backgroundColor: col }}
                            title={`${role}: ${col}`}
                          />
                        ))}
                      </span>
                    </span>
                  )}
                </div>
              </div>

              {referenceImageBase64 && (
                <div className="mb-6 flex items-start gap-4 p-4 rounded-xl border border-[#7C3AED]/20 bg-[#7C3AED]/5">
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
                <Label className="text-xs tracking-wide uppercase font-semibold text-muted-foreground">What should we create?</Label>
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  {CONTENT_TYPES.map((ct) => {
                    const active = contentType === ct.id;
                    return (
                      <button
                        key={ct.id}
                        type="button"
                        disabled={!ct.available}
                        title={
                          ct.available ? undefined : `${ct.label} generation is not available yet.`
                        }
                        onClick={() => ct.available && setContentType(ct.id)}
                        aria-pressed={active}
                        className={cn(
                          "flex items-center gap-3 rounded-xl border p-4 text-left transition-colors",
                          active
                            ? "border-[#7C3AED] bg-[#7C3AED]/5 shadow-xs"
                            : "border-border hover:bg-secondary/60",
                          !ct.available &&
                            "cursor-not-allowed opacity-60 hover:bg-transparent",
                        )}
                      >
                        <span
                          className={cn(
                            "grid size-10 shrink-0 place-items-center rounded-lg",
                            active
                              ? "bg-[#7C3AED] text-white"
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

              <div className="grid gap-5 sm:grid-cols-2">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Campaign / promotion name</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Input
                    placeholder={brand.name ? `e.g., ${brand.name} Special Spotlight` : "e.g., Summer Launch"}
                    value={campaignName}
                    onChange={(e) => setCampaignName(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Product or collection</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  {/* Brand Master Product Chips */}
                  {brand.productsServices && brand.productsServices.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 pb-1">
                      <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                        <Sparkles className="size-3 text-[#7C3AED]" /> Quick pick:
                      </span>
                      {brand.productsServices.slice(0, 4).map((p, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => setProduct(p.name)}
                          className={cn(
                            "text-[11px] px-2 py-0.5 rounded-md border transition-all",
                            product === p.name
                              ? "border-[#7C3AED] bg-[#7C3AED] text-white font-medium shadow-xs"
                              : "border-border bg-secondary/50 text-foreground hover:border-[#7C3AED]/40 hover:bg-secondary"
                          )}
                        >
                          {p.name}
                        </button>
                      ))}
                    </div>
                  )}
                  <Input
                    placeholder={
                      brand.productsServices?.[0]?.name ||
                      (brand.industry ? `e.g., ${brand.industry} services` : "e.g., Premium Consultation")
                    }
                    value={product}
                    onChange={(e) => setProduct(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Target audience</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Input
                    placeholder={brand.audience || "e.g., Students, Professionals, Travelers"}
                    value={audience}
                    onChange={(e) => setAudience(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Location</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Input
                    placeholder={brand.location || "e.g., Bengaluru, India"}
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Occasion / festival</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Input
                    placeholder="e.g., Summer Season, New Year, Exclusive Offer"
                    value={occasion}
                    onChange={(e) => setOccasion(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Offer / Key Call-to-Action</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Input
                    placeholder={brand.ctaKeyword || brand.tagline || "e.g., Start Application Today / Flat 20% Off"}
                    value={offer}
                    onChange={(e) => setOffer(e.target.value)}
                  />
                </div>

                <div className="space-y-2 sm:col-span-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Brand tone</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Input
                    placeholder={brand.brandTone || "e.g., Authoritative, Premium, Trustworthy"}
                    value={brandTone}
                    onChange={(e) => setBrandTone(e.target.value)}
                  />
                </div>

                <div className="space-y-2 sm:col-span-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-sm font-medium">Custom instructions / Specific requirements</Label>
                    <span className="text-[11px] text-muted-foreground">optional</span>
                  </div>
                  <Textarea
                    placeholder="e.g., Ensure the poster has falling confetti, mention our winter discount code explicitly, etc."
                    value={customInstructions}
                    onChange={(e) => setCustomInstructions(e.target.value)}
                    rows={3}
                  />
                </div>
              </div>

              {/* VIDEO-ONLY FIELDS */}
              {contentType === "video" && (
                <div className="mt-8 rounded-xl border border-border p-5">
                  <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <Video className="size-4 text-[#7C3AED]" />
                      <h3 className="text-sm font-semibold text-foreground">Video settings</h3>
                    </div>
                    {/* The generator reads none of these, so they are shown as
                        the intended shape of the feature rather than pretended
                        to work. Nothing here is sent with the brief. */}
                    <span className="shrink-0 rounded-full border border-border bg-secondary/60 px-2.5 py-0.5 text-xs text-muted-foreground">
                      Not available yet
                    </span>
                  </div>

                  <div className="mt-4 grid gap-5 sm:grid-cols-3">
                    <div className="space-y-2">
                      <Label>Duration</Label>
                      <Select value={videoDuration} onValueChange={setVideoDuration} disabled>
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
                      <Select value={videoAspect} onValueChange={setVideoAspect} disabled>
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
                      <Select value={videoStyle} onValueChange={setVideoStyle} disabled>
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
                      disabled
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
                        <Images className="size-4 text-[#7C3AED]" />
                        <h3 className="text-sm font-semibold text-foreground">Carousel slides</h3>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Describe what belongs in each position. Slides are generated and published
                        in this order.
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
                          <span className="grid size-7 place-items-center rounded-full bg-[#7C3AED] text-xs font-semibold text-white">
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

              {/* POSTER ADD-ONS — logo and phone number from the brand kit */}
              {contentType !== "video" && (
                <div className="mt-8 rounded-xl border border-border p-5">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-foreground">Brand add-ons</h3>
                    <span className="text-xs font-medium text-primary">Live Overlay Enabled</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Automatically overlays your verified brand logo at the top-right and contact details in the footer.
                  </p>

                  <div className="mt-4 space-y-3">
                    <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-secondary/20 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        {hasLogo ? (
                          <img
                            src={brand.logoUrl}
                            alt="Brand logo"
                            className="size-9 shrink-0 rounded-lg border border-border bg-background object-contain p-1"
                          />
                        ) : (
                          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground">
                            <ImageIcon className="size-4" />
                          </span>
                        )}
                        <div className="min-w-0">
                          <Label htmlFor="addon-logo" className="text-sm font-medium cursor-pointer">Show brand logo (Top Right)</Label>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {hasLogo ? "Verified logo from your Brand Master." : "Upload a logo in Brand Master first."}
                          </p>
                        </div>
                      </div>
                      <Checkbox
                        id="addon-logo"
                        checked={includeLogo && hasLogo}
                        disabled={!hasLogo}
                        onCheckedChange={(checked) => setIncludeLogo(!!checked)}
                      />
                    </div>

                    <div className="rounded-xl border border-border bg-secondary/20 px-4 py-3">
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground">
                            <Phone className="size-4" />
                          </span>
                          <div className="min-w-0">
                            <Label htmlFor="addon-phone" className="text-sm font-medium cursor-pointer">Show phone & website (Footer Frame)</Label>
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              Rendered in a modern footer frame at the bottom.
                            </p>
                          </div>
                        </div>
                        <Checkbox
                          id="addon-phone"
                          checked={includePhone}
                          onCheckedChange={(checked) => setIncludePhone(!!checked)}
                        />
                      </div>
                      {includePhone ? (
                        <div className="mt-3">
                          <Label className="text-xs text-muted-foreground">Contact Phone Number</Label>
                          <Input
                            type="tel"
                            className="mt-1"
                            placeholder="+91 98765 43210"
                            value={phoneOverride}
                            onChange={(e) => setPhoneOverride(e.target.value)}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              )}

              <div className="mt-8 flex items-center gap-4">
                <Button
                  onClick={handleGenerate}
                  className="bg-[#7C3AED] hover:bg-[#6D28D9] text-white gap-2"
                >
                  <Sparkles className="size-4" /> Generate with AI
                </Button>
                <Button variant="ghost" onClick={() => setStep("create_or_upload")}>
                  Cancel
                </Button>
              </div>
            </div>
          </section>
        )}

        {/* STEP 1A: GEMINI GENERATING */}
        {step === "ai_generating" && (
          <section className="surface-card p-12 text-center flex flex-col items-center justify-center border border-[#7C3AED]/30 bg-[#F7F3EE] min-h-[400px]">
            <Loader2 className="size-12 animate-spin text-[#7C3AED] mb-6" />
            <h3 className="text-2xl font-semibold text-[#7C3AED]">AI is working...</h3>
            <p className="mt-3 text-muted-foreground max-w-md text-base">{workingMessage}</p>
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
                onClick={() => setStep("create_or_upload")}
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
              <Button variant="ghost" onClick={() => setStep("create_or_upload")}>
                Cancel
              </Button>
            </div>
          </section>
        )}

        {/* CONTENT PREVIEW & PUBLISHING SETUP */}
        {(step === "preview" || step === "publish_setup") && asset && (
          <div className="space-y-4">
            <button
              onClick={() => setStep("create_or_upload")}
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

                <div className="mt-4 rounded-xl border border-border overflow-hidden bg-background">
                  <div
                    className={cn(
                      "flex items-end bg-gradient-to-br p-6 relative overflow-hidden group",
                      asset.previewUrl ? "h-auto min-h-[280px] cursor-pointer" : "h-64",
                      asset.tone || "from-secondary to-muted",
                    )}
                    onClick={() =>
                      asset.previewUrl && asset.contentType !== "video" && setShowFullImage(true)
                    }
                  >
                    {asset.previewUrl ? (
                      asset.contentType === "video" ? (
                        <video
                          src={asset.previewUrl}
                          controls
                          className="absolute inset-0 h-full w-full object-contain bg-black"
                        />
                      ) : (
                        <>
                          <img
                            src={asset.previewUrl}
                            alt="Generated Poster"
                            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                          />
                          <div className="absolute inset-0 bg-black/40 opacity-0 transition-opacity duration-300 group-hover:opacity-100 flex items-center justify-center pointer-events-none">
                            <div className="flex items-center gap-2 text-white bg-black/50 px-4 py-2 rounded-full backdrop-blur-md">
                              <ZoomIn className="size-4" />
                              <span className="text-sm font-medium">View Full Size</span>
                            </div>
                          </div>
                        </>
                      )
                    ) : (
                      <p className="relative z-10 font-display text-3xl text-white mix-blend-overlay">
                        {asset.campaign}
                      </p>
                    )}
                  </div>

                  <div className="p-6">
                    {asset.source === "ai" ? (
                      <div className="inline-flex items-center gap-2 rounded-full bg-[#7C3AED]/10 px-3 py-1.5 text-xs font-medium text-[#7C3AED] mb-5">
                        <Sparkles className="size-3.5" /> Generated with AI
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
                          <Images className="size-4 text-[#7C3AED]" />
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
                                  className="size-12 shrink-0 rounded-lg border border-border object-cover"
                                />
                              ) : (
                                <span className="grid size-12 shrink-0 place-items-center rounded-lg bg-[#7C3AED]/10 text-sm font-semibold text-[#7C3AED]">
                                  {i + 1}
                                </span>
                              )}
                              <p className="min-w-0 text-sm text-muted-foreground">
                                {slide.description}
                              </p>
                            </li>
                          ))}
                        </ol>
                      </div>
                    ) : null}

                    {!contentLocked ? (
                      <div className="flex flex-wrap gap-2 pt-6 mt-6 border-t border-border">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setStep(asset.source === "ai" ? "ai_form" : "manual_upload")
                          }
                        >
                          <Edit3 className="mr-2 size-4" /> Edit / Replace Media
                        </Button>
                        {asset.source === "ai" && (
                          <Button variant="outline" size="sm" onClick={handleGenerate}>
                            <RefreshCw className="mr-2 size-4" /> Regenerate All
                          </Button>
                        )}
                      </div>
                    ) : (
                      <p className="mt-6 rounded-xl border border-emerald-500/25 bg-emerald-500/8 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
                        This is the approved version. Its copy and media are locked while publishing.
                      </p>
                    )}
                  </div>
                </div>

                {step === "preview" && !contentLocked && (
                  <div className="mt-8 grid gap-3 sm:grid-cols-2">
                    <Button
                      variant="outline"
                      className="h-12"
                      disabled={contentSaving}
                      onClick={() => void saveContentDraft()}
                    >
                      {contentSaving ? <Loader2 className="size-4 animate-spin" /> : null}
                      Save draft
                    </Button>
                    <Button
                      className="h-12"
                      disabled={contentSaving}
                      onClick={() => void saveContentDraft({ submit: true })}
                    >
                      {contentSaving ? <Loader2 className="size-4 animate-spin" /> : null}
                      Submit for review
                    </Button>
                  </div>
                )}
              </section>

              {/* RIGHT: SELECT SOCIAL ACCOUNTS */}
              {step === "publish_setup" && (
                <section className="surface-card p-5 sm:p-8 animate-in fade-in slide-in-from-bottom-4">
                  <p className="label-eyebrow text-primary">SELECT WHERE TO PUBLISH</p>
                  <div className="mt-4 space-y-2">
                    {accountsLoading ? (
                      <p className="flex items-center gap-2 rounded-xl border border-dashed border-border px-3 py-6 text-sm text-muted-foreground">
                        <Loader2 className="size-4 animate-spin" /> Loading your connected
                        accounts…
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
                    <td className="max-w-[220px] truncate px-4 py-3 font-medium">{row.content}</td>
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
        </div>
      </section>

      {/* FULL SIZE IMAGE MODAL */}
      <Dialog open={showFullImage} onOpenChange={setShowFullImage}>
        <DialogContent className="max-w-[90vw] md:max-w-3xl lg:max-w-4xl p-1 bg-transparent border-none shadow-none">
          <DialogTitle className="sr-only">Full Size Poster Preview</DialogTitle>
          {asset?.previewUrl && (
            <img
              src={asset.previewUrl}
              alt="Full size poster"
              className="w-full h-auto max-h-[90vh] object-contain rounded-lg"
            />
          )}
        </DialogContent>
      </Dialog>

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

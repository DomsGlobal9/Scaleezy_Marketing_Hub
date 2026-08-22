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
import { cn } from "@/lib/utils";
import { useBrandSettings } from "@/lib/brand-settings";
import { apiFetch, apiPost } from "@/lib/api";

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
  | "gemini_form"
  | "gemini_generating"
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
  id?: string;
  /** ContentItem row the backend persisted for this generation. */
  contentItemId?: string;
  name: string;
  type: string;
  dimensions: string;
  created: string;
  source: "gemini" | "upload";
  contentType: ContentType;
  campaign?: string;
  tone?: string;
  postTitle: string;
  postDescription: string;
  postHashtags: string;
  previewUrl?: string;
  /** Populated for carousels — one entry per slide, in order. */
  slides?: CarouselSlide[];
}

const CONTENT_TYPES: {
  id: ContentType;
  label: string;
  hint: string;
  icon: typeof ImageIcon;
}[] = [
  { id: "poster", label: "Poster", hint: "A single still image", icon: ImageIcon },
  { id: "video", label: "Video", hint: "A short promo clip", icon: Video },
  { id: "carousel", label: "Carousel", hint: "Multiple ordered slides", icon: Images },
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
const canPublishTo = (acc: any, isVideoAsset: boolean): boolean => {
  const status = String(acc?.status ?? "").toUpperCase();
  const enabled = (acc?.publishing_enabled ?? acc?.publishingEnabled) !== false;
  const formatMismatch = acc?.platform === "YOUTUBE" && !isVideoAsset;
  return status === "CONNECTED" && enabled && !formatMismatch;
};

function PublishingPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<WorkflowStep>("create_or_upload");
  const [asset, setAsset] = useState<DraftAsset | null>(null);
  const [showFullImage, setShowFullImage] = useState(false);
  const [referenceImageBase64, setReferenceImageBase64] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [uploadIntention, setUploadIntention] = useState<"reference" | "final" | null>(null);
  const [isGeneratingCaptions, setIsGeneratingCaptions] = useState(false);
  // Three different flows share the "AI is working" step; without this the
  // panel told a video uploader we were analysing their image.
  const [workingKind, setWorkingKind] = useState<WorkingKind>("generate");
  // Lets the user stop waiting on a queued generation, which otherwise holds
  // the screen for the full ten-minute polling ceiling.
  const generationAbort = useRef<AbortController | null>(null);

  // Gemini Form State
  const [campaignName, setCampaignName] = useState("");
  const [product, setProduct] = useState("");
  const [audience, setAudience] = useState("");
  const [location, setLocation] = useState("");
  const [occasion, setOccasion] = useState("");
  const [offer, setOffer] = useState("");
  const [brandTone, setBrandTone] = useState("");

  // What to generate, plus the per-type extras
  const [contentType, setContentType] = useState<ContentType>("poster");
  const [videoDuration, setVideoDuration] = useState(VIDEO_DURATIONS[1]!);
  const [videoAspect, setVideoAspect] = useState(VIDEO_ASPECTS[0]!);
  const [videoStyle, setVideoStyle] = useState(VIDEO_STYLES[0]!);
  const [videoScript, setVideoScript] = useState("");
  const [slides, setSlides] = useState<CarouselSlide[]>([newSlide(), newSlide(), newSlide()]);

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
  const [publishingHistory, setPublishingHistory] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);

  const loadHistory = useCallback(async () => {
    try {
      const res = await apiFetch("/api/marketing/publishing/jobs/");
      const data = await res.json();
      if (!Array.isArray(data)) {
        setHistoryError(true);
        return;
      }
      const historyRows: any[] = [];
      data.forEach((job: any) => {
        (job.items ?? []).forEach((item: any) => {
          historyRows.push({
            id: item.id,
            content: "Generated Marketing Post", // No text on asset currently, fallback
            platform: item.social_connection.platform,
            account: item.social_connection.account_name || item.social_connection.username,
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
      // Fetch workspaces
      const wsRes = await apiFetch("/api/marketing/workspaces/");
      const wsData = await wsRes.json();
      const wsId = Array.isArray(wsData) && wsData.length > 0 ? wsData[0].id : null;

      let assetId = asset?.id || null;
      const b64Data = asset?.previewUrl || referenceImageBase64;

      if (!assetId && b64Data && b64Data.startsWith("data:") && wsId) {
        // Convert base64 data URI to Blob
        const r = await fetch(b64Data);
        const blob = await r.blob();

        // Upload as file
        const formData = new FormData();
        formData.append("file", blob, "poster.jpg");
        formData.append("workspace_id", wsId);
        formData.append(
          "source",
          asset?.source === "gemini" ? "GEMINI_GENERATED" : "MANUAL_UPLOAD",
        );

        const uploadRes = await apiFetch("/api/marketing/assets/upload/", {
          method: "POST",
          body: formData,
        });
        const uploadData = await uploadRes.json();
        // Swallowing this used to drop the user into the fallback below and
        // publish somebody else's artwork, so it has to surface.
        if (!uploadData.success) {
          throw new Error(uploadData.message || "Could not upload the image for this post.");
        }
        assetId = uploadData.data.id;
      }

      if (!wsId || !assetId) {
        // There used to be a fallback here that picked the first row out of
        // /assets/ when this post had no image. MarketingAsset declares no
        // ordering, so it published an arbitrary earlier asset to live
        // accounts under this caption. Refusing is the only safe answer.
        throw new Error("There is no image to publish. Generate or upload one first.");
      }

      // Build the caption from the asset's generated/manual content
      const captionParts = [asset?.postTitle, asset?.postDescription, asset?.postHashtags].filter(
        Boolean,
      );
      const caption = captionParts.join("\n\n") || "";

      const res = await apiFetch("/api/marketing/publishing/jobs/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: wsId,
          asset_id: assetId,
          publish_mode: mode === "now" ? "NOW" : "SCHEDULED",
          ...(scheduledAt ? { scheduled_at: scheduledAt } : {}),
          caption,
          social_connection_ids: ids,
          ...(asset?.contentItemId ? { content_item_id: asset.contentItemId } : {}),
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
    } catch (err: any) {
      console.error(err);
      toast.error(err.message || "Network error while publishing.");
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

      const res = await apiFetch(`/api/marketing/gemini/${generationId}/`, { signal });
      const json = await res.json();
      const request = json.data ?? json;

      if (request?.status === "FAILED") {
        throw new Error(request.error_message || "Generation failed.");
      }
      if (request?.status !== "COMPLETED") continue;

      const resultRes = await apiFetch(`/api/marketing/gemini/${generationId}/results/`, {
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
        contentItemId: null,
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
    setStep("gemini_generating");
    try {
      // Video and multi-slide carousels run long enough to hit a gateway
      // timeout on the synchronous endpoint, and when they do the work is
      // lost even if the server finished it. Those go on the queue and are
      // polled; a poster still comes back in one request.
      const background = contentType === "video" || contentType === "carousel";
      const endpoint = background
        ? "/api/marketing/gemini/generate-async/"
        : "/api/marketing/gemini/generate/";

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
          referenceImageBase64,
          // contentType and slides are read and persisted on both the sync and
          // the async path. The video settings, the derived slideCount and the
          // logo/phone overlay keys that used to ride along here were read by
          // nothing — the views build their brief from an explicit allowlist —
          // so they are no longer sent and their controls are disabled above.
          contentType,
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

      const label =
        contentType === "video" ? "Video" : contentType === "carousel" ? "Carousel" : "Poster";

      setAsset({
        name: `${campaignName || "Untitled"} ${label}.${contentType === "video" ? "mp4" : "jpg"}`,
        type: contentType === "video" ? "MP4" : "JPG",
        dimensions:
          contentType === "video"
            ? // The aspect ratio picker no longer reaches the generator, so
              // naming a ratio here would assert a size nothing honoured.
              "As generated"
            : contentType === "carousel"
              ? `1080×1080 · ${slides.length} slides`
              : "1080×1350",
        created: new Date().toLocaleDateString("en-GB", {
          day: "2-digit",
          month: "short",
          year: "numeric",
        }),
        source: "gemini",
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
    } catch (err: any) {
      if (err?.name === "AbortError") {
        toast("Stopped waiting. Anything already queued keeps running.");
        setStep("gemini_form");
        return;
      }
      console.error("Gemini generation error:", err);
      toast.error(err.message || "Failed to generate content. Please try again.");
      setStep("gemini_form");
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
      setStep("gemini_generating");
      try {
        // Fetch workspaces
        const wsRes = await apiFetch("/api/marketing/workspaces/");
        const wsData = await wsRes.json();
        const wsId = Array.isArray(wsData) && wsData.length > 0 ? wsData[0].id : null;
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
        const analyzeRes = await apiFetch("/api/marketing/gemini/analyze-video/", {
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
        setStep("gemini_form");
        setIsAnalyzing(true);
        try {
          const res = await apiFetch("/api/marketing/gemini/analyze-image/", {
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
        setStep("gemini_generating"); // Re-use the loading step
        try {
          const res = await apiFetch("/api/marketing/gemini/generate-captions/", {
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
                  setStep("gemini_form");
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
        {step === "gemini_form" && (
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
                        ? "Gemini is currently analyzing your image to auto-fill the details..."
                        : "Gemini will analyze this image to write the perfect caption and generate a highly enhanced, professional marketing poster."}
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
                            ? "border-[#7C3AED] bg-[#7C3AED]/5"
                            : "border-border hover:bg-secondary/60",
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
                  <Label>Campaign / promotion name</Label>
                  <Input value={campaignName} onChange={(e) => setCampaignName(e.target.value)} />
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
                <div className="space-y-2">
                  <Label>Occasion / festival</Label>
                  <Input value={occasion} onChange={(e) => setOccasion(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>Offer</Label>
                  <Input value={offer} onChange={(e) => setOffer(e.target.value)} />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label>Brand tone</Label>
                  <Input value={brandTone} onChange={(e) => setBrandTone(e.target.value)} />
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
                  <h3 className="text-sm font-semibold text-foreground">Brand add-ons</h3>
                  {/* The old copy promised a per-generation override. Only the
                      brand-level defaults reach the poster; the toggles here
                      were a local copy that nothing downstream ever read. */}
                  <p className="mt-1 text-xs text-muted-foreground">
                    Follows your Brand Kit default in Settings — a per-generation override is not
                    available yet.
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
                          <Label className="text-sm font-normal">Show brand logo</Label>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {hasLogo ? "From your Brand Kit." : "Upload a logo in Settings first."}
                          </p>
                        </div>
                      </div>
                      <Checkbox checked={includeLogo && hasLogo} disabled />
                    </div>

                    <div className="rounded-xl border border-border bg-secondary/20 px-4 py-3">
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-muted-foreground">
                            <Phone className="size-4" />
                          </span>
                          <div className="min-w-0">
                            <Label className="text-sm font-normal">Show phone number</Label>
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              Printed at the bottom of the image.
                            </p>
                          </div>
                        </div>
                        <Checkbox checked={includePhone} disabled />
                      </div>
                      {includePhone ? (
                        <Input
                          type="tel"
                          className="mt-3"
                          disabled
                          placeholder="+91 98765 43210"
                          value={phoneOverride}
                          onChange={(e) => setPhoneOverride(e.target.value)}
                        />
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
                  <Sparkles className="size-4" /> Generate with Gemini
                </Button>
                <Button variant="ghost" onClick={() => setStep("create_or_upload")}>
                  Cancel
                </Button>
              </div>
            </div>
          </section>
        )}

        {/* STEP 1A: GEMINI GENERATING */}
        {step === "gemini_generating" && (
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
                    Gemini will use this image as inspiration to generate a brand new, highly
                    polished AI poster.
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
                    Skip generation. Have Gemini write engaging captions and hashtags for this exact
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
                    {asset.source === "gemini" ? (
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
                        <Label>Post Title</Label>
                        <Input
                          value={asset.postTitle}
                          onChange={(e) => setAsset({ ...asset, postTitle: e.target.value })}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Post Description / Caption</Label>
                        <Textarea
                          rows={4}
                          value={asset.postDescription}
                          onChange={(e) => setAsset({ ...asset, postDescription: e.target.value })}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Hashtags</Label>
                        <Input
                          value={asset.postHashtags}
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

                    <div className="flex flex-wrap gap-2 pt-6 mt-6 border-t border-border">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          setStep(asset.source === "gemini" ? "gemini_form" : "manual_upload")
                        }
                      >
                        <Edit3 className="mr-2 size-4" /> Edit / Replace Media
                      </Button>
                      {asset.source === "gemini" && (
                        <Button variant="outline" size="sm" onClick={handleGenerate}>
                          <RefreshCw className="mr-2 size-4" /> Regenerate All
                        </Button>
                      )}
                    </div>
                  </div>
                </div>

                {step === "preview" && (
                  <Button
                    className="mt-8 w-full text-lg h-14"
                    onClick={() => setStep("publish_setup")}
                  >
                    Continue to Publishing
                  </Button>
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
                                {acc.accountName || acc.account_name}
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

import { createFileRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  CheckCircle2,
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
  GripVertical,
  Image as ImageIcon,
  Images,
  Phone,
  Plus,
  Trash2,
  Video,
} from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
import { DEMO_ACCOUNTS, PUBLISHING_HISTORY } from "@/lib/marketing-data";
import { cn } from "@/lib/utils";
import { useBrandSettings } from "@/lib/brand-settings";
import { apiFetch } from "@/lib/api";

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

type JobState = "queued" | "uploading" | "publishing" | "published" | "failed";

interface Job {
  id: string;
  label: string;
  state: JobState;
  message?: string | undefined;
}

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

function PublishingPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<WorkflowStep>("create_or_upload");
  const [asset, setAsset] = useState<DraftAsset | null>(null);
  const [showFullImage, setShowFullImage] = useState(false);
  const [referenceImageBase64, setReferenceImageBase64] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [uploadIntention, setUploadIntention] = useState<"reference" | "final" | null>(null);
  const [isGeneratingCaptions, setIsGeneratingCaptions] = useState(false);

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

  const hasLogo = !!(brand.logoDataUrl || brand.logoUrl);

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
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [running, setRunning] = useState(false);
  const [publishingHistory, setPublishingHistory] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>(DEMO_ACCOUNTS);

  useEffect(() => {
    // Fetch connected accounts for publishing
    apiFetch("/api/marketing/social-accounts/")
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setAccounts(data);
        }
      })
      .catch(console.error);

    apiFetch("/api/marketing/publishing/jobs/")
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          const historyRows: any[] = [];
          data.forEach((job: any) => {
            if (job.items && Array.isArray(job.items)) {
              job.items.forEach((item: any) => {
                historyRows.push({
                  id: item.id,
                  content: "Generated Marketing Post", // No text on asset currently, fallback
                  platform: item.social_connection.platform,
                  account: item.social_connection.account_name || item.social_connection.username,
                  date: new Date(item.queued_at).toLocaleString(),
                  status: item.status.charAt(0).toUpperCase() + item.status.slice(1).toLowerCase(),
                  postId: item.external_post_id,
                  error: item.error_message,
                });
              });
            }
          });
          setPublishingHistory(historyRows);
        }
      })
      .catch((err) => {
        console.error("Failed to load history:", err);
        setPublishingHistory([]);
      });
  }, []);

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const runJobs = async (ids: string[]) => {
    if (ids.length === 0) return;
    setRunning(true);
    toast("Publishing started.");

    try {
      // Fetch workspaces
      const wsRes = await apiFetch("/api/marketing/workspaces/");
      const wsData = await wsRes.json();
      const wsId = Array.isArray(wsData) && wsData.length > 0 ? wsData[0].id : null;

      let assetId = asset?.id || null;
      const b64Data = asset?.previewUrl || referenceImageBase64;

      if (!assetId && b64Data && b64Data.startsWith("data:") && wsId) {
        try {
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

          const uploadRes = await apiFetch("/api/marketing/assets/upload/",
            {
              method: "POST",
              body: formData,
            },
          );
          const uploadData = await uploadRes.json();
          if (uploadData.success) {
            assetId = uploadData.data.id;
          }
        } catch (e) {
          console.error("Asset upload failed:", e);
        }
      }

      if (!assetId) {
        // Fallback for MVP if no image is available
        const asRes = await apiFetch("/api/marketing/assets/");
        const asData = await asRes.json();
        assetId = Array.isArray(asData) && asData.length > 0 ? asData[0].id : null;
      }

      if (!wsId || !assetId) {
        throw new Error("Missing workspace or failed to upload asset.");
      }

      // Build the caption from the asset's generated/manual content
      const captionParts = [
        asset?.postTitle,
        asset?.postDescription,
        asset?.postHashtags,
      ].filter(Boolean);
      const caption = captionParts.join("\n\n") || "";

      const res = await apiFetch("/api/marketing/publishing/jobs/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: wsId,
          asset_id: assetId,
          publish_mode: mode === "now" ? "NOW" : "SCHEDULED",
          caption,
          social_connection_ids: ids,
        }),
      });

      const data = await res.json();

      if (data.success) {
        toast.success("Publishing job executed successfully.");
      } else {
        toast.error(data.message || "Failed to publish.");
      }
    } catch (err: any) {
      console.error(err);
      toast.error(err.message || "Network error while publishing.");
    } finally {
      setRunning(false);
      setStep("create_or_upload"); // Reset or show history
    }
  };

  const handleGenerate = async () => {
    setStep("gemini_generating");
    try {
      const res = await apiFetch("/api/marketing/gemini/generate/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          campaignName,
          product,
          audience,
          location,
          occasion,
          offer,
          brandTone,
          referenceImageBase64,
          // Content type and its extras — backend fields still to be added.
          contentType,
          ...(contentType === "video"
            ? {
                videoDuration,
                videoAspectRatio: videoAspect,
                videoStyle,
                videoScript,
              }
            : {}),
          ...(contentType === "carousel"
            ? {
                slideCount: slides.length,
                slides: slides.map((s, i) => ({
                  position: i + 1,
                  description: s.description.trim() || slidePlaceholder(i),
                })),
              }
            : {}),
          // Poster overlays
          includeLogo: includeLogo && hasLogo,
          logoUrl: includeLogo && hasLogo ? brand.logoUrl || brand.logoDataUrl : "",
          includePhoneNumber: includePhone && !!phoneOverride.trim(),
          phoneNumber: includePhone ? phoneOverride.trim() : "",
        }),
      });
      const json = await res.json();
      if (!json.success) {
        throw new Error(json.message || "Generation failed");
      }
      const d = json.data;

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
            ? videoAspect
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
      console.error("Gemini generation error:", err);
      toast.error(err.message || "Failed to generate content. Please try again.");
      setStep("gemini_form");
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const isVideo = file.type.startsWith("video/");

    if (isVideo) {
      if (uploadIntention === "reference") {
        toast.error("Video cannot be used as a reference for AI generation.");
        return;
      }
      
      setIsGeneratingCaptions(true);
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

        const uploadRes = await apiFetch("/api/marketing/assets/upload/",
            { method: "POST", body: formData }
        );
        const uploadData = await uploadRes.json();
        if (!uploadData.success) throw new Error("Upload failed.");

        const assetId = uploadData.data.id;
        const fileUrl = uploadData.data.file_url;

        // Analyze video
        const analyzeRes = await apiFetch("/api/marketing/gemini/analyze-video/",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ asset_id: assetId }),
            }
        );
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
          const res = await apiFetch("/api/marketing/gemini/analyze-image/",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ referenceImageBase64: base64String }),
            },
          );
          const json = await res.json();
          if (json.success && json.data) {
            const d = json.data;
            if (d.campaignName) setCampaignName(d.campaignName);
            if (d.product) setProduct(d.product);
            if (d.occasion) setOccasion(d.occasion);
            if (d.brandTone) setBrandTone(d.brandTone);
            toast.success("AI auto-filled your campaign details!");
          }
        } catch (e) {
          console.error("Failed to analyze image", e);
        } finally {
          setIsAnalyzing(false);
        }
      } else if (uploadIntention === "final") {
        setIsGeneratingCaptions(true);
        setStep("gemini_generating"); // Re-use the loading step
        try {
          const res = await apiFetch("/api/marketing/gemini/generate-captions/",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ referenceImageBase64: base64String }),
            },
          );
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

  const failedIds = (jobs ?? []).filter((j) => j.state === "failed").map((j) => j.id);
  const publishedCount = (jobs ?? []).filter((j) => j.state === "published").length;
  const complete = !!jobs && !running;

  return (
    <div>
      <PageHeader
        eyebrow="Marketing Hub"
        title="Publishing"
        subtitle="Create or upload your marketing content, select your social channels, and publish everywhere from one place."
        backTo="/"
        actions={
          <Button variant="outline" onClick={() => toast("Draft saved.")}>
            Save Draft
          </Button>
        }
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
                  <div className="flex items-center gap-2">
                    <Video className="size-4 text-[#7C3AED]" />
                    <h3 className="text-sm font-semibold text-foreground">Video settings</h3>
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
                      placeholder="What should be said or shown, scene by scene. Leave blank to let AI write it."
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
                        <div className="flex flex-col items-center gap-1 pt-1">
                          <span className="grid size-7 place-items-center rounded-full bg-[#7C3AED] text-xs font-semibold text-white">
                            {i + 1}
                          </span>
                          <GripVertical className="size-3.5 text-muted-foreground/50" />
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
                  <p className="mt-1 text-xs text-muted-foreground">
                    Defaults come from your Brand Kit in Settings. Changing them here affects only
                    this generation.
                  </p>

                  <div className="mt-4 space-y-3">
                    <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-secondary/20 px-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        {hasLogo ? (
                          <img
                            src={brand.logoDataUrl || brand.logoUrl}
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
                      <Checkbox
                        checked={includeLogo && hasLogo}
                        disabled={!hasLogo}
                        onCheckedChange={(v) => setIncludeLogo(!!v)}
                      />
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
                        <Checkbox
                          checked={includePhone}
                          onCheckedChange={(v) => setIncludePhone(!!v)}
                        />
                      </div>
                      {includePhone ? (
                        <Input
                          type="tel"
                          className="mt-3"
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
            <p className="mt-3 text-muted-foreground max-w-md text-base">
              Analyzing your image to craft the perfect marketing asset.
            </p>
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
              <ArrowLeft className="size-4" /> Back to Dashboard
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
                    onClick={() => asset.previewUrl && asset.contentType !== "video" && setShowFullImage(true)}
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
                    {accounts.map((acc) => {
                      const s = (acc.status || "").toUpperCase();
                      const isYoutube = acc.platform === "YOUTUBE";
                      const isVideo = asset?.contentType === "video";
                      const isFormatMismatch = isYoutube && !isVideo;
                      
                      const disabled = (s !== "CONNECTED" && s !== "TOKEN_EXPIRED") || isFormatMismatch;
                      return (
                        <label
                          key={acc.id}
                          className={cn(
                            "grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-3",
                            selected.includes(acc.id) && "border-primary bg-primary/5",
                            disabled && "opacity-60 cursor-not-allowed",
                          )}
                          title={isFormatMismatch ? "YouTube only supports video uploads" : ""}
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
                            </span>
                          </span>
                          <StatusBadge status={acc.status} className="justify-self-end" />
                        </label>
                      );
                    })}
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
                        <Input type="date" className="mt-1.5" defaultValue="2026-08-12" />
                      </div>
                      <div>
                        <Label className="text-xs tracking-wide uppercase">Time</Label>
                        <Input type="time" className="mt-1.5" defaultValue="10:30" />
                      </div>
                      <div>
                        <Label className="text-xs tracking-wide uppercase">Timezone</Label>
                        <Select defaultValue="Asia/Kolkata">
                          <SelectTrigger className="mt-1.5 w-full">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {["Asia/Kolkata", "Asia/Dubai", "Europe/London"].map((tz) => (
                              <SelectItem key={tz} value={tz}>
                                {tz}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  ) : null}

                  <p className="mt-4 text-xs text-muted-foreground">
                    Allowed publishing hours, daily limits, paused accounts and token validity are
                    checked before each job is created.
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
                {publishingHistory.map((row, i) => (
                  <tr key={i} className="border-b border-border/70 last:border-0">
                    <td className="max-w-[220px] truncate px-4 py-3 font-medium">{row.asset}</td>
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
                        <Button size="sm" variant="outline" onClick={() => toast("Retrying…")}>
                          <RotateCcw className="size-4" /> Retry
                        </Button>
                      ) : row.status === "Published" ? (
                        <Button size="sm" variant="ghost">
                          <ExternalLink className="size-4" /> View
                        </Button>
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
            {publishingHistory.map((row, i) => (
              <div key={i} className="p-4">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-foreground">
                    {row.asset}
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
                {row.error !== "—" ? (
                  <p className="mt-2 text-xs text-destructive">{row.error}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* JOB PROGRESS MODAL */}
      <Dialog open={!!jobs} onOpenChange={(o) => !o && !running && setJobs(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="tracking-[0.08em] uppercase">
              {complete ? "Publication Complete" : "Publishing Content"}
            </DialogTitle>
          </DialogHeader>
          <ul className="space-y-2">
            {(jobs ?? []).map((job) => (
              <li
                key={job.id}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-2.5"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-foreground">
                    {job.label}
                  </span>
                  {job.message ? (
                    <span className="block text-xs text-destructive">{job.message}</span>
                  ) : null}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {job.state === "published" ? (
                    <>
                      <CheckCircle2 className="size-4 text-success" /> Published
                    </>
                  ) : job.state === "failed" ? (
                    <>
                      <AlertTriangle className="size-4 text-gold" /> Failed
                    </>
                  ) : (
                    <>
                      <Loader2 className="size-4 animate-spin text-primary" />
                      {job.state === "uploading"
                        ? "Uploading..."
                        : job.state === "publishing"
                          ? "Publishing..."
                          : "Queued"}
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
          {complete ? (
            <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
              <p className="text-sm text-muted-foreground">
                <span className="font-semibold text-foreground">{publishedCount}</span> Published ·
                <span className="font-semibold text-foreground"> {failedIds.length}</span> Failed
              </p>
              <div className="flex gap-2">
                {failedIds.length ? (
                  <Button size="sm" variant="outline" onClick={() => runJobs(failedIds)}>
                    <RotateCcw className="size-4" /> Retry Failed
                  </Button>
                ) : null}
                <Button size="sm" onClick={() => setJobs(null)}>
                  Done
                </Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
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

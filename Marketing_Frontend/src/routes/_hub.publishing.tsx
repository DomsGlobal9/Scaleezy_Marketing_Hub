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
  ArrowLeft
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

type WorkflowStep = "create_or_upload" | "gemini_form" | "gemini_generating" | "manual_upload" | "preview" | "publish_setup";

interface DraftAsset {
  name: string;
  type: string;
  dimensions: string;
  created: string;
  source: 'gemini' | 'upload';
  campaign?: string;
  tone?: string;
  postTitle: string;
  postDescription: string;
  postHashtags: string;
  previewUrl?: string;
}

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

  // Publishing State
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<"now" | "schedule">("now");
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [running, setRunning] = useState(false);
  const [publishingHistory, setPublishingHistory] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>(DEMO_ACCOUNTS);

  useEffect(() => {
    // Fetch connected accounts for publishing
    fetch('http://127.0.0.1:8000/api/marketing/social-accounts/')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setAccounts(data);
        }
      })
      .catch(console.error);

    // In a real app, you'd fetch both publishing history and media assets
    // fetch('http://127.0.0.1:8000/api/marketing/publishing/history/')
    //   .then(res => res.json())
    //   .then(data => setPublishingHistory(data))
    //   .catch(console.error);
    setPublishingHistory([]);
  }, []);

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const runJobs = async (ids: string[]) => {
    if (ids.length === 0) return;
    setRunning(true);
    toast("Publishing started.");
    
    try {
        // Fetch workspaces
        const wsRes = await fetch("http://127.0.0.1:8000/api/marketing/workspaces/");
        const wsData = await wsRes.json();
        const wsId = Array.isArray(wsData) && wsData.length > 0 ? wsData[0].id : null;
        
        // Fetch first asset (hack for MVP, ideally we'd create one or pick from state)
        const asRes = await fetch("http://127.0.0.1:8000/api/marketing/assets/");
        const asData = await asRes.json();
        const assetId = Array.isArray(asData) && asData.length > 0 ? asData[0].id : null;
        
        if (!wsId || !assetId) {
            throw new Error("Missing workspace or asset in database.");
        }

        const res = await fetch("http://127.0.0.1:8000/api/marketing/publishing/jobs/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: wsId,
                asset_id: assetId,
                publish_mode: mode === "now" ? "NOW" : "SCHEDULED",
                social_connection_ids: ids
            })
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
      const res = await fetch("http://127.0.0.1:8000/api/marketing/gemini/generate/", {
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
        }),
      });
      const json = await res.json();
      if (!json.success) {
        throw new Error(json.message || "Generation failed");
      }
      const d = json.data;
      setAsset({
        name: `${campaignName} Poster.jpg`,
        type: "JPG",
        dimensions: "1080×1350",
        created: new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
        source: "gemini",
        campaign: campaignName,
        tone: "from-[#F7F3EE] to-[#7C3AED]/20",
        postTitle: d.postTitle || `${campaignName} Announcement`,
        postDescription: d.postDescription || "",
        postHashtags: d.postHashtags || "",
        previewUrl: d.posterImageUrl || undefined,
      });
      setStep("preview");
    } catch (err: any) {
      console.error("Gemini generation error:", err);
      toast.error(err.message || "Failed to generate content. Please try again.");
      setStep("gemini_form");
    }
  };


  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Convert file to base64
    const reader = new FileReader();
    reader.onload = async (event) => {
      const base64String = event.target?.result as string;
      setReferenceImageBase64(base64String);
      
      if (uploadIntention === "reference") {
        setStep("gemini_form");
        setIsAnalyzing(true);
        try {
          const res = await fetch("http://127.0.0.1:8000/api/marketing/gemini/analyze-image/", {
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
          const res = await fetch("http://127.0.0.1:8000/api/marketing/gemini/generate-captions/", {
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
            created: new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
            source: "upload",
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
            <h2 className="mb-6 text-xl font-semibold tracking-tight text-foreground">CREATE YOUR CONTENT</h2>
            
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
                  <h3 className="text-lg  font-semibold text-foreground">↑ Upload Poster / Image</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Upload a reference image or a final poster.
                  </p>
                </div>
                <div className="cursor-pointer mt-4 rounded-full bg-background px-6 py-2 text-sm font-medium text-foreground border border-border transition-transform group-hover:scale-105 shadow-sm">
                  Upload Poster
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
                  <h2 className="text-2xl font-semibold tracking-tight text-[#7C3AED]">GENERATE WITH AI</h2>
                  <p className="text-xs font-semibold tracking-widest text-[#7C3AED]/70 uppercase mt-1">POWERED BY AI</p>
                </div>
              </div>
            </div>

            <div className="p-5 sm:p-8">
              {referenceImageBase64 && (
                <div className="mb-6 flex items-start gap-4 p-4 rounded-xl border border-[#7C3AED]/20 bg-[#7C3AED]/5">
                  <div className="relative w-24 h-24 rounded-lg overflow-hidden shrink-0 border border-border">
                    <img src={referenceImageBase64} alt="Reference" className="w-full h-full object-cover" />
                  </div>
                  <div className="flex-1">
                    <h3 className="font-semibold text-foreground flex items-center gap-2">
                      Reference Image Uploaded
                      {isAnalyzing && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
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

              <div className="mt-8 flex items-center gap-4">
                <Button onClick={handleGenerate} className="bg-[#7C3AED] hover:bg-[#6D28D9] text-white gap-2">
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
              <h2 className="text-xl font-semibold tracking-tight text-foreground">CHOOSE UPLOAD TYPE</h2>
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
                    Gemini will use this image as inspiration to generate a brand new, highly polished AI poster.
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
                    Skip generation. Have Gemini write engaging captions and hashtags for this exact poster.
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
                <div className={cn("flex items-end bg-gradient-to-br p-6 relative overflow-hidden group", asset.previewUrl ? "h-auto min-h-[280px] cursor-pointer" : "h-64", asset.tone || "from-secondary to-muted")}
                     onClick={() => asset.previewUrl && setShowFullImage(true)}>
                  {asset.previewUrl ? (
                    <>
                      <img src={asset.previewUrl} alt="Generated Poster" className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" />
                      <div className="absolute inset-0 bg-black/40 opacity-0 transition-opacity duration-300 group-hover:opacity-100 flex items-center justify-center">
                        <div className="flex items-center gap-2 text-white bg-black/50 px-4 py-2 rounded-full backdrop-blur-md">
                          <ZoomIn className="size-4" />
                          <span className="text-sm font-medium">View Full Size</span>
                        </div>
                      </div>
                    </>
                  ) : (
                    <p className="relative z-10 font-display text-3xl text-white mix-blend-overlay">{asset.campaign}</p>
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
                  
                  <div className="flex flex-wrap gap-2 pt-6 mt-6 border-t border-border">
                    <Button variant="outline" size="sm" onClick={() => setStep(asset.source === "gemini" ? "gemini_form" : "manual_upload")}>
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
                    const disabled = acc.status !== "Connected" && acc.status !== "Token Expired";
                    return (
                      <label
                        key={acc.id}
                        className={cn(
                          "grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-3",
                          selected.includes(acc.id) && "border-primary bg-primary/5",
                          disabled && "opacity-60",
                        )}
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
                          </span>
                        </span>
                        <StatusBadge
                          status={acc.status}
                          className="justify-self-end"
                        />
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
                  Allowed publishing hours, daily limits, paused accounts and token validity are checked before each job is created.
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
      <input type="file" className="hidden" ref={fileInputRef} onChange={handleFileUpload} accept="image/*,video/mp4" />
    </div>
  );
}

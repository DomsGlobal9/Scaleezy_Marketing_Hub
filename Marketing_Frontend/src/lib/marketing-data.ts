export type Platform =
  "facebook" | "instagram" | "linkedin" | "x" | "tiktok" | "youtube" | "google-business";

export type AccountStatus =
  | "Not Connected"
  | "Connecting"
  | "Connected"
  | "Permission Missing"
  | "Token Expired"
  | "Reauthorization Required"
  | "Revoked"
  | "Connection Failed"
  | "Publishing Disabled"
  | "Disconnected"
  | "Platform Unavailable";

export type StatusTone = "success" | "warning" | "danger" | "neutral";

export function statusTone(status: AccountStatus): StatusTone {
  switch (status) {
    case "Connected":
      return "success";
    case "Token Expired":
    case "Reauthorization Required":
    case "Permission Missing":
    case "Publishing Disabled":
      return "warning";
    case "Revoked":
    case "Connection Failed":
    case "Platform Unavailable":
      return "danger";
    default:
      return "neutral";
  }
}

export interface PlatformMeta {
  id: Platform;
  name: string;
  accountType: string;
  fields: string[];
  accountTypeOptions: string[];
  requiredPermissions: string[];
  optionalPermissions: string[];
}

export const PLATFORMS: PlatformMeta[] = [
  {
    id: "facebook",
    name: "Facebook",
    accountType: "Facebook Page",
    accountTypeOptions: ["Facebook Page"],
    requiredPermissions: ["Publish content", "Upload media", "Check publishing status"],
    optionalPermissions: ["Read comments", "Read analytics"],
    fields: ["Page ID", "Page name", "Page URL", "Page role"],
  },
  {
    id: "instagram",
    name: "Instagram",
    accountType: "Business / Creator",
    accountTypeOptions: ["Business Account", "Creator Account"],
    requiredPermissions: ["Publish content", "Upload media", "Check publishing status"],
    optionalPermissions: ["Read comments", "Read analytics"],
    fields: ["Instagram User ID", "Username", "Account type", "Connected Facebook Page"],
  },
  {
    id: "linkedin",
    name: "LinkedIn",
    accountType: "Organization Page",
    accountTypeOptions: ["Organization Page", "Member Profile"],
    requiredPermissions: ["Publish content", "Upload image / video", "Check publishing status"],
    optionalPermissions: ["Read analytics"],
    fields: ["Organization Page ID", "Organization name", "Page URL", "Content role"],
  },
  {
    id: "x",
    name: "X",
    accountType: "X Account",
    accountTypeOptions: ["X Account"],
    requiredPermissions: ["Create post", "Upload media"],
    optionalPermissions: ["Read analytics"],
    fields: ["User ID", "Username", "Display name", "API plan", "Rate-limit status"],
  },
  {
    id: "youtube",
    name: "YouTube",
    accountType: "Channel",
    accountTypeOptions: ["Brand Channel", "Personal Channel"],
    requiredPermissions: ["Video upload", "Check publishing status"],
    optionalPermissions: ["Read analytics"],
    fields: ["Channel ID", "Channel name", "Default privacy", "Default category"],
  },
  {
    id: "google-business",
    name: "Google Business Profile",
    accountType: "Business Location",
    accountTypeOptions: ["Business Location"],
    requiredPermissions: ["Local post", "Image upload", "Post status"],
    optionalPermissions: ["Administrator access"],
    fields: ["Location ID", "Business name", "Business address", "Google Maps URL"],
  },
];

export interface SocialAccount {
  id: string;
  platform: Platform;
  status: AccountStatus;
  accountName: string;
  username: string;
  accountType: string;
  profileUrl: string;
  externalId: string;
  connectedBy: string;
  connectedEmail: string;
  role: string;
  permissions: string[];
  tokenStatus: string;
  lastVerified: string;
  lastPublished: string;
  connectedAt: string;
  lastError?: string | undefined;
  publishingEnabled: boolean;
  isDefault: boolean;
  platformDetails: { label: string; value: string }[];
  settings: {
    timezone: string;
    allowedStart: string;
    allowedEnd: string;
    dailyLimit: number;
    automaticRetry: boolean;
    comments: boolean;
    analytics: boolean;
    paused: boolean;
  };
}

const baseSettings = {
  timezone: "Asia/Kolkata",
  allowedStart: "09:00",
  allowedEnd: "21:00",
  dailyLimit: 5,
  automaticRetry: true,
  comments: false,
  analytics: true,
  paused: false,
};

export const DEMO_ACCOUNTS: SocialAccount[] = [];

export interface MediaAsset {
  id: string;
  name: string;
  type: string;
  created: string;
  ratio: string;
  tone: string;
  campaign: string;
}

export const MEDIA_ASSETS: MediaAsset[] = [];

export const PUBLISHING_HISTORY: any[] = [];

export const AUDIT_LOGS: any[] = [];

export const PERMISSION_MATRIX = [
  {
    role: "Viewer",
    view: true,
    create: false,
    edit: false,
    approve: false,
    publish: false,
    disconnect: false,
    admin: false,
  },
  {
    role: "Marketing Executive",
    view: true,
    create: true,
    edit: true,
    approve: false,
    publish: false,
    disconnect: false,
    admin: false,
  },
  {
    role: "Marketing Manager",
    view: true,
    create: true,
    edit: true,
    approve: true,
    publish: true,
    disconnect: false,
    admin: false,
  },
  {
    role: "Workspace Admin",
    view: true,
    create: true,
    edit: true,
    approve: true,
    publish: true,
    disconnect: true,
    admin: true,
  },
];

/**
 * Static vocabulary for the social accounts screens: platform metadata and
 * status tones. No demo rows live here any more — every list in the app is
 * loaded from the API and shows a truthful empty state when there is nothing.
 */
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

export function statusTone(status: AccountStatus | string): StatusTone {
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
  /** Whether the backend has an OAuth adapter for it today. */
  supported: boolean;
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
    supported: true,
  },
  {
    id: "instagram",
    name: "Instagram",
    accountType: "Business / Creator",
    accountTypeOptions: ["Business Account", "Creator Account"],
    requiredPermissions: ["Publish content", "Upload media", "Check publishing status"],
    optionalPermissions: ["Read comments", "Read analytics"],
    fields: ["Instagram User ID", "Username", "Account type", "Connected Facebook Page"],
    supported: true,
  },
  {
    id: "linkedin",
    name: "LinkedIn",
    accountType: "Personal profile",
    accountTypeOptions: ["Personal profile"],
    requiredPermissions: ["Publish content", "Upload image / video", "Check publishing status"],
    optionalPermissions: ["Read analytics"],
    fields: ["Member ID", "Profile name", "Profile URL"],
    supported: true,
  },
  {
    id: "x",
    name: "X",
    accountType: "X Account",
    accountTypeOptions: ["X Account"],
    requiredPermissions: ["Create post", "Upload media"],
    optionalPermissions: ["Read analytics"],
    fields: ["User ID", "Username", "Display name", "API plan", "Rate-limit status"],
    supported: true,
  },
  {
    id: "youtube",
    name: "YouTube",
    accountType: "Channel",
    accountTypeOptions: ["Brand Channel", "Personal Channel"],
    requiredPermissions: ["Video upload", "Check publishing status"],
    optionalPermissions: ["Read analytics"],
    fields: ["Channel ID", "Channel name", "Default privacy", "Default category"],
    supported: true,
  },
  {
    id: "google-business",
    name: "Google Business Profile",
    accountType: "Business Location",
    accountTypeOptions: ["Business Location"],
    requiredPermissions: ["Local post", "Image upload", "Post status"],
    optionalPermissions: ["Administrator access"],
    fields: ["Location ID", "Business name", "Business address", "Google Maps URL"],
    supported: false,
  },
];

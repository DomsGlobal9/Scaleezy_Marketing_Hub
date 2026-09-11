/**
 * Illustrations for the public pages.
 *
 * Authored as inline SVG rather than sourced as bitmaps, for four reasons that
 * all matter here: they stay sharp at any size, they weigh a few hundred bytes
 * instead of a few hundred kilobytes, they inherit the page's own colours
 * through `currentColor` and the brand tokens so they work on the light and
 * dark bands alike, and — most importantly — they depict the product honestly.
 * A stock photograph of a smiling team at a laptop would say nothing true about
 * what this software does, and a mocked-up dashboard full of invented metrics
 * would say something false.
 *
 * Each one is `role="img"` with a <title>, so it is announced to a screen
 * reader as a single labelled graphic rather than read out as loose fragments.
 */
import { cn } from "@/lib/utils";

const LIME = "var(--color-primary)";

interface IllustrationProps {
  className?: string;
}

/** Shared frame: responsive box, no fixed pixel size, decorative parts hidden. */
function Figure({
  title,
  viewBox,
  className,
  children,
}: {
  title: string;
  viewBox: string;
  // Explicitly `| undefined`: the project sets exactOptionalPropertyTypes, so
  // an optional prop will not accept a value that is possibly undefined unless
  // the type says so, and every caller forwards its own optional className.
  className?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <svg
      role="img"
      aria-label={title}
      viewBox={viewBox}
      className={cn("h-auto w-full", className)}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>{title}</title>
      {children}
    </svg>
  );
}

/**
 * Four kinds of brand material converging into one compiled brand profile.
 * Used on /how-it-works and /capabilities.
 */
export function BrandBrainIllustration({ className }: IllustrationProps) {
  const sources = [
    { y: 24, label: "Documents" },
    { y: 74, label: "Transcripts" },
    { y: 124, label: "References" },
    { y: 174, label: "Corrections" },
  ];

  return (
    <Figure
      title="Documents, transcripts, reference posts and human corrections feeding one compiled brand profile"
      viewBox="0 0 420 220"
      className={className}
    >
      {sources.map((source) => (
        <g key={source.label}>
          <rect
            x="4"
            y={source.y}
            width="128"
            height="34"
            rx="8"
            stroke="currentColor"
            strokeOpacity="0.22"
          />
          <text
            x="18"
            y={source.y + 22}
            fill="currentColor"
            fillOpacity="0.75"
            fontSize="12"
            fontFamily="inherit"
          >
            {source.label}
          </text>
          <path
            d={`M132 ${source.y + 17} C 176 ${source.y + 17}, 196 110, 250 110`}
            stroke="currentColor"
            strokeOpacity="0.28"
            strokeWidth="1.5"
          />
        </g>
      ))}

      <circle cx="256" cy="110" r="6" fill={LIME} />

      <rect
        x="288"
        y="66"
        width="126"
        height="88"
        rx="14"
        stroke={LIME}
        strokeWidth="1.5"
        fill={LIME}
        fillOpacity="0.08"
      />
      <text x="308" y="102" fill="currentColor" fontSize="13" fontWeight="600" fontFamily="inherit">
        Brand
      </text>
      <text x="308" y="122" fill="currentColor" fontSize="13" fontWeight="600" fontFamily="inherit">
        profile
      </text>
      <text
        x="308"
        y="140"
        fill="currentColor"
        fillOpacity="0.55"
        fontSize="10"
        fontFamily="inherit"
      >
        confirmed by a person
      </text>
    </Figure>
  );
}

/**
 * Capabilities on the left, providers on the right, routed independently.
 * The point of the picture is that the lines cross: copy and images need not
 * go to the same vendor.
 */
export function RoutingIllustration({ className }: IllustrationProps) {
  const capabilities = ["Copy", "Images", "Video", "Embeddings"];
  const providers = ["Provider A", "Provider B", "Provider C"];
  // Deliberately not one-to-one: two capabilities share a provider, and one
  // provider serves none until it is needed as failover.
  const routes = [
    [0, 0],
    [1, 1],
    [2, 1],
    [3, 2],
  ];

  const capY = (i: number) => 30 + i * 44;
  const provY = (i: number) => 52 + i * 52;

  return (
    <Figure
      title="Each generation capability routed independently to a configured AI provider"
      viewBox="0 0 420 210"
      className={className}
    >
      {capabilities.map((label, i) => (
        <g key={label}>
          <rect
            x="4"
            y={capY(i) - 15}
            width="112"
            height="30"
            rx="8"
            stroke="currentColor"
            strokeOpacity="0.22"
          />
          <text
            x="18"
            y={capY(i) + 5}
            fill="currentColor"
            fillOpacity="0.75"
            fontSize="12"
            fontFamily="inherit"
          >
            {label}
          </text>
        </g>
      ))}

      {routes.map(([cap, prov]) => (
        <path
          key={`${cap}-${prov}`}
          d={`M116 ${capY(cap!)} C 190 ${capY(cap!)}, 220 ${provY(prov!)}, 288 ${provY(prov!)}`}
          stroke={LIME}
          strokeOpacity="0.55"
          strokeWidth="1.5"
        />
      ))}

      {providers.map((label, i) => (
        <g key={label}>
          <rect
            x="288"
            y={provY(i) - 16}
            width="128"
            height="32"
            rx="8"
            stroke="currentColor"
            strokeOpacity="0.22"
            fill={LIME}
            fillOpacity={i === 2 ? "0" : "0.07"}
          />
          <text
            x="304"
            y={provY(i) + 5}
            fill="currentColor"
            fillOpacity="0.75"
            fontSize="12"
            fontFamily="inherit"
          >
            {label}
          </text>
        </g>
      ))}
    </Figure>
  );
}

/**
 * The approval gate. A draft cannot reach a channel without passing a person,
 * and the rejected path loops back rather than disappearing.
 */
export function ApprovalGateIllustration({ className }: IllustrationProps) {
  return (
    <Figure
      title="A draft passes a human approval gate before publishing; rejected work returns for revision"
      viewBox="0 0 420 180"
      className={className}
    >
      <rect
        x="4"
        y="60"
        width="96"
        height="42"
        rx="10"
        stroke="currentColor"
        strokeOpacity="0.22"
      />
      <text x="24" y="86" fill="currentColor" fillOpacity="0.75" fontSize="12" fontFamily="inherit">
        Draft
      </text>

      <path d="M100 81 H160" stroke="currentColor" strokeOpacity="0.28" strokeWidth="1.5" />

      <rect
        x="160"
        y="52"
        width="104"
        height="58"
        rx="12"
        stroke={LIME}
        strokeWidth="1.5"
        fill={LIME}
        fillOpacity="0.1"
      />
      <text x="180" y="78" fill="currentColor" fontSize="12" fontWeight="600" fontFamily="inherit">
        Approval
      </text>
      <text
        x="180"
        y="95"
        fill="currentColor"
        fillOpacity="0.55"
        fontSize="10"
        fontFamily="inherit"
      >
        a person decides
      </text>

      <path d="M264 81 H320" stroke={LIME} strokeWidth="1.5" />
      <path d="M312 76 L320 81 L312 86" stroke={LIME} strokeWidth="1.5" />
      <rect
        x="322"
        y="60"
        width="94"
        height="42"
        rx="10"
        stroke={LIME}
        strokeWidth="1.5"
        fill={LIME}
        fillOpacity="0.08"
      />
      <text x="340" y="86" fill="currentColor" fontSize="12" fontWeight="600" fontFamily="inherit">
        Published
      </text>

      {/* Rejected: back to the draft, never onward. */}
      <path
        d="M212 110 V142 H52 V102"
        stroke="currentColor"
        strokeOpacity="0.3"
        strokeWidth="1.5"
        strokeDasharray="4 4"
      />
      <path
        d="M47 110 L52 102 L57 110"
        stroke="currentColor"
        strokeOpacity="0.3"
        strokeWidth="1.5"
      />
      <text
        x="112"
        y="158"
        fill="currentColor"
        fillOpacity="0.5"
        fontSize="10"
        fontFamily="inherit"
      >
        rejected or needs edits — with the reason attached
      </text>
    </Figure>
  );
}

/**
 * One approved post fanning out to five channels, each succeeding or failing
 * on its own. The failed row is the point: it does not take the others down.
 */
export function FanOutIllustration({ className }: IllustrationProps) {
  const channels = [
    { label: "Instagram", ok: true },
    { label: "Facebook", ok: true },
    { label: "LinkedIn", ok: true },
    { label: "X", ok: false },
    { label: "YouTube", ok: true },
  ];
  const y = (i: number) => 22 + i * 36;

  return (
    <Figure
      title="One approved post fanning out to five channels, where a single channel failing does not stop the others"
      viewBox="0 0 420 210"
      className={className}
    >
      <rect
        x="4"
        y="82"
        width="112"
        height="44"
        rx="10"
        stroke={LIME}
        strokeWidth="1.5"
        fill={LIME}
        fillOpacity="0.08"
      />
      <text x="22" y="103" fill="currentColor" fontSize="12" fontWeight="600" fontFamily="inherit">
        Approved
      </text>
      <text
        x="22"
        y="118"
        fill="currentColor"
        fillOpacity="0.55"
        fontSize="10"
        fontFamily="inherit"
      >
        one post
      </text>

      {channels.map((channel, i) => (
        <g key={channel.label}>
          <path
            d={`M116 104 C 170 104, 190 ${y(i) + 14}, 236 ${y(i) + 14}`}
            stroke={channel.ok ? LIME : "currentColor"}
            strokeOpacity={channel.ok ? "0.5" : "0.25"}
            strokeWidth="1.5"
            strokeDasharray={channel.ok ? undefined : "4 4"}
          />
          <rect
            x="236"
            y={y(i)}
            width="140"
            height="28"
            rx="8"
            stroke="currentColor"
            strokeOpacity="0.22"
          />
          <circle
            cx="252"
            cy={y(i) + 14}
            r="4"
            fill={channel.ok ? LIME : "currentColor"}
            fillOpacity={channel.ok ? 1 : 0.3}
          />
          <text
            x="266"
            y={y(i) + 18}
            fill="currentColor"
            fillOpacity="0.75"
            fontSize="11"
            fontFamily="inherit"
          >
            {channel.label}
          </text>
          <text
            x="384"
            y={y(i) + 18}
            fill="currentColor"
            fillOpacity="0.45"
            fontSize="9"
            fontFamily="inherit"
          >
            {channel.ok ? "sent" : "retry"}
          </text>
        </g>
      ))}
    </Figure>
  );
}

/**
 * Two workspaces side by side with no path between them. The crossed line is
 * the whole message.
 */
export function IsolationIllustration({ className }: IllustrationProps) {
  const box = (x: number, label: string) => (
    <g>
      <rect
        x={x}
        y="20"
        width="150"
        height="140"
        rx="14"
        stroke="currentColor"
        strokeOpacity="0.22"
      />
      <text
        x={x + 20}
        y="48"
        fill="currentColor"
        fontSize="12"
        fontWeight="600"
        fontFamily="inherit"
      >
        {label}
      </text>
      {["Brand", "Sources", "Content", "Channels"].map((row, i) => (
        <g key={row}>
          <rect
            x={x + 20}
            y={64 + i * 24}
            width="110"
            height="18"
            rx="5"
            fill={LIME}
            fillOpacity="0.1"
          />
          <text
            x={x + 28}
            y={77 + i * 24}
            fill="currentColor"
            fillOpacity="0.6"
            fontSize="9"
            fontFamily="inherit"
          >
            {row}
          </text>
        </g>
      ))}
    </g>
  );

  return (
    <Figure
      title="Two client workspaces with no path for data to travel between them"
      viewBox="0 0 420 190"
      className={className}
    >
      {box(4, "Client A")}
      {box(266, "Client B")}
      <path
        d="M162 90 H258"
        stroke="currentColor"
        strokeOpacity="0.22"
        strokeWidth="1.5"
        strokeDasharray="4 4"
      />
      <g stroke="var(--color-destructive)" strokeWidth="2">
        <path d="M200 78 L220 102" />
        <path d="M220 78 L200 102" />
      </g>
      <text x="168" y="126" fill="currentColor" fillOpacity="0.5" fontSize="9" fontFamily="inherit">
        no shared reads
      </text>
    </Figure>
  );
}

/**
 * A published post traced back through every step that produced it.
 */
export function LineageIllustration({ className }: IllustrationProps) {
  const steps = ["Published post", "Approval", "Draft + model", "Brand fact", "Source document"];

  return (
    <Figure
      title="A published post traced back through its approval, the model that drafted it, and the brand material it drew on"
      viewBox="0 0 420 200"
      className={className}
    >
      {steps.map((step, i) => {
        const y = 16 + i * 36;
        return (
          <g key={step}>
            <circle
              cx="20"
              cy={y + 12}
              r="5"
              fill={i === 0 ? LIME : "currentColor"}
              fillOpacity={i === 0 ? 1 : 0.3}
            />
            {i < steps.length - 1 && (
              <path
                d={`M20 ${y + 17} V ${y + 43}`}
                stroke="currentColor"
                strokeOpacity="0.25"
                strokeWidth="1.5"
              />
            )}
            <rect
              x="40"
              y={y}
              width="330"
              height="24"
              rx="7"
              stroke="currentColor"
              strokeOpacity="0.18"
            />
            <text
              x="54"
              y={y + 16}
              fill="currentColor"
              fillOpacity={i === 0 ? "0.9" : "0.65"}
              fontSize="11"
              fontWeight={i === 0 ? "600" : "400"}
              fontFamily="inherit"
            >
              {step}
            </text>
          </g>
        );
      })}
    </Figure>
  );
}

/**
 * The loop, as a closed ring rather than a line — the shape is the argument.
 */
export function LoopRingIllustration({ className }: IllustrationProps) {
  const stages = ["Learn", "Create", "Review", "Publish", "Improve"];
  const cx = 130;
  const cy = 130;
  const r = 96;

  return (
    <Figure
      title="The five stage marketing loop: learn, create, review, publish, improve"
      viewBox="0 0 260 260"
      className={className}
    >
      <circle cx={cx} cy={cy} r={r} stroke="currentColor" strokeOpacity="0.18" strokeWidth="1.5" />
      {stages.map((stage, i) => {
        const angle = (i / stages.length) * Math.PI * 2 - Math.PI / 2;
        const x = cx + Math.cos(angle) * r;
        const y = cy + Math.sin(angle) * r;
        return (
          <g key={stage}>
            <circle cx={x} cy={y} r="7" fill={LIME} />
            <text
              x={x}
              y={y - 16}
              fill="currentColor"
              fillOpacity="0.8"
              fontSize="12"
              fontWeight="600"
              textAnchor="middle"
              fontFamily="inherit"
            >
              {stage}
            </text>
          </g>
        );
      })}
      <text
        x={cx}
        y={cy - 4}
        fill="currentColor"
        fillOpacity="0.5"
        fontSize="11"
        textAnchor="middle"
        fontFamily="inherit"
      >
        every result
      </text>
      <text
        x={cx}
        y={cy + 14}
        fill="currentColor"
        fillOpacity="0.5"
        fontSize="11"
        textAnchor="middle"
        fontFamily="inherit"
      >
        returns to the brand
      </text>
    </Figure>
  );
}

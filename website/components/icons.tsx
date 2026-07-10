type IconProps = { size?: number };

function Svg({ size = 20, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function MicIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </Svg>
  );
}

export function MicOffIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
      <path d="M4 4l16 16" />
    </Svg>
  );
}

export function CamIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="7" width="12" height="10" rx="2" />
      <path d="m15 11 5-3v8l-5-3" />
    </Svg>
  );
}

export function CamOffIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="3" y="7" width="12" height="10" rx="2" />
      <path d="m15 11 5-3v8l-5-3" />
      <path d="M4 4l16 16" />
    </Svg>
  );
}

export function VolumeIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M11 5 6 9H3v6h3l5 4z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
    </Svg>
  );
}

export function VolumeOffIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M11 5 6 9H3v6h3l5 4z" />
      <path d="m16 9 5 5" />
      <path d="m21 9-5 5" />
    </Svg>
  );
}

export function EndIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M8 12a14 14 0 0 1 8 0" />
      <path d="M2 13c0-2 4-5 10-5s10 3 10 5c0 1-1 3-2.5 2.5L16 14.5v-2" />
      <path d="M8 12.5v2l-3.5 1C3 16 2 14 2 13" />
    </Svg>
  );
}

export function SparkIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 3.5 13.8 9.2 19.5 11 13.8 12.8 12 18.5 10.2 12.8 4.5 11 10.2 9.2z" />
    </Svg>
  );
}

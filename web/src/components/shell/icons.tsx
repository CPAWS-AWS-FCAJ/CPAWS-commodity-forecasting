import type { SVGProps } from "react";

// Icon SVG nội tuyến tối giản (không dùng thư viện icon): 16 px, nét 1.5, màu theo chữ.
type IconProps = SVGProps<SVGSVGElement>;

function Svg({ children, className = "", ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={`shrink-0 ${className}`.trim()}
      {...props}
    >
      {children}
    </svg>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />
    </Svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </Svg>
  );
}

export function SunIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="2.75" />
      <path d="M8 1.5v1.25M8 13.25v1.25M1.5 8h1.25M13.25 8h1.25M3.4 3.4l.9.9M11.7 11.7l.9.9M3.4 12.6l.9-.9M11.7 4.3l.9-.9" />
    </Svg>
  );
}

export function MoonIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13.5 9.6A5.75 5.75 0 016.4 2.5a5.75 5.75 0 107.1 7.1z" />
    </Svg>
  );
}

export function LockIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3.25" y="7" width="9.5" height="6.75" rx="1.25" />
      <path d="M5.5 7V5a2.5 2.5 0 015 0v2" />
    </Svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 3.5L10.5 8 6 12.5" />
    </Svg>
  );
}

export function SignOutIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6.5 2.75H4A1.25 1.25 0 002.75 4v8A1.25 1.25 0 004 13.25h2.5M10 5l3 3-3 3M13 8H6.5" />
    </Svg>
  );
}

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

/** Thu gọn/mở sidebar desktop: khung có cột trái; mũi tên đổi chiều theo trạng thái. */
export function SidebarToggleIcon({ collapsed = false, ...props }: IconProps & { collapsed?: boolean }) {
  return (
    <Svg {...props}>
      <rect x="2" y="2.75" width="12" height="10.5" rx="1.5" />
      <path d="M6 2.75v10.5" />
      <path d={collapsed ? "M9 6.25L10.75 8 9 9.75" : "M10.75 6.25L9 8l1.75 1.75"} />
    </Svg>
  );
}

export function OverviewIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.5 13.5h11" />
      <path d="M3 10.5l3-3.25 2.5 2 4.5-5" />
    </Svg>
  );
}

export function ForecastIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.5 9.5h4" />
      <path d="M6.5 9.5l7-5M6.5 9.5l7 0M6.5 9.5l7 4" />
    </Svg>
  );
}

export function AccuracyIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="5.75" />
      <circle cx="8" cy="8" r="2.5" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2" />
    </Svg>
  );
}

export function GuideIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 4.25C6.75 3.25 4.75 3 2.5 3.25v9c2.25-.25 4.25 0 5.5 1 1.25-1 3.25-1.25 5.5-1v-9C11.25 3 9.25 3.25 8 4.25z" />
      <path d="M8 4.25v9" />
    </Svg>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="8" cy="8" r="5.75" />
      <path d="M8 7.25v3.5M8 5.1v.01" />
    </Svg>
  );
}

export function SignInIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.5 2.75H12A1.25 1.25 0 0113.25 4v8A1.25 1.25 0 0112 13.25H9.5M6 5l3 3-3 3M9 8H2.5" />
    </Svg>
  );
}

export function UserPlusIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="6.5" cy="5.5" r="2.5" />
      <path d="M2 13.25c.5-2.25 2.25-3.5 4.5-3.5s4 1.25 4.5 3.5M12.5 4.5v4M10.5 6.5h4" />
    </Svg>
  );
}

export function ExpandIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5L9 7M2.5 13.5L7 9" />
    </Svg>
  );
}

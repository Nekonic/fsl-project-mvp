import type { JSX } from "preact";

const SHAPES = {
  brand: <><path d="M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-4" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  map: <><rect x="9" y="2" width="6" height="5" rx="1" /><rect x="2" y="17" width="6" height="5" rx="1" /><rect x="16" y="17" width="6" height="5" rx="1" /><path d="M12 7v5M5 17v-5h14v5" /></>,
  rules: <><path d="M4 4h16v16H4z" /><path d="M8 9h8M8 13h8M8 17h5" /></>,
  shield: <path d="M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6l-8-3Z" />,
  bell: <><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></>,
  terminal: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="m7 9 3 3-3 3M13 15h4" /></>,
  prompt: <path d="m5 7 5 5-5 5M12 18h7" />,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>,
  upload: <path d="M12 19V5M5 12l7-7 7 7" />,
  flag: <><path d="M5 21V4" /><path d="M5 4h11l-2 4 2 4H5" /></>,
  heart: <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" />,
  score: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
  steps: <><path d="M9 6h11M9 12h11M9 18h11" /><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2" /></>,
  folded: <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2Z M9 4v14M15 6v14" />,
  code: <path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14" />,
  window: <><path d="M4 6h16v12H4z" /><path d="m8 10 2 2-2 2M12 14h4" /></>,
  database: <><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></>,
  alarm: <><path d="M12 3 4 6v6c0 4.4 3.4 8.3 8 9 4.6-.7 8-4.6 8-9V6l-8-3Z" /><path d="M12 8v5M12 16h.01" /></>,
  swords: <><path d="M14.5 17.5 3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2" /><path d="M9.5 6.5 14 2h3v3l-4.5 4.5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  check: <path d="m5 12 5 5 9-10" />,
  chevrons: <path d="m7 6 6 6-6 6M13 6l6 6-6 6" />,
} satisfies Record<string, JSX.Element>;

export type IconName = keyof typeof SHAPES;

export interface IconProps {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      {SHAPES[name]}
    </svg>
  );
}

export function HeroArt({ size = 170 }: { size?: number }) {
  return (
    <svg class="hero-art" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 2.5 4.5 5.5v6c0 4.6 3.2 8.7 7.5 9.9 4.3-1.2 7.5-5.3 7.5-9.9v-6L12 2.5Z" fill="var(--hero-art-fill)" stroke="var(--hero-art-line)" stroke-width="0.8" />
      <path d="M12 2.5v18.9c4.3-1.2 7.5-5.3 7.5-9.9v-6L12 2.5Z" fill="var(--hero-art-shade)" />
      <path d="m8.6 12 2.4 2.4 4.6-4.8" stroke="var(--lime)" stroke-width="1.6" stroke-linecap="round" />
    </svg>
  );
}

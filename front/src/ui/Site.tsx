import type { ComponentChildren, Ref } from "preact";

export function SiteSplit({ children }: { children: ComponentChildren }) {
  return <div class="site-split">{children}</div>;
}

export function SideList({ children }: { children: ComponentChildren }) {
  return <div class="side-list">{children}</div>;
}

export function SiteBar({ children }: { children: ComponentChildren }) {
  return <div class="pane-bar site-bar">{children}</div>;
}

export function SiteAddress({ warning, children }: { warning?: ComponentChildren; children: ComponentChildren }) {
  return (
    <label class="site-address">
      {warning && <span class="site-address-warning">{warning}</span>}
      {children}
    </label>
  );
}

export function SiteFrame({ src, title, frameRef, onLoad }: { src: string; title: string; frameRef: Ref<HTMLIFrameElement>; onLoad: () => void }) {
  return <iframe ref={frameRef} class="site-frame" src={src} title={title} sandbox="allow-forms allow-same-origin" onLoad={onLoad} />;
}

export function PaneColumn({ children }: { children: ComponentChildren }) {
  return <div class="pane-column">{children}</div>;
}

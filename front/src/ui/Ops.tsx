import type { ComponentChildren, Ref } from "preact";
import { Dot, type DotTone } from "./Badge";
import { Row, Stack } from "./Card";
import { Text } from "./Text";

export function OpRow({ title, actions, children }: { title?: ComponentChildren; actions?: ComponentChildren; children?: ComponentChildren }) {
  return (
    <div class="op-row">
      {title && <h2 class="op-name">{title}</h2>}
      {children}
      {actions && <div class="op-actions">{actions}</div>}
    </div>
  );
}

export interface ServerDot {
  host: string;
  title?: string;
  tone: DotTone;
}

export function ServerDots({ servers }: { servers: ServerDot[] }) {
  return (
    <span class="servers">
      {servers.map((server) => <span key={server.host} title={server.title}><Dot tone={server.tone} />{server.host}</span>)}
    </span>
  );
}

export function IdentityCell({ name }: { name: string }) {
  return (
    <Row>
      <span class="avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
      <Text strong tone="heading" cut>{name}</Text>
    </Row>
  );
}

export function RowActions({ error, children }: { error?: ComponentChildren; children: ComponentChildren }) {
  return (
    <>
      <Row>{children}</Row>
      {error && <p class="row-error">{error}</p>}
    </>
  );
}

export function FormErrorLines({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return <Stack gap="sm">{lines.map((line, index) => <Text key={index} tone="danger" small>{line}</Text>)}</Stack>;
}

export interface MapFrameProps {
  gridRef?: Ref<HTMLDivElement>;
  canvasRef?: Ref<HTMLDivElement>;
  zoomIn?: { label: string; onClick: () => void };
  zoomOut?: { label: string; onClick: () => void };
  message?: ComponentChildren;
}

export function MapFrame({ gridRef, canvasRef, zoomIn, zoomOut, message }: MapFrameProps) {
  return (
    <div class="map" ref={gridRef}>
      {message !== undefined ? <p class="map-said">{message}</p> : <div class="map-canvas" ref={canvasRef} />}
      {zoomIn && zoomOut && (
        <div class="map-zoom">
          <button type="button" aria-label={zoomIn.label} onClick={zoomIn.onClick}>+</button>
          <button type="button" aria-label={zoomOut.label} onClick={zoomOut.onClick}>−</button>
        </div>
      )}
    </div>
  );
}

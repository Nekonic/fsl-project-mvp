import type cytoscapeFactory from "cytoscape";
import type { Core, ElementDefinition, NodeSingular, StylesheetJson } from "cytoscape";
import { useEffect, useRef, useState } from "preact/hooks";
import { useResource } from "../api/hooks";
import { usePaneShownAgain } from "../router";
import { errorText, hasString, t } from "../strings";
import { MapFrame, Pane } from "../ui";
import type { PaneProps } from "./types";

export interface MapZone {
  id: string;
  caption: string;
  subnet: string;
  owner?: string;
  box: [number, number, number, number];
  shift?: number;
}

export interface MapNode {
  id: string;
  kind: string;
  name?: string;
  zone?: string;
  x?: number;
  y?: number;
  label?: string;
  text?: string;
  more?: number;
}

export interface MapEdge {
  id: string;
  kind: string;
  source: string;
  target: string;
  route?: Array<[number, number]>;
  start?: [number, number];
  end?: [number, number];
}

export interface LearnerMap {
  zones: MapZone[];
  nodes: MapNode[];
  edges: MapEdge[];
}

const SYMBOL_FILES = import.meta.glob<string>("./map-symbols/node-*.svg", { query: "?raw", import: "default" });
const MARGIN = 24;
const GRID = 22;
const FLOW_EVERY_MS = 40;
const ZOOM_IN = 1.25;
const ZOOM_OUT = 0.8;

const LABEL_SIDES: Record<string, Record<string, string | number>> = {
  above: { "text-valign": "top", "text-halign": "center", "text-margin-x": 0, "text-margin-y": -6 },
  below: { "text-valign": "bottom", "text-halign": "center", "text-margin-x": 0, "text-margin-y": 6 },
  left: { "text-valign": "center", "text-halign": "left", "text-margin-x": -8, "text-margin-y": 0 },
  right: { "text-valign": "center", "text-halign": "right", "text-margin-x": 8, "text-margin-y": 0 },
};

type Symbols = Record<string, string>;

interface Palette {
  zones: Record<string, string>;
  symbols: Symbols;
  link: string;
  lit: string;
  logs: string;
  ink: string;
  chip: string;
  chipLine: string;
  address: string;
  background: string;
  sans: string;
  mono: string;
  text: number;
  zoneText: number;
  addressText: number;
  zoneRadius: number;
  routeRadius: number;
  zoneFillOpacity: number;
  zoneLineOpacity: number;
  zoneCaptionLineOpacity: number;
  litOpacity: number;
}

function token(style: CSSStyleDeclaration, name: string): string {
  return style.getPropertyValue(name).trim();
}

function amount(style: CSSStyleDeclaration, name: string): number {
  return Number.parseFloat(token(style, name));
}

async function symbolFiles(): Promise<Symbols> {
  const read = await Promise.all(Object.entries(SYMBOL_FILES).map(async ([path, load]) => [/node-(\w+)\.svg$/.exec(path)?.[1] ?? path, await load()]));
  return Object.fromEntries(read);
}

function painted(files: Symbols, style: CSSStyleDeclaration): Symbols {
  return Object.fromEntries(Object.entries(files).map(([kind, svg]) => [kind,
    `data:image/svg+xml;utf8,${encodeURIComponent(svg.replace(/var\((--[\w-]+)\)/g, (whole, name: string) => token(style, name) || whole))}`]));
}

function paletteOf(element: Element, files: Symbols): Palette {
  const style = getComputedStyle(element);
  return {
    symbols: painted(files, style),
    zones: {
      internet: token(style, "--map-internet"),
      dmz: token(style, "--map-dmz"),
      web: token(style, "--map-web"),
      database: token(style, "--map-database"),
      mgmt: token(style, "--map-mgmt"),
    },
    link: token(style, "--map-link"),
    lit: token(style, "--map-lit"),
    logs: token(style, "--map-logs"),
    ink: token(style, "--map-ink"),
    chip: token(style, "--map-chip"),
    chipLine: token(style, "--map-chip-line"),
    address: token(style, "--map-address"),
    background: token(style, "--map-bg"),
    sans: token(style, "--font-sans"),
    mono: token(style, "--font-mono"),
    text: amount(style, "--map-text"),
    zoneText: amount(style, "--map-zone-text"),
    addressText: amount(style, "--map-address-text"),
    zoneRadius: amount(style, "--map-zone-radius"),
    routeRadius: amount(style, "--map-route-radius"),
    zoneFillOpacity: amount(style, "--map-zone-fill-opacity"),
    zoneLineOpacity: amount(style, "--map-zone-line-opacity"),
    zoneCaptionLineOpacity: amount(style, "--map-zone-caption-line-opacity"),
    litOpacity: amount(style, "--map-lit-opacity"),
  };
}

export function zoneCaption(zone: MapZone): string {
  const key = `topology.zone.${zone.caption}`;
  const caption = hasString(key) ? t(key, { owner: zone.owner ?? "" }) : zone.caption;
  return [caption, zone.subnet].filter(Boolean).join(" ");
}

export function nodeLabel(node: MapNode): string {
  if (node.kind === "address") return node.more ? t("topology.address_more", { address: node.text ?? "", more: node.more }) : node.text ?? "";
  const key = node.kind === "sensor" ? "topology.sensor" : `topology.name.${node.name ?? ""}`;
  return hasString(key) ? t(key) : node.name ?? "";
}

function classOf(node: MapNode): string {
  if (node.kind === "switch" || node.kind === "address") return node.kind;
  return `device ${node.kind}`;
}

function bends(route: Array<[number, number]>, from: { x: number; y: number }, to: { x: number; y: number }) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  return route.map(([x, y]) => ({
    weight: ((x - from.x) * dx + (y - from.y) * dy) / (length * length),
    distance: ((y - from.y) * dx - (x - from.x) * dy) / length,
  }));
}

export function elementsOf(map: LearnerMap, palette: Palette): ElementDefinition[] {
  const at = Object.fromEntries(map.nodes.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]));
  const zones: ElementDefinition[] = map.zones.map((zone) => {
    const [x1, y1, x2, y2] = zone.box;
    return {
      group: "nodes", classes: "zone", position: { x: (x1 + x2) / 2, y: (y1 + y2) / 2 },
      data: { id: `zone:${zone.id}`, label: zoneCaption(zone), colour: palette.zones[zone.caption] || palette.logs, shift: zone.shift ?? 0, width: x2 - x1, height: y2 - y1 },
    };
  });
  const nodes: ElementDefinition[] = map.nodes.map((node) => ({
    group: "nodes", classes: classOf(node), position: at[node.id],
    data: { id: node.id, label: nodeLabel(node), name: node.name ?? "", side: node.label ?? "below", symbol: palette.symbols[node.kind] ?? palette.symbols.host },
  }));
  const edges: ElementDefinition[] = map.edges.map((edge) => {
    const from = at[edge.source] ?? { x: 0, y: 0 };
    const to = at[edge.target] ?? { x: 0, y: 0 };
    const route = edge.route ? bends(edge.route, from, to) : [];
    return {
      group: "edges", classes: edge.route ? `${edge.kind} routed` : edge.kind,
      data: {
        id: edge.id, source: edge.source, target: edge.target,
        weights: route.map((bend) => bend.weight), distances: route.map((bend) => bend.distance),
        start: edge.start ? `${edge.start[0]}px ${edge.start[1]}px` : "outside-to-node",
        end: edge.end ? `${edge.end[0]}px ${edge.end[1]}px` : "outside-to-node",
      },
    };
  });
  return [...zones, ...nodes, ...edges];
}

function stylesOf(palette: Palette): StylesheetJson {
  return [
    { selector: "node", style: { "font-family": palette.sans, "font-size": palette.text, color: palette.ink } },
    { selector: "node.zone", style: {
      shape: "round-rectangle", "corner-radius": palette.zoneRadius, width: "data(width)", height: "data(height)", "background-color": "data(colour)",
      "background-opacity": palette.zoneFillOpacity, "border-width": 1.5, "border-color": "data(colour)", "border-opacity": palette.zoneLineOpacity, label: "data(label)",
      "text-valign": "top", "text-halign": "center", "font-size": palette.zoneText, "font-weight": 600, color: "data(colour)",
      "text-margin-x": "data(shift)", "text-margin-y": 11, "text-background-color": palette.chip, "text-background-shape": "round-rectangle",
      "text-background-opacity": 1, "text-background-padding": 5, "text-border-width": 1, "text-border-color": "data(colour)",
      "text-border-opacity": palette.zoneCaptionLineOpacity, "z-compound-depth": "bottom", "z-index": 0, events: "no" } },
    { selector: "node.device, node.switch", style: {
      shape: "round-rectangle", width: 52, height: 52, "background-opacity": 0, "border-width": 0,
      "background-image": "data(symbol)", "background-fit": "contain", "background-clip": "none", "z-index": 10,
      "underlay-color": palette.lit, "underlay-padding": 4, "underlay-opacity": 0, "underlay-shape": "round-rectangle" } },
    { selector: "node.device", style: { label: "data(label)", "text-wrap": "wrap", "line-height": 1.35, "font-weight": 600,
      "text-background-color": palette.chip, "text-background-opacity": 1, "text-background-padding": 3,
      "text-background-shape": "round-rectangle" } },
    { selector: "node.device.lit, node.switch.lit", style: { "underlay-opacity": palette.litOpacity } },
    ...Object.entries(LABEL_SIDES).map(([side, style]) => ({ selector: `node.device[side = "${side}"]`, style })),
    { selector: "edge", style: { width: 2, "curve-style": "straight", "line-color": palette.link, "font-family": palette.sans,
      "z-index": 5, "source-endpoint": "data(start)", "target-endpoint": "data(end)", "line-cap": "round" } },
    { selector: "edge.mirror", style: { "line-style": "dashed", "line-dash-pattern": [6, 5] } },
    { selector: "edge.lit", style: { "line-color": palette.lit, width: 2.5, "line-style": "dashed", "line-dash-pattern": [7, 5], "z-index": 6 } },
    { selector: "edge.routed", style: {
      "curve-style": "segments", "edge-distances": "node-position", "segment-weights": "data(weights)",
      "segment-distances": "data(distances)", "segment-radii": palette.routeRadius, "radius-type": "arc-radius" } },
    { selector: "node.address", style: { width: 1, height: 1, "background-opacity": 0, "border-width": 0,
      label: "data(label)", "text-valign": "center", color: palette.address, "font-size": palette.addressText, "font-family": palette.mono,
      "text-background-color": palette.background, "text-background-shape": "round-rectangle", "text-background-opacity": 1,
      "text-background-padding": 3, "text-border-width": 1, "text-border-color": palette.chipLine, "text-border-opacity": 1, events: "no" } },
    { selector: 'node.address[side = "right"]', style: { "text-halign": "right" } },
    { selector: 'node.address[side = "left"]', style: { "text-halign": "left" } },
  ] as unknown as StylesheetJson;
}

function asMap(said: unknown): LearnerMap | null {
  const map = said as Partial<LearnerMap> | undefined;
  if (!map || !Array.isArray(map.nodes) || !Array.isArray(map.zones) || !Array.isArray(map.edges) || !map.nodes.length) return null;
  return map as LearnerMap;
}

function drawn(cytoscape: typeof cytoscapeFactory, files: Symbols, container: HTMLElement, grid: HTMLElement, map: LearnerMap): Core {
  const palette = paletteOf(container, files);
  const cy = cytoscape({
    container, elements: elementsOf(map, palette), style: stylesOf(palette), layout: { name: "preset" },
    autoungrabify: true, autounselectify: true, boxSelectionEnabled: false, minZoom: 0.3, maxZoom: 2.5,
  });
  let flowing: ReturnType<typeof setInterval> | undefined;
  const lit = (node: NodeSingular, on: boolean) => {
    node.closedNeighborhood().toggleClass("lit", on);
    clearInterval(flowing);
    if (!on) return;
    let offset = 0;
    flowing = setInterval(() => {
      offset = (offset + 1) % 24;
      cy.edges(".lit").style("line-dash-offset", -offset);
    }, FLOW_EVERY_MS);
  };
  cy.on("mouseover", "node.device, node.switch", (event) => lit(event.target as NodeSingular, true));
  cy.on("mouseout", "node.device, node.switch", (event) => lit(event.target as NodeSingular, false));
  cy.on("viewport", () => {
    const step = GRID * cy.zoom();
    const pan = cy.pan();
    grid.style.backgroundSize = `${step}px ${step}px`;
    grid.style.backgroundPosition = `${pan.x}px ${pan.y}px`;
  });
  cy.on("destroy", () => clearInterval(flowing));
  cy.fit(undefined, MARGIN);
  return cy;
}

export function TopologyView({ map }: { map: LearnerMap }) {
  const grid = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const view = useRef<Core | null>(null);

  useEffect(() => {
    const container = canvas.current;
    const backdrop = grid.current;
    if (!container || !backdrop) return undefined;
    let gone = false;
    let resized: ResizeObserver | undefined;
    void Promise.all([import("cytoscape"), symbolFiles()]).then(([{ default: cytoscape }, files]) => {
      if (gone) return;
      const cy = drawn(cytoscape, files, container, backdrop, map);
      view.current = cy;
      resized = new ResizeObserver(() => {
        if (container.clientWidth === 0) return;
        cy.resize();
        cy.fit(undefined, MARGIN);
      });
      resized.observe(container);
    });
    return () => {
      gone = true;
      resized?.disconnect();
      view.current?.destroy();
      view.current = null;
    };
  }, [map]);

  const zoom = (by: number) => {
    const cy = view.current;
    if (!cy) return;
    const level = Math.min(cy.maxZoom(), Math.max(cy.minZoom(), cy.zoom() * by));
    cy.zoom({ level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  };

  return (
    <MapFrame gridRef={grid} canvasRef={canvas}
      zoomIn={{ label: t("topology.zoom_in"), onClick: () => zoom(ZOOM_IN) }}
      zoomOut={{ label: t("topology.zoom_out"), onClick: () => zoom(ZOOM_OUT) }} />
  );
}

export function MapPane({ round }: PaneProps) {
  const topology = useResource("/api/rounds/{round_id}/topology/", { params: { round_id: round } });
  usePaneShownAgain("map", topology.reload);
  const [map, setMap] = useState<LearnerMap | null>(null);
  useEffect(() => setMap(asMap(topology.data)), [topology.data]);
  return (
    <Pane scroll={false}>
      {map
        ? <TopologyView map={map} />
        : (
          <MapFrame message={topology.error ? t("topology.unread", { reason: errorText(topology.error) }) : topology.loading ? t("topology.loading") : t("topology.empty")} />
        )}
    </Pane>
  );
}

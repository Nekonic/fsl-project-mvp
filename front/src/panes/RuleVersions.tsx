import type { Schemas } from "../api/client";
import { useResource } from "../api/hooks";
import { clock } from "../format";
import { t, tFor, type StringKey } from "../strings";
import { AsideCard, ErrorNotice, Loading, Pane, RowLine, Table, Text, type Column, type TextTone } from "../ui";
import type { PaneProps } from "./types";

export type Engine = "ids" | "waf";
export type AppliedVersion = Schemas["AppliedVersion"];

export interface EngineVersion extends AppliedVersion {
  engine: Engine;
}

const VERSIONS_PATH = {
  ids: "/api/rounds/{round_id}/defence/ids/rules/versions/",
  waf: "/api/rounds/{round_id}/defence/waf/versions/",
} as const;

const APPLY_EVENTS = ["rule.applied", "round.ended"];

export function useRuleVersions(round: number, engine: Engine) {
  const shown = useResource(VERSIONS_PATH[engine], { params: { round_id: round } }, { refreshOn: { round, kinds: APPLY_EVENTS } });
  const versions: EngineVersion[] = (shown.data ?? []).map((one) => ({ ...one, engine }));
  const head = versions.reduce<EngineVersion | undefined>((best, one) => (!best || one.version > best.version ? one : best), undefined);
  return { versions, head, error: shown.error, loading: shown.loading && !shown.data, reload: shown.reload };
}

export function versionNoteKey(version: AppliedVersion): StringKey {
  if (version.tested === null) return version.source === "setup" ? "versions.starting_rules" : "versions.untested";
  return version.same_as_tested ? "versions.same_as_tested" : "versions.not_same_as_tested";
}

const NOTE_TONE: Partial<Record<StringKey, TextTone>> = {
  "versions.untested": "warn",
  "versions.starting_rules": "muted",
  "versions.same_as_tested": "ok",
  "versions.not_same_as_tested": "warn",
};

export function VersionNote({ version }: { version: AppliedVersion }) {
  const key = versionNoteKey(version);
  return <Text tone={NOTE_TONE[key]}>{t(key)}</Text>;
}

export function AppliedMeta({ head, loading }: { head: AppliedVersion | undefined; loading: boolean }) {
  if (loading) return <>{t("common.loading")}</>;
  if (!head) return <>{t("versions.initial")}</>;
  return (
    <>
      {t("versions.applied", { version: head.version })} · <Text mono>{clock(head.applied_at)}</Text> · {t(versionNoteKey(head))}
    </>
  );
}

function engineLabel(engine: Engine): string {
  return tFor("engine", engine);
}

const COLUMNS: Column<EngineVersion>[] = [
  { key: "engine", label: t("col.engine"), cell: (row) => engineLabel(row.engine) },
  { key: "version", label: t("versions.col.version"), kind: "num", cell: (row) => row.version },
  { key: "at", label: t("versions.col.applied_at"), kind: "mono", cell: (row) => clock(row.applied_at) },
  { key: "source", label: t("versions.col.source"), cell: (row) => tFor("versions.source", row.source) },
  { key: "sha", label: t("versions.col.sha"), kind: "mono", cell: (row) => row.sha.slice(0, 12) },
  { key: "note", label: t("versions.col.tested"), cell: (row) => <VersionNote version={row} /> },
];

export function RuleVersions({ round, placement }: PaneProps) {
  const ids = useRuleVersions(round, "ids");
  const waf = useRuleVersions(round, "waf");
  const all = [...ids.versions, ...waf.versions].sort((a, b) => b.applied_at.localeCompare(a.applied_at));
  const error = ids.error ?? waf.error;
  const loading = ids.loading || waf.loading;
  const body = loading ? <Loading>{t("common.loading")}</Loading> : error ? <ErrorNotice error={error} /> : null;

  if (placement === "main") {
    return (
      <Pane title={t("pane.applied")}>
        {body ?? <Table columns={COLUMNS} rows={all} rowKey={(row) => `${row.engine}-${row.version}`} variant="grid" empty={t("versions.none")} />}
      </Pane>
    );
  }
  return (
    <AsideCard title={t("pane.applied")}>
      {body ?? (all.length ? all.map((row) => (
        <RowLine key={`${row.engine}-${row.version}`}>
          <span><Text tone="muted">{engineLabel(row.engine)} {row.version}</Text> <Text mono>{clock(row.applied_at)}</Text></span>
          <VersionNote version={row} />
        </RowLine>
      )) : <Text tone="muted">{t("versions.none")}</Text>)}
    </AsideCard>
  );
}

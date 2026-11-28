import { useEffect, useState } from "preact/hooks";
import { api, RULE_TEST_TIMEOUT_MS, type Schemas } from "../api/client";
import { useEvents, useResource } from "../api/hooks";
import { clock } from "../format";
import { usePaneShownAgain } from "../router";
import { t, tFor } from "../strings";
import { Badge, Banner, Button, Code, CodeEditor, ErrorNotice, Loading, Notice, Pane, PaneSection, Select, Table, Text, type Column } from "../ui";
import { AppliedMeta, VersionNote, useRuleVersions, type AppliedVersion } from "./RuleVersions";
import { BenchButtons, BenchOutcome, RuleTestSection, fileName, rememberTest, useLatestTest, useRuleBench, type BenchCalls } from "./RuleBench";
import type { PaneProps } from "./types";

type WafFile = Schemas["WafFile"];

const BELOW_FLOOR = "limit.below_floor";
const SHARED_KEY = "limit.shared_key";

function asMap(files: WafFile[]): Record<string, string> {
  return Object.fromEntries(files.map((one) => [one.path, one.text]));
}

function contentOf(files: Record<string, string>): string {
  return JSON.stringify(Object.entries(files).sort(([one], [other]) => one.localeCompare(other)));
}

function changedOf(draft: Record<string, string>, live: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(draft).filter(([path, text]) => live[path] !== text));
}

function draftKey(round: number): string {
  return `cr.waf_draft.${round}`;
}

export function keepDraft(round: number, base: number, changed: Record<string, string>): void {
  try {
    if (Object.keys(changed).length) localStorage.setItem(draftKey(round), JSON.stringify({ base, files: changed }));
    else localStorage.removeItem(draftKey(round));
  } catch {
    return;
  }
}

export function keptDraft(round: number, base: number, live: Record<string, string>): Record<string, string> {
  try {
    const held = JSON.parse(localStorage.getItem(draftKey(round)) ?? "null") as { base?: unknown; files?: unknown } | null;
    if (!held || held.base !== base || typeof held.files !== "object" || held.files === null) return live;
    const files = Object.entries(held.files as Record<string, unknown>)
      .filter((entry): entry is [string, string] => entry[0] in live && typeof entry[1] === "string");
    return { ...live, ...Object.fromEntries(files) };
  } catch {
    return live;
  }
}

function StoredVersion({ round, version }: { round: number; version: number }) {
  const shown = useResource("/api/rounds/{round_id}/defence/waf/versions/{version}/", { params: { round_id: round, version } });
  const [path, setPath] = useState<string | null>(null);
  if (shown.error) return <ErrorNotice error={shown.error} />;
  if (!shown.data) return <Loading>{t("common.loading")}</Loading>;
  const files = shown.data.files;
  const chosen = files.find((one) => one.path === path) ?? files[0];
  return (
    <PaneSection title={t("waf.version.title", { version })} meta={<Text mono small>{shown.data.sha.slice(0, 12)}</Text>}>
      <Select mono value={chosen?.path ?? ""} label={t("waf.file")} onValue={setPath}
        options={files.map((one) => ({ value: one.path, label: fileName(one.path) }))} />
      {chosen && <Code>{chosen.text || t("waf.file.empty")}</Code>}
    </PaneSection>
  );
}

export function Waf({ round }: PaneProps) {
  const read = useResource("/api/rounds/{round_id}/defence/waf/", { params: { round_id: round } }, { refreshOn: { round, kinds: ["rule.applied", "rule.refused"] } });
  const versions = useRuleVersions(round, "waf");
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [path, setPath] = useState<string>("");
  const [base, setBase] = useState(0);
  const [opened, setOpened] = useState<number | null>(null);
  const live = read.data ? asMap(read.data.files) : {};
  const changed = draft ? changedOf(draft, live) : {};
  const body = JSON.stringify(changed);
  const bench = useRuleBench(body);

  useEffect(() => {
    if (!read.data) return;
    setDraft(keptDraft(round, read.data.version, asMap(read.data.files)));
    setBase(read.data.version);
    setPath((was) => was || read.data?.files[0]?.path || "");
  }, [read.data]);

  usePaneShownAgain("waf", read.reload);
  const content = draft === null ? null : contentOf(draft);
  useLatestTest({ round, engine: "waf", content, body, liveBody: JSON.stringify({}), head: versions.head, recorded: read.data?.recorded, bench });

  const calls: BenchCalls = {
    check: () => api.post("/api/rounds/{round_id}/defence/waf/check/", { params: { round_id: round }, body: { files: changed } }),
    test: async () => {
      const said = await api.post("/api/rounds/{round_id}/defence/waf/test/", { params: { round_id: round }, body: { files: changed }, timeoutMs: RULE_TEST_TIMEOUT_MS });
      if (said.ok && content !== null) rememberTest(round, "waf", content, said.test);
      return said;
    },
    apply: async (tested) => {
      const said = await api.post("/api/rounds/{round_id}/defence/waf/apply/", { params: { round_id: round }, body: { files: changed, base_version: base, tested } });
      keepDraft(round, said.version, {});
      setBase(said.version);
      versions.reload();
      read.reload();
      return said;
    },
  };

  const badLines = new Set(bench.problems.filter((problem) => problem.path === path).map((problem) => problem.line)
    .filter((line): line is number => typeof line === "number"));
  const fileOptions = (read.data?.files ?? []).map((one) => ({
    value: one.path,
    label: `${fileName(one.path)}${changed[one.path] !== undefined ? ` · ${t("waf.file.edited")}` : ""}`,
  }));

  const versionColumns: Column<AppliedVersion>[] = [
    { key: "version", label: t("versions.col.version"), kind: "num", cell: (row) => row.version },
    { key: "at", label: t("versions.col.applied_at"), kind: "mono", cell: (row) => clock(row.applied_at) },
    { key: "source", label: t("versions.col.source"), cell: (row) => <Badge>{tFor("versions.source", row.source)}</Badge> },
    { key: "sha", label: t("versions.col.sha"), kind: "mono", cell: (row) => row.sha.slice(0, 12) },
    { key: "note", label: t("versions.col.tested"), cell: (row) => <VersionNote version={row} /> },
    { key: "open", label: "", kind: "end", cell: (row) => <Button small onClick={() => setOpened(opened === row.version ? null : row.version)}>{t(opened === row.version ? "waf.version.close" : "waf.version.open")}</Button> },
  ];

  return (
    <Pane title={t("pane.waf")} meta={<AppliedMeta head={versions.head} loading={versions.loading} />}
      actions={<BenchButtons bench={bench} calls={calls} disabled={draft === null || !Object.keys(changed).length} />}>
      {read.error && <ErrorNotice error={read.error} />}
      {draft === null ? (read.error ? null : <Loading>{t("common.loading")}</Loading>) : (
        <PaneSection>
          {read.data && !read.data.recorded && <Notice tone="warn">{t("waf.not_running")}</Notice>}
          <Select mono value={path} options={fileOptions} label={t("waf.file")} onValue={setPath} />
          <Text tone="muted" small mono>{path}</Text>
          <CodeEditor minLines={12} value={draft[path] ?? ""} badLines={badLines} label={fileName(path)}
            onValue={(text) => {
              const edited = { ...draft, [path]: text };
              setDraft(edited);
              keepDraft(round, base, changedOf(edited, live));
            }} />
          {Object.keys(changed).length > 0 && !bench.applicable && <Text tone="muted" small>{t("rules.apply_needs_test")}</Text>}
          <Text tone="muted" small>{t("waf.terminal_note")}</Text>
        </PaneSection>
      )}
      <BenchOutcome bench={bench} onReload={read.reload} />
      <RuleTestSection result={bench.result} stale={bench.stale && !bench.applied} untestedText={t("rule_test.not_yet.waf")} engine="waf" />
      <PaneSection title={t("versions.title")} ruled>
        {versions.error ? <ErrorNotice error={versions.error} />
          : <Table columns={versionColumns} rows={[...versions.versions].reverse()} rowKey={(row) => row.version} variant="grid" empty={t("versions.none")} />}
      </PaneSection>
      {opened !== null && <StoredVersion round={round} version={opened} />}
    </Pane>
  );
}

export function LimitWarningBanner({ round }: { round: number }) {
  const [warned, setWarned] = useState<{ kind: string; zone: string; rate: number; floor: number } | null>(null);
  useEvents(round, [BELOW_FLOOR, SHARED_KEY], (events) => {
    const last = events[events.length - 1];
    if (!last?.body) return;
    const body = last.body;
    setWarned({ kind: last.kind, zone: String(body.zone ?? ""), rate: Number(body.rate_rpm ?? 0), floor: Number(body.floor_rpm ?? 0) });
  }, true);
  if (!warned) return null;
  if (warned.kind === SHARED_KEY) return <Banner title={t("waf.limit.shared_key")} detail={t("waf.limit.shared_key.detail", warned)} />;
  return <Banner title={t("waf.limit.below_floor")} detail={t("waf.limit.below_floor.detail", warned)} />;
}

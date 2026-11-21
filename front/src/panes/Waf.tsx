import { useEffect, useState } from "preact/hooks";
import { api, type Schemas } from "../api/client";
import { useResource } from "../api/hooks";
import { clock } from "../format";
import { t, tFor } from "../strings";
import { Badge, Button, Code, CodeEditor, ErrorNotice, Loading, Notice, Pane, PaneSection, Select, Table, Text, type Column } from "../ui";
import { AppliedMeta, VersionNote, useRuleVersions, type AppliedVersion } from "./RuleVersions";
import { BenchButtons, BenchOutcome, RuleTestSection, fileName, useRuleBench, type BenchCalls } from "./RuleTestTable";
import type { PaneProps } from "./types";

type WafFile = Schemas["WafFile"];

function asMap(files: WafFile[]): Record<string, string> {
  return Object.fromEntries(files.map((one) => [one.path, one.text]));
}

function changedOf(draft: Record<string, string>, live: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(draft).filter(([path, text]) => live[path] !== text));
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
  const read = useResource("/api/rounds/{round_id}/defence/waf/", { params: { round_id: round } }, { refreshOn: { round, kinds: ["rule.applied"] } });
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
    setDraft(asMap(read.data.files));
    setBase(read.data.version);
    setPath((was) => was || read.data?.files[0]?.path || "");
  }, [read.data]);

  const headTest = versions.head?.tested ?? null;
  useEffect(() => {
    if (headTest === null || draft === null) return;
    void api.get("/api/rounds/{round_id}/defence/waf/tests/{test_id}/", { params: { round_id: round, test_id: headTest } })
      .then((said) => bench.seed(said, versions.head?.same_as_tested && read.data?.recorded ? JSON.stringify({}) : null))
      .catch(() => undefined);
  }, [headTest, draft === null]);

  const calls: BenchCalls = {
    check: () => api.post("/api/rounds/{round_id}/defence/waf/check/", { params: { round_id: round }, body: { files: changed } }),
    test: () => api.post("/api/rounds/{round_id}/defence/waf/test/", { params: { round_id: round }, body: { files: changed } }),
    apply: async (tested) => {
      const said = await api.post("/api/rounds/{round_id}/defence/waf/apply/", { params: { round_id: round }, body: { files: changed, base_version: base, tested } });
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
            onValue={(text) => setDraft({ ...draft, [path]: text })} />
          <Text tone="muted" small>{t("waf.terminal_note")}</Text>
        </PaneSection>
      )}
      <BenchOutcome bench={bench} onReload={read.reload} />
      <RuleTestSection result={bench.result} stale={bench.stale} untestedText={t("rule_test.not_yet.waf")} />
      <PaneSection title={t("waf.versions")} ruled>
        {versions.error ? <ErrorNotice error={versions.error} />
          : <Table columns={versionColumns} rows={[...versions.versions].reverse()} rowKey={(row) => row.version} variant="grid" empty={t("versions.none")} />}
      </PaneSection>
      {opened !== null && <StoredVersion round={round} version={opened} />}
    </Pane>
  );
}

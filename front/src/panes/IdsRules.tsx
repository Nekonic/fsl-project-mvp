import { useState } from "preact/hooks";
import { api } from "../api/client";
import { useResource } from "../api/hooks";
import { clock } from "../format";
import { t, tFor } from "../strings";
import { Badge, Button, Code, ErrorNotice, Loading, Notice, Pane, PaneSection, Table, Text, type Column } from "../ui";
import { AppliedMeta, VersionNote, useRuleVersions, type AppliedVersion } from "./RuleVersions";
import { BenchOutcome, RuleTestSection, rememberTest, useLatestTest, useRuleBench } from "./RuleTestTable";
import type { PaneProps } from "./types";

const RULE_EVENTS = ["rule.applied", "rule.refused", "round.ended"];

function StoredVersion({ round, version }: { round: number; version: number }) {
  const shown = useResource("/api/rounds/{round_id}/defence/ids/rules/versions/{version}/", { params: { round_id: round, version } });
  if (shown.error) return <ErrorNotice error={shown.error} />;
  if (!shown.data) return <Loading>{t("common.loading")}</Loading>;
  return (
    <PaneSection title={t("waf.version.title", { version })} meta={<Text mono small>{shown.data.sha.slice(0, 12)}</Text>}>
      <Code>{shown.data.files[0]?.text || t("waf.file.empty")}</Code>
    </PaneSection>
  );
}

export function IdsRules({ round }: PaneProps) {
  const rules = useResource("/api/rounds/{round_id}/defence/ids/rules/", { params: { round_id: round } }, { refreshOn: { round, kinds: RULE_EVENTS } });
  const versions = useRuleVersions(round, "ids");
  const [opened, setOpened] = useState<number | null>(null);
  const live = rules.data?.text ?? "";
  const bench = useRuleBench(live);
  useLatestTest({ round, engine: "ids", content: rules.data ? live : null, body: live, liveBody: live, head: versions.head, recorded: rules.data?.recorded, bench });

  const test = () => bench.test({
    test: async () => {
      const said = await api.post("/api/rounds/{round_id}/defence/ids/rules/test/", { params: { round_id: round }, body: { text: live } });
      if (said.ok) rememberTest(round, "ids", live, said.test);
      return said;
    },
  });

  const versionColumns: Column<AppliedVersion>[] = [
    { key: "version", label: t("versions.col.version"), kind: "num", cell: (row) => row.version },
    { key: "at", label: t("versions.col.applied_at"), kind: "mono", cell: (row) => clock(row.applied_at) },
    { key: "source", label: t("versions.col.source"), cell: (row) => <Badge>{tFor("versions.source", row.source)}</Badge> },
    { key: "sha", label: t("versions.col.sha"), kind: "mono", cell: (row) => row.sha.slice(0, 12) },
    { key: "note", label: t("versions.col.tested"), cell: (row) => <VersionNote version={row} /> },
    { key: "open", label: "", kind: "end", cell: (row) => <Button small onClick={() => setOpened(opened === row.version ? null : row.version)}>{t(opened === row.version ? "waf.version.close" : "waf.version.open")}</Button> },
  ];

  return (
    <Pane title={t("pane.ids_rules")} meta={<AppliedMeta head={versions.head} loading={versions.loading} />}
      actions={<Button small tone="primary" busy={bench.busy === "test"} disabled={!rules.data || bench.busy !== null} onClick={() => void test()}>{t("rules.test")}</Button>}>
      {rules.error && <ErrorNotice error={rules.error} />}
      {!rules.data ? (rules.error ? null : <Loading>{t("common.loading")}</Loading>) : (
        <PaneSection>
          {!rules.data.recorded && <Notice tone="warn">{t("ids.not_running")}</Notice>}
          <Code>{live || t("waf.file.empty")}</Code>
          <Text tone="muted" small>{t("ids.terminal_note")}</Text>
        </PaneSection>
      )}
      <BenchOutcome bench={bench} onReload={rules.reload} />
      <RuleTestSection result={bench.result} stale={bench.stale} untestedText={t("rule_test.not_yet.ids")} engine="ids" />
      <PaneSection title={t("waf.versions")} ruled>
        {versions.error ? <ErrorNotice error={versions.error} />
          : <Table columns={versionColumns} rows={[...versions.versions].reverse()} rowKey={(row) => row.version} variant="grid" empty={t("versions.none")} />}
      </PaneSection>
      {opened !== null && <StoredVersion round={round} version={opened} />}
    </Pane>
  );
}

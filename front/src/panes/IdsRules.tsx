import { useEffect, useState } from "preact/hooks";
import { api } from "../api/client";
import { useAction, useResource } from "../api/hooks";
import { clock } from "../format";
import { fieldErrors, formErrors, t } from "../strings";
import { Button, ErrorNotice, Field, Filters, Form, Input, Loading, Pane, PaneSection, Table, Text, type Column, CodeEditor } from "../ui";
import { AppliedMeta, useRuleVersions } from "./RuleVersions";
import { BenchButtons, BenchOutcome, RuleTestSection, useRuleBench, type BenchCalls } from "./RuleTestTable";
import type { PaneProps } from "./types";

const DISABLE_EVENTS = ["rule.disabled", "rule.applied", "round.ended"];
type DisabledRule = { sid: number; original: string; reason: string; expires_at: string };

function DisabledRules({ round }: { round: number }) {
  const listed = useResource("/api/rounds/{round_id}/defence/ids/disabled/", { params: { round_id: round } }, { refreshOn: { round, kinds: DISABLE_EVENTS } });
  const disable = useAction("post", "/api/rounds/{round_id}/defence/ids/disabled/");
  const enable = useAction("delete", "/api/rounds/{round_id}/defence/ids/disabled/{sid}/");
  const [sid, setSid] = useState("");
  const [minutes, setMinutes] = useState("60");
  const [reason, setReason] = useState("");
  const byField = fieldErrors(disable.error);

  const submit = async () => {
    const done = await disable.run({ params: { round_id: round }, body: { sid: Number(sid), minutes: Number(minutes), reason } });
    if (done) {
      setSid("");
      setReason("");
      listed.reload();
    }
  };

  const columns: Column<DisabledRule>[] = [
    { key: "sid", label: t("ids.disabled.sid"), kind: "mono", cell: (row) => row.sid },
    { key: "original", label: t("ids.disabled.original"), kind: "cut", cell: (row) => <Text mono small>{row.original}</Text>, title: (row) => row.original },
    { key: "reason", label: t("ids.disabled.reason"), kind: "wrap", cell: (row) => row.reason || <Text tone="faint">—</Text> },
    { key: "expires", label: t("ids.disabled.expires_at"), kind: "mono", cell: (row) => clock(row.expires_at) },
    {
      key: "enable", label: "", kind: "end",
      cell: (row) => (
        <Button small busy={enable.busy} onClick={async () => {
          await enable.run({ params: { round_id: round, sid: row.sid } });
          listed.reload();
        }}>{t("ids.disabled.enable")}</Button>
      ),
    },
  ];

  return (
    <PaneSection title={t("ids.disabled.title")} ruled>
      {listed.loading && !listed.data ? <Loading>{t("common.loading")}</Loading>
        : listed.error ? <ErrorNotice error={listed.error} />
        : <Table columns={columns} rows={listed.data ?? []} rowKey={(row) => row.sid} variant="grid" empty={t("ids.disabled.none")} />}
      {enable.error && <ErrorNotice error={enable.error} />}
      <Form onSubmit={() => void submit()}>
        <Filters>
          <Field label={t("ids.disabled.sid")} error={byField.sid}>
            <Input mono value={sid} onValue={setSid} inputMode="numeric" placeholder="9000001" bad={!!byField.sid} />
          </Field>
          <Field label={t("ids.disabled.minutes")} error={byField.minutes}>
            <Input mono value={minutes} onValue={setMinutes} inputMode="decimal" bad={!!byField.minutes} />
          </Field>
          <Field label={t("ids.disabled.reason")} error={byField.reason}>
            <Input value={reason} onValue={setReason} bad={!!byField.reason} />
          </Field>
          <Button type="submit" busy={disable.busy} disabled={!sid}>{t("ids.disabled.disable")}</Button>
        </Filters>
        {formErrors(disable.error, ["sid", "minutes", "reason"]).map((line, index) => <Text key={index} tone="danger" small>{line}</Text>)}
      </Form>
    </PaneSection>
  );
}

export function IdsRules({ round }: PaneProps) {
  const rules = useResource("/api/rounds/{round_id}/defence/ids/rules/", { params: { round_id: round } });
  const versions = useRuleVersions(round, "ids");
  const [text, setText] = useState<string | null>(null);
  const [base, setBase] = useState(0);
  const body = text ?? "";
  const bench = useRuleBench(body);

  useEffect(() => {
    if (!rules.data) return;
    setText(rules.data.text);
    setBase(rules.data.version);
  }, [rules.data]);

  const headTest = versions.head?.tested ?? null;
  useEffect(() => {
    if (headTest === null || text === null) return;
    void api.get("/api/rounds/{round_id}/defence/ids/rules/tests/{test_id}/", { params: { round_id: round, test_id: headTest } })
      .then((said) => bench.seed(said, versions.head?.same_as_tested ? rules.data?.text ?? null : null))
      .catch(() => undefined);
  }, [headTest, text === null]);

  const calls: BenchCalls = {
    check: () => api.post("/api/rounds/{round_id}/defence/ids/rules/check/", { params: { round_id: round }, body: { text: body } }),
    test: () => api.post("/api/rounds/{round_id}/defence/ids/rules/test/", { params: { round_id: round }, body: { text: body } }),
    apply: async (tested) => {
      const said = await api.post("/api/rounds/{round_id}/defence/ids/rules/apply/", { params: { round_id: round }, body: { text: body, base_version: base, tested } });
      setBase(said.version);
      versions.reload();
      return said;
    },
  };

  const badLines = new Set(bench.problems.map((problem) => problem.line).filter((line): line is number => typeof line === "number"));

  return (
    <Pane title={t("pane.ids_rules")} meta={<AppliedMeta head={versions.head} loading={versions.loading} />}
      actions={<BenchButtons bench={bench} calls={calls} disabled={text === null} />}>
      {rules.error && <ErrorNotice error={rules.error} />}
      {text === null ? (rules.error ? null : <Loading>{t("common.loading")}</Loading>) : (
        <PaneSection>
          <CodeEditor value={text} onValue={setText} badLines={badLines} label={t("pane.ids_rules")} />
        </PaneSection>
      )}
      <BenchOutcome bench={bench} onReload={rules.reload} />
      <RuleTestSection result={bench.result} stale={bench.stale} untestedText={t("rule_test.not_yet.ids")} />
      <DisabledRules round={round} />
    </Pane>
  );
}

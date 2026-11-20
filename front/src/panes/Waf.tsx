import { useEffect, useRef, useState } from "preact/hooks";
import { api, type Schemas } from "../api/client";
import { useResource } from "../api/hooks";
import { errorLine, t } from "../strings";
import { Button, Checkbox, ErrorNotice, Field, FormGrid, Input, Loading, Pane, PaneSection, Select, Table, type Column } from "../ui";
import { AppliedMeta, useRuleVersions } from "./RuleVersions";
import { BenchButtons, BenchOutcome, RuleTestSection, useRuleBench, type BenchCalls, type RuleProblem } from "./RuleTestTable";
import type { PaneProps } from "./types";

type Posture = Schemas["WafPosture"];
type PostureRequest = Schemas["WafPostureRequest"];

interface ExclusionDraft {
  row: number;
  ruleOrTag: string;
  target: string;
  path: string;
}

interface PostureDraft {
  paranoia: string;
  inbound: string;
  outbound: string;
  detectionOnly: boolean;
  exclusions: ExclusionDraft[];
}

const PARANOIA_LEVELS = ["1", "2", "3", "4"].map((level) => ({ value: level, label: level }));
const RULE_ID = /^\d+$/;
const FIELD_PATHS = /^(paranoia|detection_only|thresholds\.(inbound|outbound)|exclusions\[\d+\](\.(rule_id|tag|target|path))?)$/;

function draftOf(posture: Posture, nextRow: () => number): PostureDraft {
  return {
    paranoia: String(posture.paranoia),
    inbound: posture.thresholds?.inbound === undefined ? "" : String(posture.thresholds.inbound),
    outbound: posture.thresholds?.outbound === undefined ? "" : String(posture.thresholds.outbound),
    detectionOnly: posture.detection_only ?? false,
    exclusions: (posture.exclusions ?? []).map((one) => ({
      row: nextRow(),
      ruleOrTag: one.rule_id !== undefined ? String(one.rule_id) : one.tag ?? "",
      target: one.target ?? "",
      path: one.path ?? "",
    })),
  };
}

function numberOrText(value: string): number {
  return value.trim() === "" ? Number.NaN : Number(value);
}

function requestOf(draft: PostureDraft): PostureRequest {
  const thresholds: PostureRequest["thresholds"] = {};
  if (draft.inbound.trim()) thresholds.inbound = numberOrText(draft.inbound);
  if (draft.outbound.trim()) thresholds.outbound = numberOrText(draft.outbound);
  return {
    paranoia: Number(draft.paranoia),
    detection_only: draft.detectionOnly,
    thresholds,
    exclusions: draft.exclusions.map((one) => {
      const key = one.ruleOrTag.trim();
      return {
        ...(RULE_ID.test(key) ? { rule_id: Number(key) } : { tag: key }),
        ...(one.target.trim() ? { target: one.target.trim() } : {}),
        ...(one.path.trim() ? { path: one.path.trim() } : {}),
      };
    }),
  };
}

function problemsAt(problems: RuleProblem[]): (path: string) => string | undefined {
  return (path) => {
    const lines = problems.filter((problem) => problem.path === path).map((problem) => errorLine({ path: problem.path, code: problem.code }));
    return lines.length ? lines.join(" ") : undefined;
  };
}

export function Waf({ round }: PaneProps) {
  const read = useResource("/api/rounds/{round_id}/defence/waf/", { params: { round_id: round } });
  const versions = useRuleVersions(round, "waf");
  const rows = useRef(0);
  const nextRow = () => ++rows.current;
  const [draft, setDraft] = useState<PostureDraft | null>(null);
  const [base, setBase] = useState(0);
  const request = draft ? requestOf(draft) : null;
  const body = request ? JSON.stringify(request) : "";
  const bench = useRuleBench(body);
  const at = problemsAt(bench.problems);

  useEffect(() => {
    if (!read.data) return;
    setDraft(draftOf(read.data.posture, nextRow));
    setBase(read.data.version);
  }, [read.data]);

  const headTest = versions.head?.tested ?? null;
  useEffect(() => {
    if (headTest === null || draft === null) return;
    void api.get("/api/rounds/{round_id}/defence/waf/tests/{test_id}/", { params: { round_id: round, test_id: headTest } })
      .then((said) => bench.seed(said, versions.head?.same_as_tested && read.data ? JSON.stringify(requestOf(draftOf(read.data.posture, () => 0))) : null))
      .catch(() => undefined);
  }, [headTest, draft === null]);

  const change = (patch: Partial<PostureDraft>) => setDraft((was) => (was ? { ...was, ...patch } : was));
  const changeExclusion = (row: number, patch: Partial<ExclusionDraft>) =>
    setDraft((was) => (was ? { ...was, exclusions: was.exclusions.map((one) => (one.row === row ? { ...one, ...patch } : one)) } : was));

  const posture = request ?? { paranoia: 1 };
  const calls: BenchCalls = {
    check: () => api.post("/api/rounds/{round_id}/defence/waf/check/", { params: { round_id: round }, body: { posture } }),
    test: () => api.post("/api/rounds/{round_id}/defence/waf/test/", { params: { round_id: round }, body: { posture } }),
    apply: async (tested) => {
      const said = await api.post("/api/rounds/{round_id}/defence/waf/apply/", { params: { round_id: round }, body: { posture, base_version: base, tested } });
      setBase(said.version);
      versions.reload();
      return said;
    },
  };

  const exclusionColumns: Column<ExclusionDraft>[] = [
    {
      key: "rule", label: t("waf.exclusion.rule_or_tag"),
      cell: (one) => {
        const index = draft?.exclusions.indexOf(one) ?? -1;
        const error = at(`exclusions[${index}].rule_id`) ?? at(`exclusions[${index}].tag`) ?? at(`exclusions[${index}]`);
        return <Field error={error}><Input mono value={one.ruleOrTag} bad={!!error} onValue={(value) => changeExclusion(one.row, { ruleOrTag: value })} /></Field>;
      },
    },
    {
      key: "target", label: t("waf.exclusion.target"),
      cell: (one) => {
        const error = at(`exclusions[${draft?.exclusions.indexOf(one) ?? -1}].target`);
        return <Field error={error}><Input mono value={one.target} bad={!!error} placeholder="ARGS:sort" onValue={(value) => changeExclusion(one.row, { target: value })} /></Field>;
      },
    },
    {
      key: "path", label: t("waf.exclusion.path"),
      cell: (one) => {
        const error = at(`exclusions[${draft?.exclusions.indexOf(one) ?? -1}].path`);
        return <Field error={error}><Input mono value={one.path} bad={!!error} placeholder="/" onValue={(value) => changeExclusion(one.row, { path: value })} /></Field>;
      },
    },
    {
      key: "remove", label: "", kind: "end",
      cell: (one) => <Button small onClick={() => change({ exclusions: (draft?.exclusions ?? []).filter((kept) => kept.row !== one.row) })}>{t("waf.exclusion.remove")}</Button>,
    },
  ];

  return (
    <Pane title={t("pane.waf")} meta={<AppliedMeta head={versions.head} loading={versions.loading} />}
      actions={<BenchButtons bench={bench} calls={calls} disabled={draft === null} />}>
      {read.error && <ErrorNotice error={read.error} />}
      {draft === null ? (read.error ? null : <Loading>{t("common.loading")}</Loading>) : (
        <>
          <FormGrid four>
            <Field label={t("waf.paranoia")} error={at("paranoia")}>
              <Select value={draft.paranoia} options={PARANOIA_LEVELS} bad={!!at("paranoia")} onValue={(value) => change({ paranoia: value })} />
            </Field>
            <Field label={t("waf.inbound")} error={at("thresholds.inbound")}>
              <Input mono inputMode="numeric" value={draft.inbound} bad={!!at("thresholds.inbound")} onValue={(value) => change({ inbound: value })} />
            </Field>
            <Field label={t("waf.outbound")} error={at("thresholds.outbound")}>
              <Input mono inputMode="numeric" value={draft.outbound} bad={!!at("thresholds.outbound")} onValue={(value) => change({ outbound: value })} />
            </Field>
            <Field label={t("waf.detection_only")} error={at("detection_only")}>
              <Checkbox checked={draft.detectionOnly} label={t("waf.detection_only.on")} onChecked={(checked) => change({ detectionOnly: checked })} />
            </Field>
          </FormGrid>
          <PaneSection title={t("waf.exclusions")} meta={t("rule_test.count", { count: draft.exclusions.length })}
            actions={<Button small onClick={() => change({ exclusions: [...draft.exclusions, { row: nextRow(), ruleOrTag: "", target: "", path: "" }] })}>{t("waf.exclusion.add")}</Button>}>
            <Table columns={exclusionColumns} rows={draft.exclusions} rowKey={(one) => one.row} variant="grid" empty={t("waf.exclusions.none")} />
          </PaneSection>
        </>
      )}
      <BenchOutcome bench={bench} onReload={read.reload} problemsShownInline={(problem) => FIELD_PATHS.test(problem.path)} />
      <RuleTestSection result={bench.result} stale={bench.stale} untestedText={t("rule_test.not_yet.waf")} />
    </Pane>
  );
}

import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, type Schemas } from "../api/client";
import { t, tFor, type StringKey } from "../strings";
import { Badge, Badges, Button, ErrorNotice, Notice, PaneSection, Stack, Stat, Stats, Table, Text, type BadgeTone, type Column } from "../ui";


export type RuleTestResult = Schemas["RuleTestResult"];
export type CaseVerdict = Schemas["CaseVerdict"];
export type Verdict = Schemas["VerdictEnum"];
export type RuleCheck = Schemas["RuleCheck"];

export interface RuleProblem {
  path: string;
  code: string;
  line?: number | null;
  message?: string;
}

export interface AppliedNow {
  version: number;
  applied_at: string;
  same_as_tested: boolean;
}

const VERDICT_TONE: Record<Verdict, BadgeTone> = { tp: "ok", fn: "danger", fp: "warn", tn: "muted" };
const VERDICT_ORDER: Verdict[] = ["tp", "fn", "fp", "tn"];
const REQUEST_ONLY_PATHS = new Set(["", "base_version", "tested", "cases"]);

export function fileName(path: string): string {
  return path.split("/").pop() ?? path;
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <Badge tone={VERDICT_TONE[verdict]}>{tFor("verdict", verdict)}</Badge>;
}

function CaseKind({ row }: { row: CaseVerdict }) {
  if (!row.malicious) return <>{t("case_kind.benign")}</>;
  return <>{row.recorded_run ? t("case_kind.tool") : t("case_kind.attack")}</>;
}

function Corroboration({ row }: { row: CaseVerdict }) {
  if (row.corroborated === null) return <Text tone="faint">—</Text>;
  return row.corroborated
    ? <Text tone="ok">{t("corroborated.yes")}</Text>
    : <Text tone="warn">{t("corroborated.no")}</Text>;
}

export interface AlertGroup {
  rule: string;
  signature: string;
  count: number;
}

export function alertGroups(alerts: CaseVerdict["alerts"]): AlertGroup[] {
  const byRule = new Map<string, AlertGroup>();
  for (const alert of alerts) {
    const key = JSON.stringify([alert.rule, alert.signature]);
    const held = byRule.get(key);
    if (held) held.count += 1;
    else byRule.set(key, { rule: String(alert.rule), signature: alert.signature, count: 1 });
  }
  return [...byRule.values()].sort((one, other) => other.count - one.count);
}

function CaseAlerts({ row }: { row: CaseVerdict }) {
  if (!row.alerts.length) return <Text tone="faint">—</Text>;
  return (
    <Stack gap="sm">
      {alertGroups(row.alerts).map((group) => (
        <span key={`${group.rule}-${group.signature}`}>
          <Text mono>{group.rule}</Text> <Text tone="muted">{group.signature}</Text>
          {group.count > 1 && <> <Text strong>{t("rule_test.alert_times", { count: group.count })}</Text></>}
        </span>
      ))}
    </Stack>
  );
}

const CASE_COLUMNS: Column<CaseVerdict>[] = [
  { key: "case", label: t("col.case"), kind: "key", cell: (row) => row.case },
  { key: "kind", label: t("col.case_kind"), kind: "nowrap", cell: (row) => <CaseKind row={row} /> },
  {
    key: "verdict", label: t("col.verdict"),
    cell: (row) => (
      <Badges>
        <VerdictBadge verdict={row.verdict} />
        {row.recorded_run && <Badge tone="neutral">{t("rule_test.recorded_run")}</Badge>}
      </Badges>
    ),
  },
  { key: "corroborated", label: t("col.corroborated"), cell: (row) => <Corroboration row={row} /> },
  { key: "alerts", label: t("col.alerts"), kind: "wrap", cell: (row) => <CaseAlerts row={row} /> },
];

export function RuleTestTable({ cases }: { cases: CaseVerdict[] }) {
  return <Table columns={CASE_COLUMNS} rows={cases} rowKey={(row) => row.case} variant="grid" empty={t("rule_test.no_cases")} />;
}

function AgainstApplied({ changes }: { changes: RuleTestResult["against_applied"] }) {
  if (!changes.length) return null;
  return (
    <Stack gap="sm">
      {changes.map((change) => (
        <Notice key={change.case}>
          <Text tone="muted">{t("rule_test.against_applied")}</Text>{" "}
          <Text mono tone="heading">{change.case}</Text>{" "}
          <VerdictBadge verdict={change.was} /> <Text tone="faint">→</Text> <VerdictBadge verdict={change.now} />
        </Notice>
      ))}
    </Stack>
  );
}

function Untested({ untested }: { untested: RuleTestResult["untested"] }) {
  if (!untested.length) return null;
  return (
    <PaneSection title={t("rule_test.untested")} meta={t("rule_test.count", { count: untested.length })}>
      {untested.map((one) => (
        <span key={one.case}><Text mono tone="heading">{one.case}</Text> <Text tone="muted">{tFor("rule_test.untested", one.reason)}</Text></span>
      ))}
    </PaneSection>
  );
}

export function RuleProblems({ problems }: { problems: RuleProblem[] }) {
  if (!problems.length) return null;
  const codes = [...new Set(problems.map((problem) => problem.code))];
  return (
    <Stack gap="sm">
      {codes.map((code) => (
        <Notice key={code} tone="danger" title={tFor("error", code, undefined, "error.unknown")}>
          {problems.filter((problem) => problem.code === code && (problem.message || problem.line)).map((problem, index) => (
            <Text key={index} mono small>
              {problem.path.startsWith("/") ? `${fileName(problem.path)} · ` : ""}
              {problem.line ? t("error.at_line", { line: problem.line, message: problem.message ?? "" }) : problem.message}
            </Text>
          ))}
        </Notice>
      ))}
    </Stack>
  );
}

export interface RuleTestSectionProps {
  result: RuleTestResult | undefined;
  stale: boolean;
  untestedText: string;
  engine: "waf" | "ids";
}

function Passing({ result, engine }: { result: RuleTestResult; engine: "waf" | "ids" }) {
  if (result.passed) return <Notice tone="ok">{t(engine === "waf" ? "rule_test.passed.waf" : "rule_test.passed.ids")}</Notice>;
  if (result.failed_benign.length) return <Notice tone="danger">{t("rule_test.failed_benign", { cases: result.failed_benign.join(", ") })}</Notice>;
  if (result.untested_benign.length) return <Notice tone="danger">{t("rule_test.untested_benign", { cases: result.untested_benign.join(", ") })}</Notice>;
  if (result.ok) return <Notice tone="danger">{t("rule_test.no_benign")}</Notice>;
  return <Notice tone="danger">{t("rule_test.failed_engine")}</Notice>;
}

export function RuleTestSection({ result, stale, untestedText, engine }: RuleTestSectionProps) {
  if (!result) {
    return (
      <PaneSection title={t("rule_test.title")} ruled>
        <Text tone="muted">{untestedText}</Text>
      </PaneSection>
    );
  }
  return (
    <PaneSection ruled title={t("rule_test.numbered", { test: result.test })}
      meta={<Stats>{VERDICT_ORDER.map((verdict) => <Stat key={verdict} label={tFor("verdict", verdict)} value={result.totals[verdict]} />)}</Stats>}>
      {stale ? <Notice tone="warn">{t("rule_test.stale")}</Notice> : <Passing result={result} engine={engine} />}
      <AgainstApplied changes={result.against_applied} />
      <RuleTestTable cases={result.cases} />
      <Untested untested={result.untested} />
    </PaneSection>
  );
}

export interface BenchCalls {
  check: () => Promise<RuleCheck>;
  test: () => Promise<RuleTestResult>;
  apply: (tested: number | null) => Promise<AppliedNow>;
}

type BenchStep = "check" | "test" | "apply";

function asProblems(errors: Array<{ path: string; code: string; line?: number | null; message?: string; params?: Record<string, unknown> }>): RuleProblem[] {
  return errors.map((error) => ({
    path: error.path,
    code: error.code,
    line: error.line ?? null,
    message: error.message ?? (typeof error.params?.message === "string" ? error.params.message : undefined),
  }));
}

export function useRuleBench(body: string) {
  const [problems, setProblems] = useState<RuleProblem[]>([]);
  const [problemsFor, setProblemsFor] = useState<string | null>(null);
  const [passedFor, setPassedFor] = useState<string | null>(null);
  const [result, setResult] = useState<RuleTestResult | undefined>(undefined);
  const [testedBody, setTestedBody] = useState<string | null>(null);
  const [failure, setFailure] = useState<ApiError | undefined>(undefined);
  const [applied, setApplied] = useState<AppliedNow | undefined>(undefined);
  const [appliedWithTest, setAppliedWithTest] = useState(false);
  const [busy, setBusy] = useState<BenchStep | null>(null);
  const testedHere = useRef(false);

  const showProblems = (found: RuleProblem[]) => {
    setProblems(found);
    setProblemsFor(found.length ? body : null);
  };

  const step = async <T,>(name: BenchStep, work: () => Promise<T>): Promise<T | undefined> => {
    setBusy(name);
    setFailure(undefined);
    setApplied(undefined);
    try {
      return await work();
    } catch (failed) {
      const error = failed instanceof ApiError ? failed : new ApiError(0, [{ path: "", code: "network" }]);
      const fieldProblems = asProblems(error.errors.filter((one) => !REQUEST_ONLY_PATHS.has(one.path)));
      showProblems(fieldProblems);
      if (fieldProblems.length < error.errors.length) setFailure(error);
      return undefined;
    } finally {
      setBusy(null);
    }
  };

  const check = (calls: BenchCalls) => step("check", async () => {
    const said = await calls.check();
    showProblems(asProblems(said.errors));
    setPassedFor(said.ok ? body : null);
    return said;
  });

  const test = (calls: Pick<BenchCalls, "test">) => step("test", async () => {
    const said = await calls.test();
    showProblems(asProblems(said.errors));
    if (said.ok) {
      testedHere.current = true;
      setResult(said);
      setTestedBody(body);
      setPassedFor(body);
    }
    return said;
  });

  const apply = (calls: BenchCalls) => step("apply", async () => {
    const said = await calls.apply(result?.test ?? null);
    showProblems([]);
    setAppliedWithTest(result !== undefined);
    setApplied(said);
    return said;
  });

  const seed = useCallback((seeded: RuleTestResult, forBody: string | null, preferred = false) => {
    if (preferred && !testedHere.current) {
      setResult(seeded);
      setTestedBody(forBody);
      return;
    }
    setResult((was) => was ?? seeded);
    setTestedBody((was) => was ?? forBody);
  }, []);

  const shownProblems = problemsFor === body ? problems : [];
  return {
    problems: shownProblems,
    passed: passedFor === body && !shownProblems.length,
    result,
    stale: result !== undefined && testedBody !== body,
    applicable: result !== undefined && result.passed && testedBody === body,
    failure,
    applied,
    appliedWithTest,
    busy,
    check,
    test,
    apply,
    seed,
  };
}

export type RuleBench = ReturnType<typeof useRuleBench>;

export type RuleEngine = "waf" | "ids";

function rememberedKey(round: number, engine: RuleEngine): string {
  return `cr.rule_test.${round}.${engine}`;
}

export function rememberTest(round: number, engine: RuleEngine, content: string, test: number): void {
  try {
    localStorage.setItem(rememberedKey(round, engine), JSON.stringify({ content, test }));
  } catch {
    return;
  }
}

export function rememberedTest(round: number, engine: RuleEngine, content: string): number | null {
  try {
    const held = JSON.parse(localStorage.getItem(rememberedKey(round, engine)) ?? "null") as { content?: unknown; test?: unknown } | null;
    return held && held.content === content && typeof held.test === "number" ? held.test : null;
  } catch {
    return null;
  }
}

function readTest(round: number, engine: RuleEngine, test: number): Promise<RuleTestResult> {
  if (engine === "waf") return api.get("/api/rounds/{round_id}/defence/waf/tests/{test_id}/", { params: { round_id: round, test_id: test } });
  return api.get("/api/rounds/{round_id}/defence/ids/rules/tests/{test_id}/", { params: { round_id: round, test_id: test } });
}

export interface LatestTestProps {
  round: number;
  engine: RuleEngine;
  content: string | null;
  body: string;
  liveBody: string;
  head: { tested: number | null; same_as_tested: boolean } | undefined;
  recorded: boolean | undefined;
  bench: RuleBench;
}

export function useLatestTest({ round, engine, content, body, liveBody, head, recorded, bench }: LatestTestProps): void {
  const remembered = content === null ? null : rememberedTest(round, engine, content);
  const headTest = head?.tested ?? null;
  const wanted = remembered ?? headTest;
  const { seed } = bench;
  useEffect(() => {
    if (content === null || wanted === null) return;
    const forBody = remembered !== null ? body : (head?.same_as_tested && recorded ? liveBody : null);
    void readTest(round, engine, wanted).then((said) => seed(said, forBody, remembered !== null)).catch(() => undefined);
  }, [round, engine, wanted, remembered !== null, content === null]);
}

export function appliedNote(applied: { same_as_tested: boolean }, withTest: boolean): StringKey {
  if (applied.same_as_tested) return "versions.same_as_tested";
  return withTest ? "versions.not_same_as_tested" : "versions.untested";
}

export function BenchButtons({ bench, calls, disabled }: { bench: RuleBench; calls: BenchCalls; disabled?: boolean }) {
  return (
    <>
      <Button small busy={bench.busy === "check"} disabled={disabled || bench.busy !== null} onClick={() => void bench.check(calls)}>{t("common.validate")}</Button>
      <Button small tone="primary" busy={bench.busy === "test"} disabled={disabled || bench.busy !== null} onClick={() => void bench.test(calls)}>{t("rules.test")}</Button>
      <Button small tone="dark" busy={bench.busy === "apply"} disabled={disabled || bench.busy !== null || !bench.applicable} onClick={() => void bench.apply(calls)}>{t("rules.apply")}</Button>
    </>
  );
}

export function BenchOutcome({ bench, onReload, problemsShownInline }: { bench: RuleBench; onReload: () => void; problemsShownInline?: (problem: RuleProblem) => boolean }) {
  const loose = problemsShownInline ? bench.problems.filter((problem) => !problemsShownInline(problem)) : bench.problems;
  const stale = bench.failure?.has("stale_version");
  return (
    <>
      <RuleProblems problems={loose} />
      {bench.failure && (
        <ErrorNotice error={bench.failure}
          action={stale ? <Button small onClick={onReload}>{t("common.reload")}</Button> : undefined} />
      )}
      {bench.passed && !bench.applied && bench.busy === null && !bench.failure && <Notice tone="ok">{t("rules.check_ok")}</Notice>}
      {bench.applied && (
        <Notice tone="ok" title={t("rules.applied_now", { version: bench.applied.version })}>
          {t(appliedNote(bench.applied, bench.appliedWithTest))}
        </Notice>
      )}
    </>
  );
}

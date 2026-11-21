import { useCallback, useState } from "preact/hooks";
import { ApiError, type Schemas } from "../api/client";
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

function CaseAlerts({ row }: { row: CaseVerdict }) {
  if (!row.alerts.length) return <Text tone="faint">—</Text>;
  return (
    <Stack gap="sm">
      {row.alerts.map((alert, index) => (
        <span key={index}><Text mono>{alert.rule}</Text> <Text tone="muted">{alert.signature}</Text></span>
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
}

export function RuleTestSection({ result, stale, untestedText }: RuleTestSectionProps) {
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
      {stale && <Notice tone="warn">{t("rule_test.stale")}</Notice>}
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

  const test = (calls: BenchCalls) => step("test", async () => {
    const said = await calls.test();
    showProblems(asProblems(said.errors));
    if (said.ok) {
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

  const seed = useCallback((seeded: RuleTestResult, forBody: string | null) => {
    setResult((was) => was ?? seeded);
    setTestedBody((was) => was ?? forBody);
  }, []);

  const shownProblems = problemsFor === body ? problems : [];
  return {
    problems: shownProblems,
    passed: passedFor === body && !shownProblems.length,
    result,
    stale: result !== undefined && testedBody !== body,
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

export function appliedNote(applied: { same_as_tested: boolean }, withTest: boolean): StringKey {
  if (applied.same_as_tested) return "versions.same_as_tested";
  return withTest ? "versions.not_same_as_tested" : "versions.untested";
}

export function BenchButtons({ bench, calls, disabled }: { bench: RuleBench; calls: BenchCalls; disabled?: boolean }) {
  return (
    <>
      <Button small busy={bench.busy === "check"} disabled={disabled || bench.busy !== null} onClick={() => void bench.check(calls)}>{t("common.validate")}</Button>
      <Button small tone="primary" busy={bench.busy === "test"} disabled={disabled || bench.busy !== null} onClick={() => void bench.test(calls)}>{t("rules.test")}</Button>
      <Button small tone="dark" busy={bench.busy === "apply"} disabled={disabled || bench.busy !== null} onClick={() => void bench.apply(calls)}>{t("rules.apply")}</Button>
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

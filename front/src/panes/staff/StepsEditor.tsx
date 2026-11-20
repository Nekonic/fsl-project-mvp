import { useState } from "preact/hooks";
import { useAction, useResource } from "../../api/hooks";
import { errorText, type ShownError, t, tFor } from "../../strings";
import { Badge, Badges, Button, ErrorNotice, Field, FormGrid, Input, Section, Select, Task, TextArea, Text, type Option, EditorGroup, FieldNote, Inputs, TryRow } from "../../ui";
import { useStaffProblems } from "./catalog";
import { ANSWERED_KINDS, blankStep, CHECK_KINDS, errorsUnder, OPENS, stepTitle, textUnder, type StepDraft } from "./document";

const TERMINAL_TITLES: Record<string, string> = {
  terminal_kali: t("terminal.attack.title"),
  terminal_waf: t("terminal.defence.title"),
};

function opensLabel(opens: string): string {
  if (opens === "none") return t("common.none");
  return TERMINAL_TITLES[opens] ?? tFor("pane", opens);
}

function kindLabel(kind: string): string {
  return tFor("check_kind", kind);
}

const OPENS_OPTIONS: Option[] = OPENS.map((opens) => ({ value: opens, label: opensLabel(opens) }));

function kindOptions(current: string): Option[] {
  const kinds = CHECK_KINDS.includes(current) ? CHECK_KINDS : [...CHECK_KINDS, current];
  return kinds.map((kind) => ({ value: kind, label: kindLabel(kind) }));
}

function useEndedRounds(wargame: string): Option[] {
  const rounds = useResource("/api/rounds/", {});
  const problems = useStaffProblems();
  const wargameOf = new Map((problems.data ?? []).map((problem) => [problem.id, problem.wargame]));
  return (rounds.data ?? [])
    .filter((round) => round.phase === "ended" && wargameOf.get(round.problem) === wargame)
    .sort((one, two) => two.round - one.round)
    .map((round) => ({ value: String(round.round), label: t("round.name", { round: round.round }) }));
}

interface StepTryProps {
  problemId: number;
  order: number;
  kind: string;
  rounds: Option[];
}

function StepTry({ problemId, order, kind, rounds }: StepTryProps) {
  const [round, setRound] = useState(rounds[0]?.value ?? "");
  const [answer, setAnswer] = useState("");
  const trying = useAction("post", "/api/staff/steps/{problem_id}/{order}/try/");
  const chosen = round || rounds[0]?.value || "";
  if (!rounds.length) {
    return <TryRow><Text tone="muted" small>{t("staff.step.try_no_round")}</Text></TryRow>;
  }
  const verdict = trying.data;
  return (
    <TryRow>
      <Select value={chosen} options={rounds} onValue={setRound} label={t("staff.step.try_round")} />
      {ANSWERED_KINDS.includes(kind) && (
        <Input value={answer} onValue={setAnswer} placeholder={t("staff.step.try_answer")} aria-label={t("staff.step.try_answer")} />
      )}
      <Button small busy={trying.busy}
        onClick={() => void trying.run({ params: { problem_id: problemId, order }, body: { round: Number(chosen), ...(ANSWERED_KINDS.includes(kind) ? { answer } : {}) } })}>
        {t("staff.step.try")}
      </Button>
      {verdict && (verdict.verdict === "passed"
        ? <Badge tone="ok">{t("staff.step.passed")}</Badge>
        : <Badges>
          <Badge tone="warn">{t("staff.step.not_yet")}</Badge>
          {verdict.detail_code && <Text tone="muted" small>{tFor("check", verdict.detail_code)}</Text>}
        </Badges>)}
      {trying.error && <Text tone="danger" small>{errorText(trying.error)}</Text>}
    </TryRow>
  );
}

interface StepEditorProps {
  step: StepDraft;
  index: number;
  errors: ShownError[];
  open: boolean;
  onToggle: () => void;
  onStep: (step: StepDraft) => void;
  onRemove: () => void;
  tryable: { problemId: number; rounds: Option[] } | null;
}

function StepEditor({ step, index, errors, open, onToggle, onStep, onRemove, tryable }: StepEditorProps) {
  const at = `steps[${index}]`;
  const mine = errorsUnder(errors, at);
  const change = (patch: Partial<StepDraft>) => onStep({ ...step, ...patch });
  const side = (
    <>
      <Badge>{opensLabel(step.opens)}</Badge>
      <Badge tone="info">{kindLabel(step.kind)}</Badge>
      <Button small tone="link" onClick={onToggle}>{open ? t("staff.step.close") : t("staff.step.open")}</Button>
    </>
  );
  return (
    <Task no={t("staff.step.no", { order: index + 1 })} title={stepTitle(step) || t("staff.step.untitled")} side={side} state={mine.length ? "error" : "open"}>
      {open ? (
        <>
          <FormGrid>
            <Field label={t("staff.step.opens")} error={textUnder(errors, `${at}.opens`)}>
              <Select value={step.opens} options={OPENS_OPTIONS} onValue={(opens) => change({ opens: opens as StepDraft["opens"] })} />
            </Field>
            <Field label={t("staff.step.check")} error={textUnder(errors, `${at}.check.kind`)}>
              <Select value={step.kind} options={kindOptions(step.kind)} onValue={(kind) => change({ kind })} />
            </Field>
            <Field wide label={t("staff.step.body")} error={textUnder(errors, `${at}.body`)}>
              <TextArea rows={2} value={step.body} onValue={(body) => change({ body })} bad={Boolean(textUnder(errors, `${at}.body`))} />
            </Field>
            <Field wide label={t("staff.step.params")} error={textUnder(errors, `${at}.check.params`)}>
              <TextArea mono rows={2} value={step.paramsText} onValue={(paramsText) => change({ paramsText })} bad={Boolean(textUnder(errors, `${at}.check.params`))} />
            </Field>
            <EditorGroup wide label={t("staff.step.hints")}>
              <Inputs>
                {step.hints.map((hint, place) => (
                  <Input key={place} value={hint} aria-label={t("staff.step.hints")}
                    onValue={(text) => change({ hints: step.hints.map((was, which) => (which === place ? text : was)) })} />
                ))}
              </Inputs>
              <FieldNote>{textUnder(errors, `${at}.hints`)}</FieldNote>
            </EditorGroup>
          </FormGrid>
          <TryRow>
            <Button small onClick={() => change({ hints: [...step.hints, ""] })}>{t("staff.step.hint_add")}</Button>
            <Button small tone="danger" onClick={onRemove}>{t("staff.step.remove")}</Button>
          </TryRow>
          {tryable
            ? <StepTry problemId={tryable.problemId} order={index + 1} kind={step.kind} rounds={tryable.rounds} />
            : <TryRow><Text tone="muted" small>{t("staff.step.try_unsaved")}</Text></TryRow>}
        </>
      ) : undefined}
    </Task>
  );
}

export interface StepsEditorProps {
  steps: StepDraft[];
  onSteps: (steps: StepDraft[]) => void;
  errors: ShownError[];
  problemId: number | null;
  wargame: string;
}

export function StepsEditor({ steps, onSteps, errors, problemId, wargame }: StepsEditorProps) {
  const [opened, setOpened] = useState<Set<number>>(() => new Set([0]));
  const rounds = useEndedRounds(wargame);
  const toggle = (index: number) => setOpened((was) => {
    const next = new Set(was);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    return next;
  });
  const failing = (index: number) => errorsUnder(errors, `steps[${index}]`).length > 0;
  const stepsError = errors.filter((error) => error.path === "steps");
  return (
    <Section title={t("staff.steps.title")} sub={<Badge>{t("common.count", { count: steps.length })}</Badge>}
      actions={<Button small onClick={() => { onSteps([...steps, blankStep()]); setOpened((was) => new Set([...was, steps.length])); }}>{t("staff.steps.add")}</Button>}>
      {stepsError.length > 0 && <ErrorNotice error={{ errors: stepsError }} />}
      {steps.length === 0 && <Text tone="muted" small>{t("staff.steps.empty")}</Text>}
      {steps.map((step, index) => (
        <StepEditor key={index} step={step} index={index} errors={errors} open={opened.has(index) || failing(index)}
          onToggle={() => toggle(index)}
          onStep={(changed) => onSteps(steps.map((was, which) => (which === index ? changed : was)))}
          onRemove={() => onSteps(steps.filter((_, which) => which !== index))}
          tryable={problemId ? { problemId, rounds } : null} />
      ))}
    </Section>
  );
}

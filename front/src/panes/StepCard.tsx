import { useState } from "preact/hooks";
import type { Schemas } from "../api/client";
import { useAction, useResource } from "../api/hooks";
import { to } from "../links";
import { navigate, setHash } from "../router";
import { t, tFor } from "../strings";
import { AsideCard, AsideHead, Button, ErrorNotice, Input, Loading, Notice, Pane, Progress, Prose, Text, StepCardFrame, HintBox, StepRows, StepRow, FormActions, Form, type StepState } from "../ui";
import type { PaneProps } from "./types";

export type LessonShown = Schemas["LessonShown"];
export type StepLine = Schemas["StepLine"];

const NO_PANE = "none";
const LESSON_EVENTS = ["step.passed", "round.started", "round.ended"];

export function useLesson(round: number) {
  return useResource("/api/lessons/{round_id}/", { params: { round_id: round } }, { refreshOn: { round, kinds: LESSON_EVENTS } });
}

export function paneOfStep(step: StepLine | undefined): string | undefined {
  return step && step.opens !== NO_PANE ? step.opens : undefined;
}

export function currentStep(lesson: LessonShown | undefined): StepLine | undefined {
  if (!lesson || lesson.current === null) return undefined;
  return lesson.steps.find((step) => step.order === lesson.current);
}

function stateOf(step: StepLine, lesson: LessonShown): StepState {
  if (step.order <= lesson.progress.passed_order) return "done";
  return step.order === lesson.current ? "now" : "locked";
}

function lessonOver(lesson: LessonShown): boolean {
  return lesson.phase === "ended" || lesson.current === null;
}

interface TakenHint {
  n: number;
  text: string;
}

function StepNow({ round, step, total, onPassed }: { round: number; step: StepLine; total: number; onPassed: (next: number | null) => void }) {
  const ids = { params: { round_id: round, order: step.order } };
  const check = useAction("post", "/api/lessons/{round_id}/steps/{order}/check/");
  const askHint = useAction("post", "/api/lessons/{round_id}/steps/{order}/hint/");
  const [answer, setAnswer] = useState("");
  const [hints, setHints] = useState<TakenHint[]>([]);
  const [left, setLeft] = useState(step.hints_available);
  const verdict = check.data;

  const submit = async () => {
    const said = await check.run({ ...ids, body: { answer: answer.trim() || null } });
    if (said?.verdict === "passed") onPassed(said.next);
  };

  const nextHint = async () => {
    const said = await askHint.run({ ...ids, body: { n: hints.length + 1 } });
    if (!said) return;
    setHints((was) => [...was.filter((hint) => hint.n !== said.n), { n: said.n, text: said.hint }]);
    setLeft(said.left);
  };

  return (
    <StepCardFrame count={t("lesson.step_count", { order: step.order, total })}>
      <Prose>{step.body}</Prose>
      {hints.map((hint) => <HintBox key={hint.n} title={t("lesson.hint_title", { n: hint.n })}>{hint.text}</HintBox>)}
      <Form onSubmit={() => void submit()}>
        <Input value={answer} onValue={setAnswer} placeholder={t("lesson.answer")} aria-label={t("lesson.answer")} />
        <FormActions>
          <Button tone="primary" small type="submit" busy={check.busy}>{t("lesson.check")}</Button>
          {step.hints_available > 0 && (
            <Button small busy={askHint.busy} disabled={left <= 0} onClick={() => void nextHint()}>{t("lesson.hint_show")}</Button>
          )}
          {step.hints_available > 0 && <Text small tone="muted">{t("lesson.hints_left", { left })}</Text>}
        </FormActions>
      </Form>
      {verdict?.verdict === "not_yet" && (
        <Notice tone="warn" inline>{verdict.detail_code ? tFor("check", verdict.detail_code, undefined, "check.wrong_answer") : t("check.wrong_answer")}</Notice>
      )}
      {check.error && <ErrorNotice error={check.error} inline />}
      {askHint.error && <ErrorNotice error={askHint.error} inline />}
    </StepCardFrame>
  );
}

function StepOver({ lesson }: { lesson: LessonShown }) {
  const total = lesson.steps.length;
  const allPassed = lesson.progress.passed_order >= total;
  return (
    <StepCardFrame done count={t("lesson.progress_count", { passed: lesson.progress.passed_order, total })}>
      <Prose>{allPassed ? t("lesson.all_passed") : t("lesson.ended")}</Prose>
    </StepCardFrame>
  );
}

function StepList({ lesson }: { lesson: LessonShown }) {
  return (
    <AsideCard title={t("lesson.steps")}>
      <StepRows>
        {lesson.steps.map((step) => {
          const state = stateOf(step, lesson);
          return (
            <StepRow
              key={step.order}
              state={state}
              mark={state === "done" ? "✓" : step.order}
              body={step.body}
              label={state === "done" ? t("lesson.step_passed") : state === "locked" ? t("lesson.step_locked") : undefined}
            />
          );
        })}
      </StepRows>
    </AsideCard>
  );
}

function EndLesson({ round, over }: { round: number; over: boolean }) {
  const end = useAction("post", "/api/lessons/{round_id}/end/");
  const [asking, setAsking] = useState(false);

  const finish = async () => {
    if (!asking) {
      setAsking(true);
      return;
    }
    setAsking(false);
    if (await end.run({ params: { round_id: round } })) navigate(to.home());
  };

  return (
    <FormActions>
      {over
        ? <Button small href={to.home()}>{t("common.to_home")}</Button>
        : <Button small busy={end.busy} onClick={() => void finish()}>{asking ? t("lesson.end_confirm") : t("lesson.end")}</Button>}
      {end.error && <ErrorNotice error={end.error} inline />}
    </FormActions>
  );
}

function LessonNotes({ round, lesson, passedNow, onPassed }: { round: number; lesson: LessonShown; passedNow: number | undefined; onPassed: (order: number, next: number | null) => void }) {
  const step = currentStep(lesson);
  const over = lessonOver(lesson);
  return (
    <>
      {passedNow !== undefined && <Notice tone="ok" inline>{t("lesson.passed_step", { order: passedNow })}</Notice>}
      {step && !over
        ? <StepNow key={step.order} round={round} step={step} total={lesson.steps.length} onPassed={(next) => onPassed(step.order, next)} />
        : <StepOver lesson={lesson} />}
      <StepList lesson={lesson} />
      <EndLesson round={round} over={over} />
    </>
  );
}

function ProgressHead({ lesson }: { lesson: LessonShown | undefined }) {
  const total = lesson?.steps.length ?? 0;
  const passed = lesson?.progress.passed_order ?? 0;
  return (
    <AsideHead
      title={t("pane.step_card")}
      sub={[t("lesson.progress"), t("lesson.progress_count", { passed, total })]}
      progress={<Progress value={passed} max={total} label={t("lesson.progress")} />}
    />
  );
}

export function StepCard({ round, placement }: PaneProps) {
  const lesson = useLesson(round);
  const [passedNow, setPassedNow] = useState<number | undefined>(undefined);

  const passed = (order: number, next: number | null) => {
    setPassedNow(order);
    const opens = paneOfStep(lesson.data?.steps.find((step) => step.order === next));
    if (opens) setHash(opens);
    lesson.reload();
  };

  const body = !lesson.data
    ? lesson.error ? <ErrorNotice error={lesson.error} /> : <Loading>{t("common.loading")}</Loading>
    : <LessonNotes round={round} lesson={lesson.data} passedNow={passedNow} onPassed={passed} />;

  if (placement === "aside-lead") {
    return (
      <>
        <ProgressHead lesson={lesson.data} />
        {body}
      </>
    );
  }
  if (placement === "aside") return <AsideCard title={t("pane.step_card")}>{body}</AsideCard>;
  const total = lesson.data?.steps.length ?? 0;
  return <Pane title={t("pane.step_card")} meta={t("lesson.progress_count", { passed: lesson.data?.progress.passed_order ?? 0, total })}>{body}</Pane>;
}

import { useEffect } from "preact/hooks";
import { waitForLesson } from "../api/client";
import { holdLease } from "../api/follow";
import { Console } from "../console/Console";
import { layouts, type RailEntry } from "../layouts";
import { currentStep, paneOfStep, useLesson, type LessonShown } from "../panes/StepCard";
import type { PaneId } from "../panes/registry";
import type { PageProps } from "../routes";
import { AppPage } from "../shell/AppPage";
import { t, tFor } from "../strings";
import { ErrorNotice, Loading, Notice, PageBody } from "../ui";

const READY_PHASES = ["ready", "ended"];

function railFor(lesson: LessonShown): RailEntry[] {
  const named = new Set(lesson.steps.map((step) => step.opens));
  const always = layouts.lesson.railAlways ?? [];
  const shown = layouts.lesson.rail.filter((entry) => named.has(entry.pane) || always.includes(entry.pane));
  return shown.length > 0 ? shown : layouts.lesson.rail;
}

function openPane(lesson: LessonShown): PaneId | undefined {
  const opens = paneOfStep(currentStep(lesson));
  return layouts.lesson.rail.find((entry) => entry.pane === opens)?.pane;
}

export function Lesson({ params }: PageProps) {
  const round = Number(params.round);
  const lesson = useLesson(round);
  const shown = lesson.data;
  const ready = shown ? READY_PHASES.includes(shown.phase) : false;
  const crumbs = [{ label: shown?.problem.title ?? t("page.lesson") }, { label: t("page.lesson") }];

  useEffect(() => holdLease(round, shown?.lease), [round, shown?.lease]);

  useEffect(() => {
    if (!shown || ready) return undefined;
    const abort = new AbortController();
    waitForLesson(round, { signal: abort.signal, onRead: lesson.setData }).catch(() => undefined);
    return () => abort.abort();
  }, [round, shown?.phase]);

  if (!shown || !ready) {
    return (
      <AppPage console title={t("page.lesson")} crumbs={crumbs}>
        <PageBody narrow>
          {lesson.error
            ? <ErrorNotice error={lesson.error} />
            : shown
              ? <Notice tone="info" title={tFor("phase", shown.phase)}>{t("lesson.waiting")}</Notice>
              : <Loading>{t("common.loading")}</Loading>}
        </PageBody>
      </AppPage>
    );
  }

  return (
    <Console
      spec={layouts.lesson}
      round={round}
      title={shown.problem.title || t("page.lesson")}
      crumbs={crumbs}
      rail={railFor(shown)}
      open={openPane(shown)}
    />
  );
}

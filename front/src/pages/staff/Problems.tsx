import { useState } from "preact/hooks";
import { to } from "../../links";
import type { PageProps } from "../../routes";
import { navigate } from "../../router";
import { AppPage } from "../../shell/AppPage";
import { t } from "../../strings";
import { Button, Empty, PageBody, Section, Stack, Split } from "../../ui";
import { ProblemEditor } from "../../panes/staff/ProblemEditor";
import { ImportButton, ImportErrors, useProblemImport } from "../../panes/staff/ProblemImport";
import { ProblemList } from "../../panes/staff/ProblemList";

const NEW_PROBLEM = "new";

export function Problems({ params }: PageProps) {
  const [changes, setChanges] = useState(0);
  const changed = () => setChanges((was) => was + 1);
  const opened = params.id === NEW_PROBLEM ? null : params.id ? Number(params.id) : undefined;
  const imported = useProblemImport((id) => {
    changed();
    navigate(to.staffProblem(id));
  });
  return (
    <AppPage title={t("page.staff.problems")} crumbs={[{ label: t("page.staff.problems") }]}>
      <PageBody>
        <Stack gap="md">
          <Section large title={t("page.staff.problems")}
            actions={<>
              <ImportButton busy={imported.busy} onFile={(file) => void imported.pick(file)} />
              <Button tone="primary" href={`${to.staffProblems()}/${NEW_PROBLEM}`}>{t("staff.problems.new")}</Button>
            </>} />
          <ImportErrors errors={imported.errors} />
          <Split list={<ProblemList current={opened ?? null} version={changes} />}>
            {opened === undefined
              ? <Empty>{t("staff.problems.pick")}</Empty>
              : <ProblemEditor key={params.id} problemId={opened}
                onSaved={(id) => { changed(); if (id !== opened) navigate(to.staffProblem(id), true); }}
                onDeleted={() => { changed(); navigate(to.staffProblems(), true); }} />}
          </Split>
        </Stack>
      </PageBody>
    </AppPage>
  );
}

import { useEffect } from "preact/hooks";
import { to } from "../../links";
import { ErrorNotice, Loading, PickList } from "../../ui";
import { grouped, useStaffProblems, useWargames, wargameLabel } from "./catalog";
import { t, tFor } from "../../strings";

export interface ProblemListProps {
  current: number | null;
  version: number;
}

export function ProblemList({ current, version }: ProblemListProps) {
  const problems = useStaffProblems();
  const { wargames } = useWargames();
  const seen = problems.data ?? [];
  const { reload } = problems;
  useEffect(() => {
    if (version) reload();
  }, [version, reload]);
  if (problems.loading && !problems.data) return <Loading>{t("common.loading")}</Loading>;
  if (problems.error) return <ErrorNotice error={problems.error} />;
  const groups = grouped(seen.slice().sort((one, two) => one.id - two.id), (problem) => problem.wargame, wargames).map((group) => ({
    title: wargameLabel(wargames, group.wargame),
    items: group.items.map((problem) => ({
      id: problem.id,
      no: problem.id,
      title: problem.title,
      sub: [`${tFor("kind", problem.kind)} · ${tFor("side", problem.side)}`],
      badge: problem.published ? { tone: "ok" as const, text: t("staff.published") } : { tone: "muted" as const, text: t("staff.unpublished") },
      href: to.staffProblem(problem.id),
      current: problem.id === current,
    })),
  }));
  return <PickList title={t("staff.problems.list")} count={t("common.count", { count: seen.length })} groups={groups} empty={t("staff.problems.empty")} />;
}

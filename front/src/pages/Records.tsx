import type { Schemas } from "../api/client";
import { useResource } from "../api/hooks";
import { clock, day } from "../format";
import { to } from "../links";
import { ScoreReport } from "../panes/Score";
import type { PageProps } from "../routes";
import { AppPage } from "../shell/AppPage";
import { t, tFor } from "../strings";
import { Badge, Button, ErrorNotice, Hero, Loading, PageBody, Section, Stack, Table, Text, type Column } from "../ui";
import { DebriefReport, stepsLine } from "./Debrief";
import { wargameName } from "./wargameText";

type RecordLine = Schemas["RecordLine"];
type Standing = Schemas["Standing"];
type DebriefShown = Schemas["Debrief"];
type ScoreShown = Schemas["Score"];

export function standingText(standing: Standing | null | undefined): string {
  return standing ? t("result.standing", { n: standing.n, top: Math.round(standing.top_percent) }) : "";
}

function problemTitle(line: { problem_title: string | null; wargame: string | null }): string {
  return line.problem_title ?? (line.wargame ? wargameName(line.wargame) : "—");
}

function endedAt(line: RecordLine): string {
  return line.ended ? `${day(line.ended)} ${clock(line.ended)}` : "—";
}

export function Records(_props: PageProps) {
  const records = useResource("/api/records/", {});
  const columns: Column<RecordLine>[] = [
    { key: "round", label: t("col.round"), kind: "strong", cell: (line) => t("round.name", { round: line.round_number }) },
    { key: "problem", label: t("col.problem"), kind: "nowrap", cell: problemTitle },
    { key: "matchup", label: t("col.matchup"), kind: "nowrap", cell: (line) => tFor("matchup", line.matchup) },
    { key: "steps", label: t("records.col.steps"), kind: "nowrap", cell: (line) => stepsLine(line.steps) || "—" },
    { key: "ended", label: t("records.col.ended"), kind: "mono", cell: endedAt },
    {
      key: "reason", label: t("col.state"), kind: "nowrap",
      cell: (line) => (line.incomplete ? <Badge tone="warn">{t("records.incomplete")}</Badge> : tFor("end_reason", line.end_reason)),
    },
    { key: "standing", label: t("records.col.standing"), cell: (line) => standingText(line.standing) || <Text tone="faint">{t("records.standing_none")}</Text> },
    { key: "open", label: "", kind: "end", cell: (line) => <Button tone="link" small href={to.record(line.record)}>{t("records.open")}</Button> },
  ];
  return (
    <AppPage title={t("page.records")} crumbs={[{ label: t("page.records") }]}>
      <PageBody>
        <Section title={t("page.records")} sub={t("records.lead")}>
          <Stack>
            {records.error && <ErrorNotice error={records.error} />}
            {!records.data && records.loading && <Loading>{t("common.loading")}</Loading>}
            {records.data && <Table columns={columns} rows={records.data} rowKey={(line) => line.record} empty={t("records.none")} />}
          </Stack>
        </Section>
      </PageBody>
    </AppPage>
  );
}

function debriefOf(value: unknown): DebriefShown | null {
  return value && typeof value === "object" && "timeline" in value ? (value as DebriefShown) : null;
}

export function RecordPage({ params }: PageProps) {
  const id = Number(params.record);
  const shown = useResource("/api/records/{record_id}/", { params: { record_id: id } });
  const record = shown.data;
  const debrief = debriefOf(record?.debrief);
  const title = record ? t("round.name", { round: record.round_number }) : t("page.record");
  const lead = record
    ? [[problemTitle(record), tFor("matchup", record.matchup), stepsLine(record.steps), endedAt(record)].filter(Boolean).join(" · ")]
    : [];
  const standing = standingText(record?.standing);
  return (
    <AppPage title={t("page.record")} crumbs={[{ label: t("page.records"), href: to.records() }, { label: title }]}>
      <Hero icon="shield" title={title} lead={standing ? [...lead, standing] : lead}
        badge={record?.incomplete ? <Badge tone="warn">{t("records.incomplete")}</Badge> : undefined} />
      <PageBody>
        {shown.error && <ErrorNotice error={shown.error} />}
        {!record && !shown.error && <Loading>{t("common.loading")}</Loading>}
        {record && debrief && <DebriefReport debrief={debrief} />}
        {record && !debrief && record.score ? <ScoreReport score={record.score as ScoreShown} /> : null}
      </PageBody>
    </AppPage>
  );
}

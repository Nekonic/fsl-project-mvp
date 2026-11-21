import { useEffect, useState } from "preact/hooks";
import { useAction } from "../api/hooks";
import { clock } from "../format";
import { setHash } from "../router";
import { t } from "../strings";
import { AsideCard, Badge, Button, Card, ErrorNotice, Form, FormActions, ListRow, Pane, PaneSection, Text, TextArea, PaneColumn } from "../ui";
import { attackWritesOpen, useAttackState } from "./Origins";
import type { PaneProps } from "./types";

export interface LootSubmission {
  at: string;
  lost: boolean;
  objective: string | null;
}

const submitted = new Map<number, LootSubmission[]>();
const watchers = new Set<() => void>();

function remember(round: number, submission: LootSubmission): void {
  submitted.set(round, [submission, ...(submitted.get(round) ?? [])]);
  watchers.forEach((watcher) => watcher());
}

function useSubmissions(round: number): LootSubmission[] {
  const [, setSeen] = useState(0);
  useEffect(() => {
    const watcher = () => setSeen((was) => was + 1);
    watchers.add(watcher);
    return () => {
      watchers.delete(watcher);
    };
  }, []);
  return submitted.get(round) ?? [];
}

function asLoot(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function SubmissionRow({ submission }: { submission: LootSubmission }) {
  return (
    <ListRow
      id={<Text mono tone="muted">{clock(submission.at)}</Text>}
      main={<Text strong>{submission.objective ?? t("loot.no_match")}</Text>}
      side={submission.lost ? <Badge tone="danger">{t("objective.lost")}</Badge> : <Badge tone="muted">{t("loot.not_taken")}</Badge>}
    />
  );
}

function LootForm({ round }: { round: number }) {
  const state = useAttackState(round);
  const loot = useAction("post", "/api/rounds/{round_id}/attack/loot/");
  const [text, setText] = useState("");
  const open = attackWritesOpen(state.data);

  const submit = async () => {
    if (!text.trim()) return;
    const said = await loot.run({ params: { round_id: round }, body: { value: asLoot(text) } });
    if (!said) return;
    remember(round, { at: new Date().toISOString(), lost: said.lost, objective: said.objective?.name ?? null });
    if (said.lost) state.reload();
  };

  return (
    <Card pad="sm">
      <Form onSubmit={() => void submit()}>
        <TextArea mono rows={7} value={text} onValue={setText} label={t("pane.loot")} disabled={!open} />
        <FormActions>
          <Button tone="danger" small type="submit" busy={loot.busy} disabled={!open || !text.trim()}>{t("loot.submit")}</Button>
        </FormActions>
        {loot.error && <ErrorNotice error={loot.error} />}
      </Form>
    </Card>
  );
}

export function Loot({ round, placement }: PaneProps) {
  const submissions = useSubmissions(round);
  const last = submissions[0];

  if (placement !== "main") {
    return (
      <AsideCard title={t("loot.title")} meta={last ? t("loot.last", { at: clock(last.at) }) : undefined}>
        <span>
          <Button small onClick={() => setHash("loot")}>{t("loot.open")}</Button>
        </span>
      </AsideCard>
    );
  }

  return (
    <Pane>
      <PaneColumn>
        <PaneSection title={t("loot.title")}>
          <Text small tone="muted">{t("loot.lead")}</Text>
          <LootForm round={round} />
        </PaneSection>
        {submissions.length > 0 && (
          <PaneSection title={t("loot.results")}>
            <Card list>
              {submissions.map((submission, index) => <SubmissionRow key={`${submission.at}-${index}`} submission={submission} />)}
            </Card>
          </PaneSection>
        )}
      </PaneColumn>
    </Pane>
  );
}

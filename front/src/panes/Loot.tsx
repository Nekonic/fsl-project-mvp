import { useEffect, useState } from "preact/hooks";
import { useAction } from "../api/hooks";
import { clock } from "../format";
import { setHash } from "../router";
import { t } from "../strings";
import { AsideCard, Badge, Button, Card, ErrorNotice, Form, FormActions, ListRow, Pane, PaneSection, Text, TextArea, PaneColumn } from "../ui";
import { objectivesChanged } from "./Objectives";
import { attackWritesOpen, useAttackState } from "./Origins";
import type { PaneProps } from "./types";

export interface LootSubmission {
  at: string;
  lost: boolean;
  objectives: string[];
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

function isPair(row: unknown): boolean {
  if (Array.isArray(row)) return row.length === 2 && typeof row[0] === "string" && typeof row[1] === "string";
  if (!row || typeof row !== "object") return false;
  const { username, hash, password } = row as Record<string, unknown>;
  return typeof username === "string" && typeof (hash ?? password) === "string";
}

export function lootOf(text: string): unknown {
  let value: unknown;
  try {
    value = JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
  if (Array.isArray(value)) return value.some(isPair) ? value : undefined;
  if (value && typeof value === "object") return Object.values(value).some((digest) => typeof digest === "string") ? value : undefined;
  return undefined;
}

export function fallenNames(said: { objective: { name: string } | null; objectives?: Array<{ name: string }> }): string[] {
  if (said.objectives?.length) return said.objectives.map((objective) => objective.name);
  return said.objective ? [said.objective.name] : [];
}

export function SubmissionRow({ submission }: { submission: LootSubmission }) {
  return (
    <ListRow
      id={<Text mono tone="muted">{clock(submission.at)}</Text>}
      main={submission.lost ? <Text strong>{submission.objectives.join(", ")}</Text> : <Text tone="muted">{t("loot.no_match")}</Text>}
      side={submission.lost ? <Badge tone="danger">{t("objective.lost")}</Badge> : undefined}
    />
  );
}

function LootForm({ round }: { round: number }) {
  const state = useAttackState(round);
  const loot = useAction("post", "/api/rounds/{round_id}/attack/loot/");
  const [text, setText] = useState("");
  const [unreadable, setUnreadable] = useState(false);
  const open = attackWritesOpen(state.data);

  const submit = async () => {
    if (!text.trim()) return;
    const value = lootOf(text);
    setUnreadable(value === undefined);
    if (value === undefined) return;
    const said = await loot.run({ params: { round_id: round }, body: { value } });
    if (!said) return;
    remember(round, { at: new Date().toISOString(), lost: said.lost, objectives: fallenNames(said) });
    if (said.lost) {
      state.reload();
      objectivesChanged(round);
    }
  };

  return (
    <Card pad="sm">
      <Form onSubmit={() => void submit()}>
        <TextArea mono rows={7} value={text} onValue={(typed) => { setText(typed); setUnreadable(false); }} label={t("pane.loot")} disabled={!open} />
        <FormActions>
          <Button tone="danger" small type="submit" busy={loot.busy} disabled={!open || !text.trim()}>{t("loot.submit")}</Button>
        </FormActions>
        {unreadable && <Text tone="danger" small>{t("error.loot_format")}</Text>}
        {!unreadable && loot.error && <ErrorNotice error={loot.error} />}
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

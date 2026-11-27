import type { Schemas } from "../../api/client";
import { errorLine, t, tFor, type ShownError } from "../../strings";
import { Checkbox, Field, FormGrid, Input, Row, Select, Stack, Subhead, Text, type Option, EditorGroup, FieldNote, LineList, WithUnit } from "../../ui";
import { MATCHUPS, textUnder, type SetupBody } from "./document";

export interface RoundSetupEditorProps {
  setup: SetupBody;
  onSetup: (setup: SetupBody) => void;
  errors: ShownError[];
  postures: Option[];
  steps: Schemas["StepLine"][];
  cards: Schemas["CardLine"][];
  objectiveNames?: Record<string, string>;
}

export function objectiveLabel(names: Record<string, string>, key: string): string {
  const name = names[key];
  return name ? `${name} · ${key}` : key;
}

function toggled(list: string[], item: string, on: boolean): string[] {
  return on ? [...list.filter((was) => was !== item), item] : list.filter((was) => was !== item);
}

function whole(text: string): number {
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) ? 0 : value;
}

function lineNote(errors: ShownError[], path: string): string | undefined {
  const found = errors.filter((error) => error.path === path);
  return found.length ? found.map(errorLine).join(" ") : undefined;
}

export function RoundSetupEditor({ setup, onSetup, errors, postures, steps, cards, objectiveNames = {} }: RoundSetupEditorProps) {
  const change = (patch: Partial<SetupBody>) => onSetup({ ...setup, ...patch });
  const cases = setup.probe_cases ?? [];
  const objectives = setup.objectives ?? [];
  const botSteps = setup.bot_steps ?? [];
  const chosenCards = setup.cards ?? [];
  const toggleMatchup = (matchup: SetupBody["matchups"][number], on: boolean) => change({ matchups: toggled(setup.matchups, matchup, on) as SetupBody["matchups"] });
  const postureOptions: Option[] = [{ value: "", label: t("common.none") }, ...postures];
  if (setup.posture && !postures.some((option) => option.value === setup.posture)) postureOptions.push({ value: setup.posture, label: setup.posture });

  return (
    <>
      <Subhead>{t("staff.round.title")}</Subhead>
      <EditorGroup label={t("staff.round.matchups")}>
        <Row wide>
          {MATCHUPS.map((matchup) => (
            <Checkbox key={matchup} checked={setup.matchups.includes(matchup)} onChecked={(on) => toggleMatchup(matchup, on)} label={t(`matchup.${matchup}`)} />
          ))}
        </Row>
        <FieldNote>{textUnder(errors, "round.matchups")}</FieldNote>
      </EditorGroup>

      <FormGrid>
        <EditorGroup label={t("staff.round.bot_steps")}>
          <Row wide>
            {steps.map((step) => (
              <Checkbox key={step.id} checked={botSteps.includes(step.id)} label={tFor("bot_step", step.id)}
                onChecked={(on) => change({ bot_steps: toggled(botSteps, step.id, on) })} />
            ))}
          </Row>
          <FieldNote>{textUnder(errors, "round.bot_steps")}</FieldNote>
        </EditorGroup>
        <EditorGroup label={t("staff.round.cards")}>
          <Stack gap="sm">
            <Text tone="muted" small>{t("staff.round.cards_lead")}</Text>
            {cards.length
              ? cards.map((card) => (
                <Checkbox key={card.id} checked={chosenCards.includes(card.id)} label={`${card.id} · ${card.technique} ${card.name}`}
                  onChecked={(on) => change({ cards: toggled(chosenCards, card.id, on) })} />
              ))
              : <Text tone="faint" small>{t("staff.round.cards_none")}</Text>}
          </Stack>
          <FieldNote>{textUnder(errors, "round.cards")}</FieldNote>
        </EditorGroup>
      </FormGrid>

      <FormGrid>
        <EditorGroup label={t("staff.round.probe_cases")}>
          <LineList
            lines={cases.map((name, index) => ({ text: name, bad: Boolean(lineNote(errors, `round.probe_cases[${index}]`)), note: lineNote(errors, `round.probe_cases[${index}]`) }))}
            removeLabel={t("staff.remove")} onRemove={(index) => change({ probe_cases: cases.filter((_, which) => which !== index) })}
            addLabel={t("staff.round.case_add")} placeholder={t("staff.round.case_placeholder")}
            onAdd={(name) => change({ probe_cases: [...cases, name] })} />
        </EditorGroup>
        <EditorGroup label={t("staff.round.objectives")}>
          <LineList
            lines={objectives.map((key, index) => ({ text: objectiveLabel(objectiveNames, key), bad: Boolean(lineNote(errors, `round.objectives[${index}]`)), note: lineNote(errors, `round.objectives[${index}]`) }))}
            removeLabel={t("staff.remove")} onRemove={(index) => change({ objectives: objectives.filter((_, which) => which !== index) })}
            addLabel={t("staff.round.objective_add")} placeholder={t("staff.round.objective_placeholder")}
            onAdd={(key) => change({ objectives: [...objectives, key] })} />
        </EditorGroup>
      </FormGrid>

      <FormGrid>
        <Field label={t("staff.round.benign_every")} error={textUnder(errors, "round.benign_every_s")}>
          <WithUnit unit={t("staff.seconds")}>
            <Input mono inputMode="numeric" value={setup.benign_every_s ?? ""} onValue={(text) => change({ benign_every_s: whole(text) })} />
          </WithUnit>
        </Field>
        <Field label={t("staff.round.time_limit")} error={textUnder(errors, "round.time_limit_s")}>
          <WithUnit unit={t("staff.seconds")}>
            <Input mono inputMode="numeric" value={setup.time_limit_s ?? ""} onValue={(text) => change({ time_limit_s: text.trim() ? whole(text) : null })} />
          </WithUnit>
        </Field>
        <Field label={t("staff.problem.start_posture")} error={textUnder(errors, "round.posture")}>
          <Select value={setup.posture ?? ""} options={postureOptions} onValue={(name) => change({ posture: name || null })} />
        </Field>
      </FormGrid>
    </>
  );
}

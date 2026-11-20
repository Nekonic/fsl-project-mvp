import { errorLine, t, type ShownError } from "../../strings";
import { Checkbox, Field, FormGrid, Input, Row, Select, Subhead, type Option, EditorGroup, FieldNote, HpGrid, LineList, WithUnit } from "../../ui";
import { HP_FIELDS, MATCHUPS, textUnder, type SetupBody } from "./document";

export interface RoundSetupEditorProps {
  setup: SetupBody;
  onSetup: (setup: SetupBody) => void;
  errors: ShownError[];
  postures: Option[];
}

function whole(text: string): number {
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) ? 0 : value;
}

function lineNote(errors: ShownError[], path: string): string | undefined {
  const found = errors.filter((error) => error.path === path);
  return found.length ? found.map(errorLine).join(" ") : undefined;
}

export function RoundSetupEditor({ setup, onSetup, errors, postures }: RoundSetupEditorProps) {
  const change = (patch: Partial<SetupBody>) => onSetup({ ...setup, ...patch });
  const cases = setup.probe_cases ?? [];
  const objectives = setup.objectives ?? [];
  const toggleMatchup = (matchup: SetupBody["matchups"][number], on: boolean) =>
    change({ matchups: on ? [...setup.matchups.filter((was) => was !== matchup), matchup] : setup.matchups.filter((was) => was !== matchup) });
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
        <EditorGroup label={t("staff.round.probe_cases")}>
          <LineList
            lines={cases.map((name, index) => ({ text: name, bad: Boolean(lineNote(errors, `round.probe_cases[${index}]`)), note: lineNote(errors, `round.probe_cases[${index}]`) }))}
            removeLabel={t("staff.remove")} onRemove={(index) => change({ probe_cases: cases.filter((_, which) => which !== index) })}
            addLabel={t("staff.round.case_add")} placeholder={t("staff.round.case_placeholder")}
            onAdd={(name) => change({ probe_cases: [...cases, name] })} />
        </EditorGroup>
        <EditorGroup label={t("staff.round.objectives")}>
          <LineList
            lines={objectives.map((key, index) => ({ text: key, bad: Boolean(lineNote(errors, `round.objectives[${index}]`)), note: lineNote(errors, `round.objectives[${index}]`) }))}
            removeLabel={t("staff.remove")} onRemove={(index) => change({ objectives: objectives.filter((_, which) => which !== index) })}
            addLabel={t("staff.round.objective_add")} placeholder={t("staff.round.objective_placeholder")}
            onAdd={(key) => change({ objectives: [...objectives, key] })} />
        </EditorGroup>
      </FormGrid>

      <EditorGroup label={t("staff.round.hp")}>
        <HpGrid>
          {HP_FIELDS.map((name) => (
            <Field key={name} label={t(`staff.round.hp.${name}`)} error={textUnder(errors, `round.hp.${name}`)}>
              <Input mono inputMode="numeric" value={setup.hp[name]} bad={Boolean(textUnder(errors, `round.hp.${name}`))}
                onValue={(text) => change({ hp: { ...setup.hp, [name]: whole(text) } })} />
            </Field>
          ))}
        </HpGrid>
      </EditorGroup>

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

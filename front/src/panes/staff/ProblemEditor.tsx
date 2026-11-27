import { useEffect, useState } from "preact/hooks";
import { api, ApiError } from "../../api/client";
import { useAction, useResource } from "../../api/hooks";
import { errorLine, errorText, t, type ShownError } from "../../strings";
import { Button, ErrorList, ErrorNotice, Field, FormGrid, Input, Loading, Select, Stack, Switch, Text, TextArea, type Option, Chips, EditorCard, EditorGroup, EditorHead, EditorSection, EditorStrip, PublishRow } from "../../ui";
import { objectiveNamesOf, usePostures, useWargames, wargameLabel } from "./catalog";
import { asShownErrors, blankDraft, built, downloadJson, draftOf, postureInline, SIDES, textUnder, type Draft } from "./document";
import { BaselinePanel } from "./BaselinePanel";
import { RoundSetupEditor } from "./RoundSetupEditor";

export interface ProblemEditorProps {
  problemId: number | null;
  onSaved: (id: number) => void;
  onDeleted: () => void;
}

const SIDE_OPTIONS: Option[] = SIDES.map((side) => ({ value: side, label: t(`side.${side}`) }));
const HELD_APART = ["stale_revision", "in_use"];

export function ProblemEditor({ problemId, onSaved, onDeleted }: ProblemEditorProps) {
  const stored = useResource("/api/staff/problems/{problem_id}/", problemId ? { params: { problem_id: problemId } } : null);
  const { wargames } = useWargames();
  const postures = usePostures();
  const steps = useResource("/api/bot-steps/", {});
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<ShownError[]>([]);
  const [checked, setChecked] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [exportError, setExportError] = useState<ApiError | undefined>(undefined);
  const create = useAction("post", "/api/staff/problems/");
  const update = useAction("put", "/api/staff/problems/{problem_id}/");
  const validate = useAction("post", "/api/staff/problems/validate/");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<ApiError | undefined>(undefined);
  const saveError = problemId ? update.error : create.error;

  useEffect(() => {
    if (stored.data) setDraft(draftOf(stored.data));
  }, [stored.data]);
  useEffect(() => {
    if (saveError) setErrors(saveError.errors.filter((error) => !HELD_APART.includes(error.code)));
  }, [saveError]);
  useEffect(() => {
    if (problemId === null && draft === null && wargames.length) setDraft(blankDraft(wargames[0]?.id ?? ""));
  }, [problemId, draft, wargames]);

  if (problemId !== null && stored.error) return <ErrorNotice error={stored.error} />;
  if (!draft) return <Loading>{t("common.loading")}</Loading>;

  const revision = stored.data?.problem.revision;
  const chosenWargame = wargames.find((wargame) => wargame.id === draft.problem.wargame);
  const change = (patch: Partial<Draft>) => {
    setDraft({ ...draft, ...patch });
    setChecked(false);
  };
  const changeProblem = (patch: Partial<Draft["problem"]>) => change({ problem: { ...draft.problem, ...patch } });
  const stale = update.error?.has("stale_revision") ? update.error : undefined;

  const runCheck = async () => {
    const said = await validate.run({ body: built(draft) });
    setErrors(asShownErrors(said?.errors ?? []));
    setChecked(Boolean(said) && said?.ok === true);
  };

  const runSave = async () => {
    const body = built(draft);
    setChecked(false);
    const said = problemId && revision !== undefined
      ? await update.run({ params: { problem_id: problemId }, body: { ...body, base_revision: revision } })
      : await create.run({ body });
    if (!said) return;
    setErrors([]);
    if (problemId) stored.setData(said);
    onSaved(said.problem.id);
  };

  const runExport = async () => {
    if (!problemId) return;
    setExportError(undefined);
    try {
      downloadJson(`problem-${problemId}.json`, await api.get("/api/staff/problems/{problem_id}/export/", { params: { problem_id: problemId } }));
    } catch (failed) {
      if (failed instanceof ApiError) setExportError(failed);
    }
  };

  const runDelete = async () => {
    if (!problemId) return;
    setConfirming(false);
    setDeleting(true);
    setDeleteError(undefined);
    try {
      await api.delete("/api/staff/problems/{problem_id}/", { params: { problem_id: problemId } });
      onDeleted();
    } catch (failed) {
      setDeleteError(failed instanceof ApiError ? failed : new ApiError(0, [{ path: "", code: "network" }]));
    } finally {
      setDeleting(false);
    }
  };

  const wargameOptions: Option[] = wargames.map((wargame) => ({ value: wargame.id, label: wargameLabel(wargames, wargame.id) }));
  if (!wargames.some((wargame) => wargame.id === draft.problem.wargame)) wargameOptions.push({ value: draft.problem.wargame, label: draft.problem.wargame });
  const ownPostures = (postures.data ?? []).filter((posture) => posture.wargame === draft.problem.wargame);
  const postureOptions: Option[] = ownPostures.map((posture) => ({ value: posture.name, label: posture.name }));
  const startName = draft.start_posture?.name ?? "";
  const startOptions: Option[] = [{ value: "", label: t("common.none") }, ...postureOptions];
  if (startName && !postureOptions.some((option) => option.value === startName)) startOptions.push({ value: startName, label: startName });
  const pathed = errors.map((error) => ({ path: error.path, text: errorLine(error) }));
  const bad = (path: string) => Boolean(textUnder(errors, path));

  const publish = (
    <PublishRow ruled
      end={problemId && (confirming
        ? <>
          <Button small tone="danger" busy={deleting} onClick={() => void runDelete()}>{t("staff.delete_confirm")}</Button>
          <Button small onClick={() => setConfirming(false)}>{t("common.cancel")}</Button>
        </>
        : <Button small busy={deleting} onClick={() => setConfirming(true)}>{t("staff.delete")}</Button>)}
      note={deleteError ? errorText(deleteError) : undefined}>
      <Switch checked={draft.problem.published} onChecked={(published) => changeProblem({ published })} label={t("staff.publish")} />
      <Text strong small>{draft.problem.published ? t("staff.published") : t("staff.unpublished")}</Text>
    </PublishRow>
  );

  return (
    <Stack gap="lg">
      <EditorCard>
        <EditorHead
          eyebrow={problemId && revision !== undefined ? t("staff.problem.eyebrow", { id: problemId, revision }) : t("staff.problem.new_title")}
          title={draft.problem.title || t("staff.problem.new_title")}
          actions={<>
            <Button busy={validate.busy} onClick={() => void runCheck()}>{t("common.validate")}</Button>
            {problemId && <Button onClick={() => void runExport()}>{t("staff.export")}</Button>}
            <Button tone="primary" busy={create.busy || update.busy} onClick={() => void runSave()}>{t("staff.save")}</Button>
          </>} />

        {stale && (
          <EditorStrip tone="danger" title={errorText(stale)}
            action={<Button small onClick={() => { update.reset(); setErrors([]); stored.reload(); }}>{t("common.reload")}</Button>}>
            <Text tone="muted">{t("staff.stale_now", { revision: String(stale.param("current_revision") ?? "") })}</Text>
          </EditorStrip>
        )}
        {exportError && <EditorStrip tone="danger" title={errorText(exportError)} />}
        {validate.error && <EditorStrip tone="danger" title={errorText(validate.error)} />}
        {pathed.length > 0 && (
          <EditorStrip title={t("staff.errors_title", { count: pathed.length })}>
            <ErrorList items={pathed} />
          </EditorStrip>
        )}
        {checked && <EditorStrip tone="ok" title={t("staff.valid")} />}

        <EditorSection ruled>
          <FormGrid>
            <EditorGroup label={t("staff.problem.side")}>
              <Chips value={draft.problem.side} options={SIDE_OPTIONS} label={t("staff.problem.side")}
                onValue={(side) => changeProblem({ side: side as Draft["problem"]["side"] })} />
            </EditorGroup>
            <Field label={t("col.wargame")} error={textUnder(errors, "problem.wargame")}>
              <Select value={draft.problem.wargame} options={wargameOptions} bad={bad("problem.wargame")} onValue={(wargame) => changeProblem({ wargame })} />
            </Field>
            <Field label={t("staff.problem.start_posture")} error={textUnder(errors, "start_posture")}>
              <Select value={startName} options={startOptions} bad={bad("start_posture")}
                onValue={(name) => {
                  const picked = ownPostures.find((posture) => posture.name === name);
                  change({ start_posture: picked ? postureInline(picked) : name ? draft.start_posture : null });
                }} />
            </Field>
            <Field wide label={t("staff.problem.title")} error={textUnder(errors, "problem.title")}>
              <Input value={draft.problem.title} bad={bad("problem.title")} onValue={(title) => changeProblem({ title })} />
            </Field>
            <Field wide label={t("staff.problem.summary")} error={textUnder(errors, "problem.summary")}>
              <TextArea rows={3} value={draft.problem.summary} bad={bad("problem.summary")} onValue={(summary) => changeProblem({ summary })} />
            </Field>
            <Field wide label={t("staff.problem.body")} error={textUnder(errors, "problem.body")}>
              <TextArea rows={6} value={draft.problem.body} bad={bad("problem.body")} onValue={(body) => changeProblem({ body })} />
            </Field>
          </FormGrid>
        </EditorSection>

        <EditorSection>
          <RoundSetupEditor setup={draft.round} onSetup={(round) => change({ round })} errors={errors} postures={postureOptions}
            steps={steps.data ?? []} cards={chosenWargame?.cards ?? []} objectiveNames={objectiveNamesOf(chosenWargame)} />
          <BaselinePanel problemId={problemId} saved={stored.data?.round} />
          {publish}
        </EditorSection>
      </EditorCard>
    </Stack>
  );
}

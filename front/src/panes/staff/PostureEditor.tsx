import { useEffect, useState } from "preact/hooks";
import { useAction, useResource } from "../../api/hooks";
import { errorText, type ShownError, t } from "../../strings";
import { Badge, Button, ErrorNotice, Field, FormGrid, Input, Loading, Select, Text, type Option, EditorBand, EditorCard, EditorHead, EditorSection, EditorStrip, CodeEditor } from "../../ui";
import { useWargames, wargameLabel } from "./catalog";
import { filledFiles, ruleCount, textUnder, type PostureBody } from "./document";

export interface PostureEditorProps {
  postureId: number | null;
  onSaved: (id: number) => void;
}

interface PostureDraft {
  wargame: string;
  name: string;
  suricata_rules: string;
  waf_files: Record<string, string>;
}

function blankPosture(wargame: string): PostureDraft {
  return { wargame, name: "", suricata_rules: "", waf_files: {} };
}

function bodyOf(draft: PostureDraft): PostureBody {
  return { wargame: draft.wargame, name: draft.name, suricata_rules: draft.suricata_rules, waf_files: filledFiles(draft.waf_files) };
}

export function PostureEditor({ postureId, onSaved }: PostureEditorProps) {
  const stored = useResource("/api/staff/postures/{posture_id}/", postureId ? { params: { posture_id: postureId } } : null);
  const { wargames } = useWargames();
  const [draft, setDraft] = useState<PostureDraft | null>(null);
  const [errors, setErrors] = useState<ShownError[]>([]);
  const [saved, setSaved] = useState(false);
  const [chosenFile, setFile] = useState("");
  const create = useAction("post", "/api/staff/postures/");
  const update = useAction("put", "/api/staff/postures/{posture_id}/");
  const saveError = postureId ? update.error : create.error;

  useEffect(() => {
    if (stored.data) setDraft({ wargame: stored.data.wargame, name: stored.data.name, suricata_rules: stored.data.suricata_rules, waf_files: { ...stored.data.waf_files } });
  }, [stored.data]);
  useEffect(() => {
    if (postureId === null && draft === null && wargames.length) setDraft(blankPosture(wargames[0]?.id ?? ""));
  }, [postureId, draft, wargames]);
  useEffect(() => {
    setErrors(saveError?.errors ?? []);
  }, [saveError]);

  if (postureId !== null && stored.error) return <ErrorNotice error={stored.error} />;
  if (!draft) return <Loading>{t("common.loading")}</Loading>;

  const change = (patch: Partial<PostureDraft>) => {
    setDraft({ ...draft, ...patch });
    setSaved(false);
  };
  const editable = wargames.find((wargame) => wargame.id === draft.wargame)?.waf_files ?? [];
  const file = chosenFile || editable[0] || "";
  const fileOptions: Option[] = editable.map((path) => ({ value: path, label: path.split("/").pop() ?? path }));
  const fileError = textUnder(errors, `waf_files.${file}`);

  const runSave = async () => {
    const body = bodyOf(draft);
    const said = postureId ? await update.run({ params: { posture_id: postureId }, body }) : await create.run({ body });
    if (!said) return;
    setErrors([]);
    setSaved(true);
    if (postureId) stored.setData(said);
    onSaved(said.id);
  };

  const wargameOptions: Option[] = wargames.map((wargame) => ({ value: wargame.id, label: wargameLabel(wargames, wargame.id) }));
  const generalErrors = errors.filter((error) => !error.path);

  return (
    <EditorCard>
      <EditorHead eyebrow={wargameLabel(wargames, draft.wargame)} title={draft.name || t("staff.posture.new_title")}
        actions={<Button tone="primary" busy={create.busy || update.busy} onClick={() => void runSave()}>{t("staff.save")}</Button>} />
      {generalErrors.length > 0 && <EditorStrip tone="danger" title={errorText({ errors: generalErrors })} />}
      {saved && <EditorStrip tone="ok" title={t("staff.saved")} />}

      <EditorSection ruled>
        <FormGrid>
          <Field label={t("staff.posture.name")} error={textUnder(errors, "name")}>
            <Input value={draft.name} bad={Boolean(textUnder(errors, "name"))} onValue={(name) => change({ name })} />
          </Field>
          {postureId === null && (
            <Field label={t("col.wargame")} error={textUnder(errors, "wargame")}>
              <Select value={draft.wargame} options={wargameOptions} onValue={(wargame) => change({ wargame })} />
            </Field>
          )}
        </FormGrid>
      </EditorSection>

      <EditorBand title={t("pane.ids_rules")}>
        <Badge>{t("staff.engine.suricata")}</Badge>
        <Text tone="muted" small>{t("staff.posture.rule_count", { count: ruleCount(draft.suricata_rules) })}</Text>
      </EditorBand>
      <EditorSection ruled>
        <CodeEditor minLines={16} value={draft.suricata_rules} label={t("pane.ids_rules")} bad={Boolean(textUnder(errors, "suricata_rules"))}
          onValue={(suricata_rules) => change({ suricata_rules })} />
        {textUnder(errors, "suricata_rules") && <Text tone="danger" small>{textUnder(errors, "suricata_rules")}</Text>}
      </EditorSection>

      <EditorBand title={t("pane.waf")}>
        <Badge>{t("staff.engine.crs")}</Badge>
      </EditorBand>
      <EditorSection>
        {textUnder(errors, "waf_files") && !fileError && <Text tone="danger" small>{textUnder(errors, "waf_files")}</Text>}
        <Field label={t("staff.posture.waf_file")}>
          <Select mono value={file} options={fileOptions} onValue={setFile} />
        </Field>
        <Text tone="muted" small mono>{file}</Text>
        <CodeEditor minLines={12} value={draft.waf_files[file] ?? ""} label={file} bad={Boolean(fileError)}
          onValue={(text) => change({ waf_files: { ...draft.waf_files, [file]: text } })} />
        {fileError && <Text tone="danger" small>{fileError}</Text>}
        <Text tone="muted" small>{t("staff.posture.waf_note")}</Text>
      </EditorSection>
    </EditorCard>
  );
}

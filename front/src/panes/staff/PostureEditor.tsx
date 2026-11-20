import { useEffect, useState } from "preact/hooks";
import { useAction, useResource } from "../../api/hooks";
import { errorText, type ShownError, t } from "../../strings";
import { Badge, Button, Card, CardHead, Checkbox, ErrorNotice, Field, FormGrid, Input, Loading, Select, Table, Text, type Column, type Option, EditorBand, EditorCard, EditorGroup, EditorHead, EditorSection, EditorStrip, CodeEditor } from "../../ui";
import { useWargames, wargameLabel } from "./catalog";
import { PARANOIA_LEVELS, ruleCount, textUnder, tuningOf, type Exclusion, type PostureBody, type WafTuning } from "./document";

export interface PostureEditorProps {
  postureId: number | null;
  onSaved: (id: number) => void;
}

interface PostureDraft {
  wargame: string;
  name: string;
  suricata_rules: string;
  tuning: WafTuning;
}

const PARANOIA_OPTIONS: Option[] = PARANOIA_LEVELS.map((level) => ({ value: String(level), label: String(level) }));

function blankPosture(wargame: string): PostureDraft {
  return { wargame, name: "", suricata_rules: "", tuning: { paranoia: 1, exclusions: [], thresholds: {}, detection_only: false } };
}

function bodyOf(draft: PostureDraft): PostureBody {
  return { wargame: draft.wargame, name: draft.name, suricata_rules: draft.suricata_rules, crs_tuning: draft.tuning as unknown as Record<string, unknown> };
}

function exclusionKey(exclusion: Exclusion): string {
  return exclusion.rule_id !== undefined ? String(exclusion.rule_id) : exclusion.tag ?? "";
}

function withKey(exclusion: Exclusion, text: string): Exclusion {
  const { rule_id: _rule, tag: _tag, ...rest } = exclusion;
  const trimmed = text.trim();
  if (/^\d+$/.test(trimmed)) return { ...rest, rule_id: Number(trimmed) };
  return { ...rest, tag: text };
}

function whole(text: string): number | undefined {
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) ? undefined : value;
}

export function PostureEditor({ postureId, onSaved }: PostureEditorProps) {
  const stored = useResource("/api/staff/postures/{posture_id}/", postureId ? { params: { posture_id: postureId } } : null);
  const { wargames } = useWargames();
  const [draft, setDraft] = useState<PostureDraft | null>(null);
  const [errors, setErrors] = useState<ShownError[]>([]);
  const [saved, setSaved] = useState(false);
  const create = useAction("post", "/api/staff/postures/");
  const update = useAction("put", "/api/staff/postures/{posture_id}/");
  const saveError = postureId ? update.error : create.error;

  useEffect(() => {
    if (stored.data) setDraft({ wargame: stored.data.wargame, name: stored.data.name, suricata_rules: stored.data.suricata_rules, tuning: tuningOf(stored.data) });
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
  const tune = (patch: Partial<WafTuning>) => change({ tuning: { ...draft.tuning, ...patch } });
  const exclusions = draft.tuning.exclusions ?? [];
  const setExclusion = (index: number, exclusion: Exclusion) => tune({ exclusions: exclusions.map((was, which) => (which === index ? exclusion : was)) });
  const thresholds = draft.tuning.thresholds ?? {};

  const runSave = async () => {
    const body = bodyOf(draft);
    const said = postureId ? await update.run({ params: { posture_id: postureId }, body }) : await create.run({ body });
    if (!said) return;
    setErrors([]);
    setSaved(true);
    if (postureId) stored.setData(said);
    onSaved(said.id);
  };

  const columns: Column<Exclusion>[] = [
    { key: "rule", label: t("waf.exclusion.rule_or_tag"), cell: (exclusion, index) => (
      <Input mono value={exclusionKey(exclusion)} aria-label={t("waf.exclusion.rule_or_tag")} bad={Boolean(textUnder(errors, `crs_tuning.exclusions[${index}]`))}
        onValue={(text) => setExclusion(index, withKey(exclusion, text))} />
    ) },
    { key: "target", label: t("waf.exclusion.target"), cell: (exclusion, index) => (
      <Input mono value={exclusion.target ?? ""} aria-label={t("waf.exclusion.target")} onValue={(target) => setExclusion(index, { ...exclusion, target })} />
    ) },
    { key: "path", label: t("waf.exclusion.path"), cell: (exclusion, index) => (
      <Input mono value={exclusion.path ?? ""} aria-label={t("waf.exclusion.path")} onValue={(path) => setExclusion(index, { ...exclusion, path })} />
    ) },
    { key: "remove", label: "", kind: "end", cell: (_exclusion, index) => (
      <Button small onClick={() => tune({ exclusions: exclusions.filter((_, which) => which !== index) })}>{t("staff.delete")}</Button>
    ) },
  ];
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
        {textUnder(errors, "crs_tuning") && <Text tone="danger" small>{textUnder(errors, "crs_tuning")}</Text>}
        <FormGrid>
          <Field label={t("waf.paranoia")}>
            <Select mono value={String(draft.tuning.paranoia)} options={PARANOIA_OPTIONS} onValue={(level) => tune({ paranoia: Number(level) })} />
          </Field>
          <EditorGroup label={t("waf.detection_only")}>
            <Checkbox checked={draft.tuning.detection_only ?? false} onChecked={(detection_only) => tune({ detection_only })} label={t("waf.detection_only.on")} />
          </EditorGroup>
          <Field label={t("waf.inbound")}>
            <Input mono inputMode="numeric" value={thresholds.inbound ?? ""} onValue={(text) => tune({ thresholds: { ...thresholds, inbound: whole(text) } })} />
          </Field>
          <Field label={t("waf.outbound")}>
            <Input mono inputMode="numeric" value={thresholds.outbound ?? ""} onValue={(text) => tune({ thresholds: { ...thresholds, outbound: whole(text) } })} />
          </Field>
        </FormGrid>
        <Card>
          <CardHead title={t("waf.exclusions")} meta={<Badge>{t("common.count", { count: exclusions.length })}</Badge>}
            actions={<Button small onClick={() => tune({ exclusions: [...exclusions, { tag: "", target: "", path: "/" }] })}>{t("waf.exclusion.add")}</Button>} />
          <Table variant="grid" columns={columns} rows={exclusions} rowKey={(_, index) => index} empty={t("waf.exclusions.none")} />
        </Card>
      </EditorSection>
    </EditorCard>
  );
}

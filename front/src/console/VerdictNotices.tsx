import { useEffect, useRef, useState } from "preact/hooks";
import { useEvents } from "../api/hooks";
import type { RoundEvent } from "../api/follow";
import { t, tFor } from "../strings";
import { Button, Notice, Stack, type NoticeTone } from "../ui";

export const JUDGED = "case.judged";
export const VERDICT_NOTICES_SHOWN = 3;
export const VERDICT_NOTICE_MS = 8_000;
const NOTICED_VERDICTS = new Set(["tp", "fn", "fp"]);

const VERDICT_NOTICE_TONE: Record<string, NoticeTone> = { tp: "ok", tn: "plain", fn: "danger", fp: "warn" };

export interface JudgedCase {
  id: number;
  action: string;
  caseName: string;
  verdict: string;
  alerts: number;
  corroborated: boolean | null;
}

export function judgedCase(event: RoundEvent): JudgedCase {
  const body = event.body as Record<string, unknown>;
  return {
    id: event.id,
    action: String(body.action ?? ""),
    caseName: typeof body.title === "string" && body.title ? body.title : String(body.case ?? ""),
    verdict: String(body.verdict ?? ""),
    alerts: Number(body.alerts ?? 0),
    corroborated: typeof body.corroborated === "boolean" ? body.corroborated : null,
  };
}

function detailOf(judged: JudgedCase): string {
  const alerts = t("verdict_notice.alerts", { count: judged.alerts });
  if (judged.verdict !== "tp" || judged.corroborated === null) return alerts;
  return `${alerts} · ${t(judged.corroborated ? "verdict_notice.corroborated" : "verdict_notice.not_corroborated")}`;
}

function VerdictNotice({ judged, onClose }: { judged: JudgedCase; onClose: () => void }) {
  const closing = useRef(onClose);
  closing.current = onClose;
  useEffect(() => {
    const timer = setTimeout(() => closing.current(), VERDICT_NOTICE_MS);
    return () => clearTimeout(timer);
  }, []);
  return (
    <Notice
      tone={VERDICT_NOTICE_TONE[judged.verdict] ?? "plain"}
      title={t("verdict_notice.line", { verdict: tFor("verdict", judged.verdict), case: judged.caseName })}
      detail={detailOf(judged)}
      action={<Button small onClick={onClose}>{t("verdict_notice.close")}</Button>}
    />
  );
}

export function VerdictNotices({ round }: { round: number }) {
  const [shown, setShown] = useState<JudgedCase[]>([]);
  useEvents(round, [JUDGED], (events, backlog) => {
    if (backlog) return;
    const noticed = events.map(judgedCase).filter((judged) => NOTICED_VERDICTS.has(judged.verdict));
    if (noticed.length) setShown((was) => [...noticed.reverse(), ...was].slice(0, VERDICT_NOTICES_SHOWN));
  });
  const close = (id: number) => setShown((was) => was.filter((one) => one.id !== id));
  if (!shown.length) return null;
  return (
    <div class="verdict-notices" aria-live="polite" aria-label={t("verdict_notice.title")}>
      <Stack gap="sm">
        {shown.map((judged) => <VerdictNotice key={judged.id} judged={judged} onClose={() => close(judged.id)} />)}
      </Stack>
    </div>
  );
}

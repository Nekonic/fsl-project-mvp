import { useEffect } from "preact/hooks";
import { ErrorNotice, Loading, PickList } from "../../ui";
import { grouped, usePostures, useWargames, wargameLabel } from "./catalog";
import { t } from "../../strings";

export interface PostureListProps {
  current: number | null;
  version: number;
  hrefOf: (id: number) => string;
}

export function PostureList({ current, version, hrefOf }: PostureListProps) {
  const postures = usePostures();
  const { wargames } = useWargames();
  const { reload } = postures;
  useEffect(() => {
    if (version) reload();
  }, [version, reload]);
  if (postures.loading && !postures.data) return <Loading>{t("common.loading")}</Loading>;
  if (postures.error) return <ErrorNotice error={postures.error} />;
  const seen = postures.data ?? [];
  const groups = grouped(seen, (posture) => posture.wargame, wargames).map((group) => ({
    title: wargameLabel(wargames, group.wargame),
    items: group.items.map((posture) => ({
      id: posture.id,
      title: posture.name,
      sub: [t("staff.posture.line", { count: Object.keys(posture.waf_files).length })],
      href: hrefOf(posture.id),
      current: posture.id === current,
    })),
  }));
  return <PickList title={t("staff.postures.list")} count={t("common.count", { count: seen.length })} groups={groups} empty={t("staff.postures.empty")} />;
}

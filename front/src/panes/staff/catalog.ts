import { useResource } from "../../api/hooks";
import type { Schemas } from "../../api/client";
import { wargameName } from "../../pages/wargameText";

export type Wargame = Schemas["Wargame"];

export function useWargames() {
  const found = useResource("/api/staff/wargames/", {});
  return { wargames: found.data ?? [], error: found.error, loading: found.loading && !found.data };
}

export function usePostures() {
  return useResource("/api/staff/postures/", {});
}

export function useStaffProblems() {
  return useResource("/api/staff/problems/", {});
}

export function wargameLabel(wargames: Wargame[], id: string): string {
  const found = wargames.find((wargame) => wargame.id === id);
  return found ? `${wargameName(found.id)} · ${found.id}` : id;
}

export function grouped<Item>(items: Item[], wargameOf: (item: Item) => string, wargames: Wargame[]): Array<{ wargame: string; items: Item[] }> {
  const order = wargames.map((wargame) => wargame.id);
  const ids = [...new Set(items.map(wargameOf))].sort((one, two) => {
    const first = order.indexOf(one);
    const second = order.indexOf(two);
    return (first < 0 ? order.length : first) - (second < 0 ? order.length : second) || one.localeCompare(two);
  });
  return ids.map((wargame) => ({ wargame, items: items.filter((item) => wargameOf(item) === wargame) }));
}

export function objectiveNamesOf(wargame: Wargame | undefined): Record<string, string> {
  const listed = (wargame as { objectives?: Array<{ key: string; name: string }> } | undefined)?.objectives ?? [];
  return Object.fromEntries(listed.map((objective) => [objective.key, objective.name]));
}

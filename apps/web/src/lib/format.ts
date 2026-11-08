import type { Item, ItemStatus } from "../api/types";

export function formatQty(value: string | number | null | undefined, unit = ""): string {
  if (value === null || value === undefined || value === "") return "–";
  const n = Number(value);
  const text = Number.isInteger(n)
    ? String(n)
    : n.toLocaleString("cs-CZ", { maximumFractionDigits: 3 });
  return unit ? `${text} ${unit}` : text;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("cs-CZ");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "–";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString("cs-CZ", { dateStyle: "short", timeStyle: "short" });
}

export function formatMoney(value: string | number | null | undefined, currency = "CZK"): string {
  if (value === null || value === undefined || value === "") return "–";
  return Number(value).toLocaleString("cs-CZ", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toLocaleString("cs-CZ", { maximumFractionDigits: 0 })} kB`;
  return `${(bytes / 1024 / 1024).toLocaleString("cs-CZ", { maximumFractionDigits: 1 })} MB`;
}

export const STATUS_TONE: Record<ItemStatus, "slate" | "green" | "amber" | "red" | "blue"> = {
  stored: "green",
  in_use: "blue",
  lent: "amber",
  repair: "amber",
  discarded: "slate",
  sold: "slate",
  lost: "red",
};

/** Hlavní (první) umístění věci, případně „+N dalších“. */
export function placementSummary(item: Item): string {
  if (item.placements.length === 0) return "";
  const first = item.placements[0].location_path ?? "?";
  return item.placements.length > 1 ? `${first} (+${item.placements.length - 1})` : first;
}

/** Ze seznamu s parent_id složí strom (zachová pořadí vstupu). */
export interface TreeNode<T> {
  node: T;
  children: TreeNode<T>[];
}

export function buildTree<T extends { id: string; parent_id: string | null }>(
  list: T[],
): TreeNode<T>[] {
  const byId = new Map<string, TreeNode<T>>();
  list.forEach((n) => byId.set(n.id, { node: n, children: [] }));
  const roots: TreeNode<T>[] = [];
  for (const n of list) {
    const entry = byId.get(n.id)!;
    const parent = n.parent_id ? byId.get(n.parent_id) : undefined;
    if (parent) parent.children.push(entry);
    else roots.push(entry);
  }
  return roots;
}

/** ID uzlu a všech jeho potomků (nezávisle na pořadí v seznamu). */
export function subtreeIds<T extends { id: string; parent_id: string | null }>(
  list: T[],
  rootId: string,
): Set<string> {
  const childrenOf = new Map<string, string[]>();
  for (const n of list) {
    if (!n.parent_id) continue;
    const arr = childrenOf.get(n.parent_id) ?? [];
    arr.push(n.id);
    childrenOf.set(n.parent_id, arr);
  }
  const out = new Set<string>([rootId]);
  const stack = [rootId];
  while (stack.length) {
    for (const c of childrenOf.get(stack.pop()!) ?? []) {
      if (!out.has(c)) {
        out.add(c);
        stack.push(c);
      }
    }
  }
  return out;
}

/** Zploštěný strom s hloubkou – pro výběry (select) s odsazením. */
export function flattenTree<T extends { id: string; parent_id: string | null }>(
  list: T[],
): { node: T; depth: number }[] {
  const out: { node: T; depth: number }[] = [];
  const walk = (nodes: TreeNode<T>[], depth: number) => {
    for (const n of nodes) {
      out.push({ node: n.node, depth });
      walk(n.children, depth + 1);
    }
  };
  walk(buildTree(list), 0);
  return out;
}

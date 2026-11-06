import { useQuery, useQueryClient } from "@tanstack/react-query";

import { get, patch, post } from "../../api/client";
import { useApiMutation } from "../../api/hooks";

export type LineResult = "unchecked" | "ok" | "missing" | "extra" | "moved";

export interface InventoryCounts {
  total: number;
  unchecked: number;
  ok: number;
  missing: number;
  extra: number;
  moved: number;
  changes: number;
}

export interface InventorySession {
  id: string;
  location_id: string | null;
  location_name: string | null;
  name: string;
  status: "open" | "closed" | "cancelled";
  started_at: string;
  closed_at: string | null;
  applied_at: string | null;
  counts: InventoryCounts;
}

export interface InventoryLine {
  item_id: string;
  item_name: string;
  item_label_code: string;
  unit: string;
  location_id: string;
  location_name: string | null;
  location_path: string | null;
  expected_qty: string | null;
  counted_qty: string | null;
  result: LineResult;
  counted_at: string | null;
  diff: string | null;
}

export interface InventoryDetail extends InventorySession {
  lines: InventoryLine[];
}

export interface InventoryChange {
  item_id: string;
  item_name: string;
  location_id: string;
  from_qty: string;
  to_qty: string;
}

export interface InventoryCloseResult {
  session: InventorySession;
  applied: boolean;
  changes: InventoryChange[];
}

export const useInventorySessions = () =>
  useQuery({
    queryKey: ["inventory", "list"],
    queryFn: () => get<InventorySession[]>("/inventory/sessions"),
  });

export const useInventorySession = (id: string | undefined) =>
  useQuery({
    queryKey: ["inventory", "session", id],
    queryFn: () => get<InventoryDetail>(`/inventory/sessions/${id}`),
    enabled: !!id,
  });

export const inventoryApi = {
  start: (body: { location_id: string | null; name?: string }) =>
    post<InventoryDetail>("/inventory/sessions", body),
  count: (sid: string, itemId: string, locationId: string, counted: number | null) =>
    patch<InventoryDetail>(`/inventory/sessions/${sid}/lines/${itemId}/${locationId}`, {
      counted_qty: counted,
    }),
  close: (sid: string, apply: boolean) =>
    post<InventoryCloseResult>(`/inventory/sessions/${sid}/close`, { apply }),
  cancel: (sid: string) => post<InventorySession>(`/inventory/sessions/${sid}/cancel`),
};

/** Mutace, která po úspěchu uloží vrácený detail inventury přímo do cache (bez dalšího dotazu). */
export function useCountLine(sessionId: string) {
  const qc = useQueryClient();
  return useApiMutation(
    (v: { itemId: string; locationId: string; counted: number | null }) =>
      inventoryApi.count(sessionId, v.itemId, v.locationId, v.counted),
    {
      invalidate: false,
      onSuccess: (detail) => {
        qc.setQueryData(["inventory", "session", sessionId], detail);
        void qc.invalidateQueries({ queryKey: ["inventory", "list"] });
      },
    },
  );
}

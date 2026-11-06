import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

const DATA_KEYS = ["items", "item", "locations", "categories", "tags", "stats", "search"];

/** Odebírá proud změn (SSE) a obnovuje data, když něco změní jiný uživatel nebo zařízení. */
export function useLiveUpdates() {
  const qc = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource("/api/v1/events", { withCredentials: true });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = () => {
      // sloučí dávku událostí do jednoho obnovení
      clearTimeout(timer);
      timer = setTimeout(() => {
        for (const key of DATA_KEYS) void qc.invalidateQueries({ queryKey: [key] });
      }, 250);
    };
    const types = [
      "item.created",
      "item.updated",
      "item.deleted",
      "item.restored",
      "item.purged",
      "item.placed",
      "item.moved",
      "item.adjusted",
      "item.removed",
      "location.created",
      "location.updated",
      "location.moved",
      "location.archived",
      "location.unarchived",
      "location.deleted",
      "category.created",
      "category.updated",
      "category.merged",
      "category.deleted",
      "tag.updated",
      "tag.deleted",
    ];
    types.forEach((t) => es.addEventListener(t, refresh));
    return () => {
      clearTimeout(timer);
      es.close();
    };
  }, [qc]);
}

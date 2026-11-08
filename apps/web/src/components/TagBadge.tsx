import { useMemo } from "react";

import { useTags } from "../api/hooks";
import { Badge } from "./ui";

/** Barva tagu je vždy `#rrggbb`; průhledné pozadí a sytý text zůstanou čitelné ve světlém i tmavém režimu. */
export function tagStyle(color: string): React.CSSProperties {
  return { backgroundColor: `${color}26`, color, borderColor: `${color}66` };
}

/** Mapa název tagu (malými písmeny) → barva z už načteného seznamu tagů. */
export function useTagColors(): (name: string) => string | null {
  const { data } = useTags();
  const map = useMemo(
    () => new Map((data ?? []).filter((t) => t.color).map((t) => [t.name.toLowerCase(), t.color!])),
    [data],
  );
  return (name) => map.get(name.toLowerCase()) ?? null;
}

/** Štítek (tag) věci; má-li tag barvu, použije ji. */
export function TagBadge({ name, color }: { name: string; color?: string | null }) {
  const lookup = useTagColors();
  const c = color === undefined ? lookup(name) : color;
  if (!c) return <Badge>{name}</Badge>;
  return (
    <span
      style={tagStyle(c)}
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium"
    >
      {name}
    </span>
  );
}

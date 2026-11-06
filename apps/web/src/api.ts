export interface Health {
  status: string;
  version: string;
}

export async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/v1/health");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as Health;
}

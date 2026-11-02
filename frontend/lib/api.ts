const DEFAULT_TIMEOUT_MS = 3000;

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type HealthResult = { ok: true } | { ok: false; error: string };

export async function getHealth(): Promise<HealthResult> {
  try {
    const res = await fetch(`${API_URL}/health`, {
      signal: AbortSignal.timeout(DEFAULT_TIMEOUT_MS),
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const body: unknown = await res.json();
    const healthy =
      typeof body === "object" && body !== null && "status" in body && body.status === "ok";
    return healthy ? { ok: true } : { ok: false, error: "Unexpected response" };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "Request failed" };
  }
}

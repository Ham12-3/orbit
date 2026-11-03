const TIMEOUT_MS = 15_000;
// Reading a workspace file may first wake the bot's paused computer.
const SANDBOX_TIMEOUT_MS = 90_000;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Browser URL for a backend path: the Next.js route at /api/backend forwards it. */
export function backendUrl(path: string): string {
  return `/api/backend${path.replace(/^\/api/, "")}`;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      return typeof detail === "string" ? detail : "The request was not valid.";
    }
  } catch {
    // not JSON
  }
  return response.statusText || `Request failed (${response.status})`;
}

/** Encode each segment of a file path for use in a URL, keeping the slashes. */
export function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

async function request(
  path: string,
  init: { method?: string; body?: unknown; timeoutMs?: number },
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(backendUrl(path), {
      method: init.method ?? "GET",
      headers: init.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: AbortSignal.timeout(init.timeoutMs ?? TIMEOUT_MS),
    });
  } catch {
    throw new ApiError(0, "Can't reach Orbit. Is make dev running?");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return response;
}

/** Call the backend. `path` is the backend path, e.g. `/api/bots`. */
export async function api<T>(
  path: string,
  init: {
    method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    body?: unknown;
    slow?: boolean; // the call may wake the bot's computer
  } = {},
): Promise<T> {
  const response = await request(path, {
    ...init,
    timeoutMs: init.slow ? SANDBOX_TIMEOUT_MS : TIMEOUT_MS,
  });
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/** Raw bytes from the backend (workspace files). */
export async function apiBytes(path: string): Promise<ArrayBuffer> {
  const response = await request(path, { timeoutMs: SANDBOX_TIMEOUT_MS });
  return response.arrayBuffer();
}

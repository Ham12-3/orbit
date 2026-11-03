import type { NextRequest } from "next/server";

const API_URL = process.env.ORBIT_API_URL ?? "http://localhost:8000";
const API_TOKEN = process.env.ORBIT_API_TOKEN;

const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "last-event-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "cache-control", "x-accel-buffering"];

/**
 * The browser only talks to this Next.js server. It forwards /api/backend/<path> to the
 * backend's /api/<path> and adds LOCAL_API_TOKEN, so the token never reaches the browser and
 * the backend stays closed even though the dev tunnel exposes it. Responses (including the
 * live SSE run stream) are piped through unbuffered.
 */
async function forward(request: NextRequest, path: string[]): Promise<Response> {
  if (!API_TOKEN) {
    return Response.json(
      { detail: "ORBIT_API_TOKEN is not set in frontend/.env.local (run make install)." },
      { status: 500 },
    );
  }
  // Encode each segment so a path can never escape /api/.
  const url = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, API_URL);
  url.search = request.nextUrl.search;

  const headers = new Headers({ Authorization: `Bearer ${API_TOKEN}` });
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : await request.arrayBuffer(),
      signal: request.signal, // the browser leaving ends the upstream request (and stream)
      cache: "no-store",
    });
  } catch {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    return Response.json(
      { detail: "Can't reach the Orbit API. Is the backend running?" },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: NextRequest, context: RouteContext<"/api/backend/[...path]">) {
  return forward(request, (await context.params).path);
}

export async function POST(request: NextRequest, context: RouteContext<"/api/backend/[...path]">) {
  return forward(request, (await context.params).path);
}

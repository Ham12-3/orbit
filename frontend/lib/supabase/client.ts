import { createBrowserClient } from "@supabase/ssr";

// createBrowserClient is a singleton under the hood, so calling this often is cheap.
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  );
}

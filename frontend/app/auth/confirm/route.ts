import { type EmailOtpType } from "@supabase/supabase-js";
import { type NextRequest, NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

// The magic-link email points here with a token_hash (see CLAUDE.md for the template).
// Verifying it server-side sets the session cookies (PKCE-safe, unlike the default link).
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const next = searchParams.get("next");

  const redirectTo = request.nextUrl.clone();
  redirectTo.search = "";
  // Only same-site paths, never "//evil.example".
  redirectTo.pathname = next && next.startsWith("/") && !next.startsWith("//") ? next : "/bots";

  if (tokenHash && type) {
    const supabase = await createClient();
    const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
    if (!error) {
      return NextResponse.redirect(redirectTo);
    }
  }

  redirectTo.pathname = "/login";
  redirectTo.searchParams.set("error", "That sign-in link is invalid or has expired.");
  return NextResponse.redirect(redirectTo);
}

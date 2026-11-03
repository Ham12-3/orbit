import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2 text-center">
          <div className="text-3xl">🪐</div>
          <h1 className="font-heading text-2xl font-semibold tracking-tight">Sign in to Orbit</h1>
          <p className="text-sm text-muted-foreground">
            We&apos;ll email you a link. No password needed.
          </p>
        </div>
        <Suspense>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}

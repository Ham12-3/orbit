import { Suspense } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_URL, getHealth } from "@/lib/api";

async function ApiStatus() {
  const health = await getHealth();
  return health.ok ? (
    <Badge>API ok</Badge>
  ) : (
    <Badge variant="destructive" title={health.error}>
      API unreachable
    </Badge>
  );
}

export default function Home() {
  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between px-4 py-3 sm:px-6">
        <span className="font-heading text-lg font-semibold tracking-tight">Orbit</span>
        <ThemeToggle />
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-12">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Scaffold is running</CardTitle>
            <CardDescription>Bots, chat and runs arrive in the next phases.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center justify-between gap-4 text-muted-foreground">
            <code className="truncate font-mono text-xs">{API_URL}</code>
            <Suspense fallback={<Badge variant="outline">Checking…</Badge>}>
              <ApiStatus />
            </Suspense>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

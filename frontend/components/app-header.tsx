"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const LATER = [
  { label: "Approvals", phase: 4 },
  { label: "Connections", phase: 4 },
];

function BotsLink({ active }: { active: boolean }) {
  return (
    <Link
      href="/bots"
      className={cn(
        "rounded-md px-2.5 py-1.5 transition-colors hover:bg-muted",
        active ? "font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      Bots
    </Link>
  );
}

function ActiveBotsLink() {
  const pathname = usePathname();
  return <BotsLink active={pathname.startsWith("/bots") || pathname.startsWith("/runs")} />;
}

export function AppHeader() {
  return (
    <header className="sticky top-0 z-20 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6">
        <Link href="/bots" className="flex items-center gap-2 font-heading font-semibold">
          <span aria-hidden>🪐</span> Orbit
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          {/* usePathname suspends on dynamic routes under Cache Components. */}
          <Suspense fallback={<BotsLink active={false} />}>
            <ActiveBotsLink />
          </Suspense>
          {LATER.map((item) => (
            <Tooltip key={item.label}>
              <TooltipTrigger
                render={<span />}
                className="hidden cursor-default rounded-md px-2.5 py-1.5 text-muted-foreground/60 sm:inline"
              >
                {item.label}
              </TooltipTrigger>
              <TooltipContent>Arrives in Phase {item.phase}</TooltipContent>
            </Tooltip>
          ))}
        </nav>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

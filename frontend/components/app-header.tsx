"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useMe } from "@/lib/queries";
import { createClient } from "@/lib/supabase/client";
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
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useMe();

  async function signOut() {
    // "local" signs out this browser only; the default revokes every session.
    await createClient().auth.signOut({ scope: "local" });
    queryClient.clear();
    router.replace("/login");
  }

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
        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label="Account"
              className={buttonVariants({ variant: "ghost", size: "icon" })}
            >
              <UserRound />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
              <DropdownMenuLabel className="truncate font-normal text-muted-foreground">
                {me.data?.email ?? "Signed in"}
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={signOut}>
                <LogOut /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}

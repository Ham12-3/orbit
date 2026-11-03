import { Suspense } from "react";

import { BotView } from "@/components/bots/bot-view";
import { Skeleton } from "@/components/ui/skeleton";

export default function BotPage() {
  // BotView reads the route and search params on the client; under Cache Components that
  // must sit inside <Suspense>.
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-xl" />}>
      <BotView />
    </Suspense>
  );
}

import { Suspense } from "react";

import { RunView } from "@/components/runs/run-view";
import { Skeleton } from "@/components/ui/skeleton";

export default function RunPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-xl" />}>
      <RunView />
    </Suspense>
  );
}

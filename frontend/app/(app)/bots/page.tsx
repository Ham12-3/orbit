import type { Metadata } from "next";

import { BotsGrid } from "@/components/bots/bots-grid";

export const metadata: Metadata = { title: "Bots" };

export default function BotsPage() {
  return <BotsGrid />;
}

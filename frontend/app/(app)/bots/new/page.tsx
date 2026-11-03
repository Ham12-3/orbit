import type { Metadata } from "next";

import { NewBotForm } from "@/components/bots/new-bot-form";

export const metadata: Metadata = { title: "New bot" };

export default function NewBotPage() {
  return <NewBotForm />;
}

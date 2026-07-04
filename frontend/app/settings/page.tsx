import { ComingSoon } from "@/components/layout/coming-soon";
import { Settings } from "lucide-react";

export default function SettingsPage() {
  return (
    <ComingSoon
      title="Settings"
      description="Configuration for LLM provider, notification preferences, and GitHub App connections will live here."
      icon={Settings}
    />
  );
}

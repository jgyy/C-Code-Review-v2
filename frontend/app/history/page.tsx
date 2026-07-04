import { ComingSoon } from "@/components/layout/coming-soon";
import { History } from "lucide-react";

export default function HistoryPage() {
  return (
    <ComingSoon
      title="History"
      description="A searchable archive of past analyses across every repository will live here. For now, see the Jobs page for recent runs."
      icon={History}
    />
  );
}

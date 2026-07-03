import { ComingSoon } from "@/components/layout/coming-soon";
import { BarChart3 } from "lucide-react";

export default function AnalyticsPage() {
  return (
    <ComingSoon
      title="Analytics"
      description="Trends across risk levels, cache efficiency, and analysis volume over time will live here."
      icon={BarChart3}
    />
  );
}

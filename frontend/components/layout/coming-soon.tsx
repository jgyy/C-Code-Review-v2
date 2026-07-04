import type { ComponentType } from "react";
import { Construction } from "lucide-react";

export function ComingSoon({
  title,
  description,
  icon: Icon,
}: {
  title: string;
  description: string;
  icon: ComponentType<{ className?: string }>;
}) {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-foreground">{title}</h1>

      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-card px-6 py-20 text-center">
        <div className="relative mb-4">
          <Icon className="h-10 w-10 text-muted-foreground/40" />
          <Construction className="absolute -bottom-1 -right-2 h-5 w-5 text-yellow-400" />
        </div>
        <p className="text-sm font-medium text-foreground">Coming soon</p>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

import type { DataSource } from "@/lib/types";

export default function DataSourceBadge({ source }: { source: DataSource | null }) {
  if (!source) return null;
  const isLive = source === "live";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        isLive
          ? "bg-emerald-100 text-emerald-800"
          : "bg-amber-100 text-amber-800"
      }`}
      title={
        isLive
          ? "Live data from the backend API"
          : "Backend unreachable — showing mock data matching the contract shape"
      }
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          isLive ? "bg-emerald-500" : "bg-amber-500"
        }`}
      />
      {isLive ? "Live data" : "Mock data"}
    </span>
  );
}

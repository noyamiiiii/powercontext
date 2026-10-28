import { Cpu, Database, LoaderCircle } from "lucide-react";

interface StatusPillProps {
  kind: "embedding" | "seekdb";
  label: string;
  detail?: string;
  loading?: boolean;
}

export function StatusPill({
  kind,
  label,
  detail,
  loading = false,
}: StatusPillProps) {
  const Icon = kind === "embedding" ? Cpu : Database;
  return (
    <div className={`status-pill status-pill--${kind}`}>
      <span className="status-pill__icon" aria-hidden="true">
        {loading ? <LoaderCircle className="spin" size={15} /> : <Icon size={15} />}
      </span>
      <span>
        <strong>{label}</strong>
        {detail ? <small>{detail}</small> : null}
      </span>
    </div>
  );
}

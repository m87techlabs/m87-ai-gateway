export const number = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : value.toLocaleString();

export const compact = (value: number) =>
  Math.abs(value) >= 1000
    ? new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value)
    : String(Math.round(value * 100) / 100);

export const dateTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" }) : "—";

export const time = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export function ago(value: string | null | undefined) {
  if (!value) return "Never";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

export const latency = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
};

export const bytes = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "Unknown";
  if (value >= 1073741824) return `${(value / 1073741824).toFixed(1)} GiB`;
  return `${(value / 1048576).toFixed(2)} MiB`;
};

export const count = (value: number, noun: string) => `${value.toLocaleString()} ${noun}${value === 1 ? "" : "s"}`;

export const percent = (part: number, whole: number) =>
  whole ? `${((part / whole) * 100).toFixed(part / whole < 0.1 ? 1 : 0)}%` : "0%";

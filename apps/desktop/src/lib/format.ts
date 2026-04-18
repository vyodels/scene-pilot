function parseDateCandidate(value: string): Date | null {
  const numeric = value.trim();
  if (/^\d+$/.test(numeric)) {
    const timestamp = Number(numeric);
    if (!Number.isNaN(timestamp)) {
      const millis = timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000;
      const fromTimestamp = new Date(millis);
      if (!Number.isNaN(fromTimestamp.getTime())) {
        return fromTimestamp;
      }
    }
  }

  const direct = new Date(value);
  if (!Number.isNaN(direct.getTime())) {
    return direct;
  }

  const normalized = value
    .trim()
    .replace(" ", "T")
    .replace(/(\.\d{3})\d+/, "$1");

  const fallback = new Date(normalized);
  if (!Number.isNaN(fallback.getTime())) {
    return fallback;
  }

  return null;
}

export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

export function formatCompactDate(iso: string): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatMoney(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

export function clampText(text: string, limit = 120): string {
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit - 1)}...`;
}

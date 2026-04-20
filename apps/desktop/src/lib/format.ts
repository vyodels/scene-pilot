function parseDateCandidate(value: string | number | Date | null | undefined): Date | null {
  if (value == null) {
    return null;
  }

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const raw = String(value).trim();
  if (!raw) {
    return null;
  }

  const numeric = raw;
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

  const direct = new Date(raw);
  if (!Number.isNaN(direct.getTime())) {
    return direct;
  }

  const normalized = raw
    .replace(" ", "T")
    .replace(/(\.\d{3})\d+/, "$1");

  const fallback = new Date(normalized);
  if (!Number.isNaN(fallback.getTime())) {
    return fallback;
  }

  return null;
}

function padDatePart(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

export function formatCompactDate(iso: string | number | Date | null | undefined): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso == null ? "" : String(iso);
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDateTime(iso: string | number | Date | null | undefined): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso == null ? "" : String(iso);
  }

  const year = date.getFullYear();
  const month = padDatePart(date.getMonth() + 1);
  const day = padDatePart(date.getDate());
  const hours = padDatePart(date.getHours());
  const minutes = padDatePart(date.getMinutes());
  const seconds = padDatePart(date.getSeconds());

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
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

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

function formatDateTimeParts(date: Date): {
  year: string;
  month: string;
  day: string;
  hours: string;
  minutes: string;
  seconds: string;
} {
  return {
    year: String(date.getFullYear()),
    month: padDatePart(date.getMonth() + 1),
    day: padDatePart(date.getDate()),
    hours: padDatePart(date.getHours()),
    minutes: padDatePart(date.getMinutes()),
    seconds: padDatePart(date.getSeconds()),
  };
}

function formatFullDateTime(date: Date): string {
  const { year, month, day, hours, minutes, seconds } = formatDateTimeParts(date);
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

export function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

export function formatCompactDate(iso: string | number | Date | null | undefined): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso == null ? "" : String(iso);
  }
  return formatFullDateTime(date);
}

export function formatChineseMessageTime(iso: string | number | Date | null | undefined): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso == null ? "" : String(iso);
  }

  const now = new Date();
  const { year, month, day, hours, minutes } = formatDateTimeParts(date);
  const isSameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  if (isSameDay) {
    return `${hours}:${minutes}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday =
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate();

  if (isYesterday && date.getFullYear() === now.getFullYear()) {
    return `昨天 ${hours}:${minutes}`;
  }

  if (date.getFullYear() === now.getFullYear()) {
    return `${month}-${day} ${hours}:${minutes}`;
  }

  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

export function formatChineseChatTime(iso: string | number | Date | null | undefined): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso == null ? "" : String(iso);
  }

  const { year, month, day, hours, minutes } = formatDateTimeParts(date);
  if (date.getFullYear() === new Date().getFullYear()) {
    return `${month}-${day} ${hours}:${minutes}`;
  }
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

export function formatDateTime(iso: string | number | Date | null | undefined): string {
  const date = parseDateCandidate(iso);
  if (!date) {
    return iso == null ? "" : String(iso);
  }

  return formatFullDateTime(date);
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

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "../../lib/i18n";
import type { CandidateDateFilter } from "./kanbanUtils";

export type CandidateDatePreset = "all" | "manual" | "last7days" | "thisWeek" | "lastMonth" | "lastQuarter" | "lastYear";

export interface CandidateDateRangeState {
  preset: CandidateDatePreset;
  startDate: string;
  endDate: string;
}

function formatDateInput(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(date: Date, days: number): Date {
  const value = new Date(date);
  value.setDate(value.getDate() + days);
  return value;
}

function addMonths(date: Date, months: number): Date {
  const value = new Date(date);
  value.setMonth(value.getMonth() + months);
  return value;
}

function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function formatMonthLabel(date: Date, language: "en" | "zh-CN"): string {
  if (language === "zh-CN") {
    return `${date.getFullYear()}年${date.getMonth() + 1}月`;
  }
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
  });
}

function shiftMonth(date: Date, amount: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + amount, 1);
}

function buildCalendarDays(month: Date): Array<{ value: string; day: number; inMonth: boolean }> {
  const firstDay = startOfMonth(month);
  const weekday = (firstDay.getDay() + 6) % 7;
  const gridStart = addDays(firstDay, -weekday);

  return Array.from({ length: 42 }, (_, index) => {
    const cellDate = addDays(gridStart, index);
    return {
      value: formatDateInput(cellDate),
      day: cellDate.getDate(),
      inMonth: cellDate.getMonth() === month.getMonth(),
    };
  });
}

function isDateInRange(value: string, startDate: string, endDate: string): boolean {
  if (!startDate || !endDate) {
    return false;
  }
  return value >= startDate && value <= endDate;
}

function sortRange(startDate: string, endDate: string): { startDate: string; endDate: string } {
  if (!startDate || !endDate || startDate <= endDate) {
    return { startDate, endDate };
  }
  return { startDate: endDate, endDate: startDate };
}

function resolvePresetRange(preset: CandidateDatePreset): CandidateDateFilter | null {
  const now = new Date();
  const endDate = formatDateInput(now);

  switch (preset) {
    case "last7days":
      return {
        kind: "custom",
        startDate: formatDateInput(addDays(now, -6)),
        endDate,
      };
    case "thisWeek": {
      const start = new Date(now);
      const day = start.getDay() || 7;
      start.setDate(start.getDate() - day + 1);
      return {
        kind: "custom",
        startDate: formatDateInput(start),
        endDate,
      };
    }
    case "lastMonth":
      return {
        kind: "custom",
        startDate: formatDateInput(addMonths(now, -1)),
        endDate,
      };
    case "lastQuarter":
      return {
        kind: "custom",
        startDate: formatDateInput(addMonths(now, -3)),
        endDate,
      };
    case "lastYear":
      return {
        kind: "custom",
        startDate: formatDateInput(addMonths(now, -12)),
        endDate,
      };
    default:
      return null;
  }
}

export function createCandidateDateRangeState(): CandidateDateRangeState {
  return {
    preset: "all",
    startDate: "",
    endDate: "",
  };
}

export function createDefaultManualCandidateDateRange(): CandidateDateRangeState {
  const range = resolvePresetRange("lastMonth");
  return {
    preset: "manual",
    startDate: range?.startDate ?? "",
    endDate: range?.endDate ?? "",
  };
}

export function resolveCandidateDateRangeFilter(value: CandidateDateRangeState): CandidateDateFilter {
  if (value.preset === "all") {
    return { kind: "all", startDate: "", endDate: "" };
  }
  if (value.preset === "manual") {
    return {
      kind: "custom",
      startDate: value.startDate,
      endDate: value.endDate,
    };
  }
  return resolvePresetRange(value.preset) ?? { kind: "all", startDate: "", endDate: "" };
}

function CalendarPanel({
  label,
  month,
  language,
  startDate,
  endDate,
  onShiftMonth,
  onPickDate,
}: {
  label: string;
  month: Date;
  language: "en" | "zh-CN";
  startDate: string;
  endDate: string;
  onShiftMonth(amount: number): void;
  onPickDate(value: string): void;
}): JSX.Element {
  const { copy } = useI18n();
  const days = useMemo(() => buildCalendarDays(month), [month]);
  const weekdayLabels = language === "zh-CN" ? ["一", "二", "三", "四", "五", "六", "日"] : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const today = formatDateInput(new Date());

  return (
    <section className="candidate-date-range__calendar">
      <div className="candidate-date-range__calendar-caption">{label}</div>
      <div className="candidate-date-range__calendar-header">
        <button type="button" className="candidate-date-range__nav" onClick={() => onShiftMonth(-1)} aria-label={copy("Previous month", "上一个月")}>
          ‹
        </button>
        <div className="candidate-date-range__month">{formatMonthLabel(month, language)}</div>
        <button type="button" className="candidate-date-range__nav" onClick={() => onShiftMonth(1)} aria-label={copy("Next month", "下一个月")}>
          ›
        </button>
      </div>
      <div className="candidate-date-range__weekdays">
        {weekdayLabels.map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="candidate-date-range__days">
        {days.map((day) => {
          const selectedStart = day.value === startDate;
          const selectedEnd = day.value === endDate;
          return (
            <button
              key={day.value}
              type="button"
              className="candidate-date-range__day"
              data-outside={!day.inMonth ? "true" : undefined}
              data-in-range={isDateInRange(day.value, startDate, endDate) ? "true" : undefined}
              data-edge={selectedStart || selectedEnd ? "true" : undefined}
              data-today={day.value === today ? "true" : undefined}
              onClick={() => onPickDate(day.value)}
            >
              {day.day}
            </button>
          );
        })}
      </div>
    </section>
  );
}

interface CandidateDateRangeControlProps {
  value: CandidateDateRangeState;
  onChange(nextValue: CandidateDateRangeState): void;
}

export function CandidateDateRangeControl({ value, onChange }: CandidateDateRangeControlProps): JSX.Element {
  const { copy, language } = useI18n();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [leftMonth, setLeftMonth] = useState(() => startOfMonth(addMonths(new Date(), -1)));
  const [rightMonth, setRightMonth] = useState(() => startOfMonth(new Date()));
  const [touchedRangeSides, setTouchedRangeSides] = useState<{ start: boolean; end: boolean }>({
    start: false,
    end: false,
  });

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  const displayedStart = value.startDate || "----/--/--";
  const displayedEnd = value.endDate || "----/--/--";

  const openManualPicker = () => {
    const nextValue =
      value.preset === "manual" && value.startDate && value.endDate
        ? value
        : createDefaultManualCandidateDateRange();
    const { startDate, endDate } = sortRange(nextValue.startDate, nextValue.endDate);
    onChange({
      preset: "manual",
      startDate,
      endDate,
    });
    setLeftMonth(startOfMonth(new Date(`${startDate}T00:00:00`)));
    setRightMonth(startOfMonth(new Date(`${endDate}T00:00:00`)));
    setTouchedRangeSides({ start: false, end: false });
    setOpen(true);
  };

  const applyDate = (side: "start" | "end", pickedDate: string) => {
    const startDate = side === "start" ? pickedDate : value.startDate || pickedDate;
    const endDate = side === "end" ? pickedDate : value.endDate || value.startDate || pickedDate;
    const nextRange = sortRange(startDate, endDate);
    const nextTouched = {
      start: touchedRangeSides.start || side === "start",
      end: touchedRangeSides.end || side === "end",
    };
    onChange({
      preset: "manual",
      startDate: nextRange.startDate,
      endDate: nextRange.endDate,
    });
    setTouchedRangeSides(nextTouched);
    if (nextTouched.start && nextTouched.end) {
      setOpen(false);
    }
  };

  return (
    <div className="candidate-date-range" ref={rootRef}>
      <label className="kanban-filter">
        <span className="kanban-filter__label">{copy("Time", "时间")}</span>
        <select
          value={value.preset}
          onChange={(event) => {
            const nextPreset = event.target.value as CandidateDatePreset;
            if (nextPreset === "manual") {
              openManualPicker();
              return;
            }
            setOpen(false);
            onChange({
              preset: nextPreset,
              startDate: "",
              endDate: "",
            });
          }}
          className="kanban-filter__select"
        >
          <option value="all">{copy("All", "全部")}</option>
          <option value="manual">{copy("Custom", "自定义")}</option>
          <option value="last7days">{copy("Last 7 days", "最近 7 天")}</option>
          <option value="thisWeek">{copy("This week", "最近一周")}</option>
          <option value="lastMonth">{copy("Last month", "最近一个月")}</option>
          <option value="lastQuarter">{copy("Last quarter", "最近三个月")}</option>
          <option value="lastYear">{copy("Last year", "最近一年")}</option>
        </select>
      </label>

      <button type="button" className="candidate-date-range__trigger" onClick={openManualPicker}>
        <span className="candidate-date-range__field">
          <span className="candidate-date-range__field-label">{copy("Start", "开始")}</span>
          <span className="candidate-date-range__field-value">{displayedStart}</span>
        </span>
        <span className="candidate-date-range__separator">→</span>
        <span className="candidate-date-range__field">
          <span className="candidate-date-range__field-label">{copy("End", "结束")}</span>
          <span className="candidate-date-range__field-value">{displayedEnd}</span>
        </span>
      </button>

      {open ? (
        <div className="candidate-date-range__popover">
          <div className="candidate-date-range__calendars">
            <CalendarPanel
              label={copy("Start date", "开始时间")}
              month={leftMonth}
              language={language}
              startDate={value.startDate}
              endDate={value.endDate}
              onShiftMonth={(amount) => setLeftMonth((current) => shiftMonth(current, amount))}
              onPickDate={(pickedDate) => applyDate("start", pickedDate)}
            />
            <CalendarPanel
              label={copy("End date", "结束时间")}
              month={rightMonth}
              language={language}
              startDate={value.startDate}
              endDate={value.endDate}
              onShiftMonth={(amount) => setRightMonth((current) => shiftMonth(current, amount))}
              onPickDate={(pickedDate) => applyDate("end", pickedDate)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

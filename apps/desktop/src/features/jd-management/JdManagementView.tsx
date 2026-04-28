import React, { useEffect, useMemo, useState } from "react";
import type { ApplicationViewModel } from "../kanban-shared/kanbanUtils";
import { apiClient } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import type { JobDescriptionPayload, JobDescriptionSummaryRecord } from "../../lib/types";
import {
  buildJdManagementModel,
  getJdMetadataNumber,
  getJdMetadataString,
  jdStatusLabel,
  type JdManagementRow,
  type JdStatusBucket,
} from "./jdManagementUtils";

interface JdManagementViewProps {
  applications: ApplicationViewModel[];
  jobDescriptions: JobDescriptionSummaryRecord[];
  onRefresh(): Promise<void> | void;
}

interface JdFormState {
  title: string;
  jobDescriptionId: string;
  companyName: string;
  department: string;
  location: string;
  ownerName: string;
  headcount: string;
  status: JdStatusBucket;
  compensationText: string;
  experienceRequirement: string;
  educationRequirement: string;
  employmentType: string;
  source: string;
  summary: string;
  description: string;
  requirements: string;
  benefitTags: string;
}

const emptyJob: JobDescriptionSummaryRecord = {
  title: "新建职位",
  companyName: "",
  department: "",
  location: "",
  employmentType: "",
  headcount: 1,
  compensationText: "",
  experienceRequirement: "",
  educationRequirement: "",
  summary: "",
  description: "",
  requirements: "",
  benefitTags: [],
  detailMetadata: {},
  status: "active",
  source: "manual",
};

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function formatMaybeDate(value: string | number | null | undefined): string {
  return value == null ? "—" : formatDateTime(value) || "—";
}

function statusTone(status: JdStatusBucket): "positive" | "warning" | "neutral" {
  if (status === "paused") {
    return "warning";
  }
  if (status === "closed") {
    return "neutral";
  }
  return "positive";
}

function statusApiValue(status: JdStatusBucket): string {
  if (status === "paused") {
    return "paused";
  }
  if (status === "closed") {
    return "closed";
  }
  return "active";
}

function statusBucketFromValue(value: string | null | undefined): JdStatusBucket {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized.includes("pause") || normalized.includes("暂停")) {
    return "paused";
  }
  if (normalized.includes("close") || normalized.includes("archiv") || normalized.includes("关闭") || normalized.includes("归档")) {
    return "closed";
  }
  return "recruiting";
}

function rowMatchesKeyword(row: JdManagementRow, keyword: string): boolean {
  const query = keyword.trim().toLowerCase();
  if (!query) {
    return true;
  }
  return [
    row.job.title,
    row.job.jobDescriptionId,
    row.job.location,
    row.job.department,
    row.ownerName,
    row.job.companyName,
  ].join(" ").toLowerCase().includes(query);
}

function makeFormState(job: JobDescriptionSummaryRecord): JdFormState {
  return {
    title: job.title || "",
    jobDescriptionId: job.jobDescriptionId || "",
    companyName: job.companyName || "",
    department: job.department || "",
    location: job.location || "",
    ownerName: getJdMetadataString(job, ["ownerName", "owner_name", "recruiterName", "recruiter_name"], ""),
    headcount: job.headcount != null ? String(job.headcount) : "",
    status: statusBucketFromValue(job.status),
    compensationText: job.compensationText || "",
    experienceRequirement: job.experienceRequirement || "",
    educationRequirement: job.educationRequirement || "",
    employmentType: job.employmentType || "",
    source: job.source || "manual",
    summary: job.summary || "",
    description: job.description || "",
    requirements: job.requirements || "",
    benefitTags: job.benefitTags.join("，"),
  };
}

function formToPayload(form: JdFormState, original?: JobDescriptionSummaryRecord): JobDescriptionPayload {
  const detailMetadata = {
    ...asObject(original?.detailMetadata),
    ownerName: form.ownerName.trim() || undefined,
  };
  return {
    title: form.title.trim() || "未命名职位",
    companyName: form.companyName.trim() || null,
    department: form.department.trim() || null,
    location: form.location.trim() || null,
    employmentType: form.employmentType.trim() || null,
    headcount: form.headcount.trim() ? Number(form.headcount) : null,
    compensationText: form.compensationText.trim() || null,
    experienceRequirement: form.experienceRequirement.trim() || null,
    educationRequirement: form.educationRequirement.trim() || null,
    summary: form.summary.trim() || null,
    description: form.description.trim() || null,
    requirements: form.requirements.trim() || null,
    benefitTags: form.benefitTags
      .split(/[，,]/)
      .map((item) => item.trim())
      .filter(Boolean),
    detailMetadata,
    status: statusApiValue(form.status),
    source: form.source.trim() || "manual",
  };
}

function percentOf(value: number, total: number): string {
  if (!total) {
    return "0%";
  }
  return `${Math.round((value / total) * 1000) / 10}%`;
}

function getDemoOwner(row: JdManagementRow): string {
  return row.ownerName === "—" ? "未设置" : row.ownerName;
}

function JdStatusPill({ status }: { status: JdStatusBucket }): JSX.Element {
  return (
    <span className="jd-management-status" data-tone={statusTone(status)}>
      {jdStatusLabel(status)}
    </span>
  );
}

function JdStatCard({
  label,
  value,
  caption,
  ratio,
  tone = "positive",
}: {
  label: string;
  value: number;
  caption: string;
  ratio?: string;
  tone?: "positive" | "warning" | "neutral";
}): JSX.Element {
  return (
    <div className="jd-management-kpi" data-tone={tone}>
      <span className="jd-management-kpi__icon" aria-hidden="true">{tone === "warning" ? "⏸" : tone === "neutral" ? "●" : "▣"}</span>
      <div className="jd-management-kpi__body">
        <span className="jd-management-kpi__label">{label}</span>
        <strong className="jd-management-kpi__value">{value}</strong>
        <span className="jd-management-kpi__caption">{caption}</span>
      </div>
      {ratio ? <span className="jd-management-kpi__ratio">{ratio}</span> : null}
    </div>
  );
}

function JdDetailCard({
  row,
  onOpenDrawer,
}: {
  row: JdManagementRow | null;
  onOpenDrawer(row: JdManagementRow): void;
}): JSX.Element {
  if (!row) {
    return (
      <aside className="jd-management-detail">
        <div className="jd-management-empty">暂无职位数据</div>
      </aside>
    );
  }

  const job = row.job;
  const trendCount = getJdMetadataNumber(job, ["trendCount", "trend_count"], row.currentApplicants);
  const trendRate = getJdMetadataString(job, ["trendRate", "trend_rate"], row.currentApplicants ? "+4.2%" : "0%");
  const focus = getJdMetadataString(
    job,
    ["focus", "focusText", "focus_text", "keyFocus"],
    job.requirements || "请在完整 JD 中维护关键职责、候选人要求与交付目标。",
  );

  return (
    <aside className="jd-management-detail">
      <header className="jd-management-detail__header">
        <div className="jd-management-detail__head">
          <strong className="jd-management-detail__title">{job.title}</strong>
          <span className="jd-management-detail__subtitle">{job.jobDescriptionId || "—"}</span>
          <JdStatusPill status={row.statusBucket} />
        </div>
        <button type="button" className="jd-management-link-button" onClick={() => onOpenDrawer(row)}>
          查看完整 JD
        </button>
      </header>

      <div className="jd-management-detail__body">
        <section className="jd-management-detail__meta-grid">
          <span className="jd-management-detail__label">JD名称</span>
          <span className="jd-management-detail__value">{job.title}</span>
          <span className="jd-management-detail__label">城市</span>
          <span className="jd-management-detail__value">{job.location || "—"}</span>
          <span className="jd-management-detail__label">部门</span>
          <span className="jd-management-detail__value">{job.department || "—"}</span>
          <span className="jd-management-detail__label">负责人</span>
          <span className="jd-management-detail__value">{getDemoOwner(row)}</span>
          <span className="jd-management-detail__label">招聘目标</span>
          <span className="jd-management-detail__value">{job.headcount != null ? `${job.headcount} 人` : "—"}</span>
          <span className="jd-management-detail__label">发布时间</span>
          <span className="jd-management-detail__value">{formatMaybeDate(job.createdAt)}</span>
          <span className="jd-management-detail__label">更新时间</span>
          <span className="jd-management-detail__value">{formatMaybeDate(job.updatedAt)}</span>
        </section>

        {job.benefitTags.length ? (
          <section className="jd-management-tag-list">
            {job.benefitTags.slice(0, 6).map((tag) => (
              <span key={tag} className="jd-management-tag">{tag}</span>
            ))}
          </section>
        ) : null}

        <section className="jd-management-drawer__card">
          <strong className="jd-management-drawer__section-title">招聘进展</strong>
          <div className="jd-management-funnel">
            {row.funnelSteps.map((step) => (
              <div key={step.key} className="jd-management-funnel__step">
                <span>{step.label}</span>
                <strong>{step.value}</strong>
                <span>{step.percent}%</span>
              </div>
            ))}
          </div>
        </section>

        <section className="jd-management-drawer__card">
          <div className="jd-management-titlebar__actions">
            <strong className="jd-management-drawer__section-title">近期候选人</strong>
            <button type="button" className="jd-management-link-button">查看全部</button>
          </div>
          <div className="jd-management-recent-list">
            {row.recentApplications.length ? row.recentApplications.map((item) => (
              <div key={item.id} className="jd-management-recent-item">
                <span className="jd-management-avatar">
                  {item.avatarUrl ? <img src={item.avatarUrl} alt="" /> : item.personName.slice(0, 1)}
                </span>
                <span className="jd-management-recent-item__body">
                  <strong>{item.personName}</strong>
                  <span>{item.statusLabel}</span>
                </span>
                <span className="jd-management-recent-item__time">{item.updatedAt || "—"}</span>
              </div>
            )) : <span className="jd-management-summary-text">暂无近期投递人</span>}
          </div>
        </section>

        <section className="jd-management-drawer__card">
          <strong className="jd-management-drawer__section-title">当前转化概览</strong>
          <div className="jd-management-detail__meta-grid">
            <span className="jd-management-detail__label">投递量</span>
            <span className="jd-management-detail__value">{trendCount}</span>
            <span className="jd-management-detail__label">沟通率</span>
            <span className="jd-management-detail__value">{percentOf(row.funnelSteps[1]?.value ?? 0, row.currentApplicants)} · {trendRate}</span>
            <span className="jd-management-detail__label">面试率</span>
            <span className="jd-management-detail__value">{percentOf(row.interviewing, row.currentApplicants)}</span>
            <span className="jd-management-detail__label">Offer率</span>
            <span className="jd-management-detail__value">{percentOf(row.offers, row.currentApplicants)}</span>
          </div>
        </section>

        <section className="jd-management-drawer__card">
          <strong className="jd-management-drawer__section-title">关键要点</strong>
          <p className="jd-management-summary-text">{focus}</p>
        </section>

        <section className="jd-management-drawer__card">
          <div className="jd-management-titlebar__actions">
            <strong className="jd-management-drawer__section-title">JD 预览摘要</strong>
            <button type="button" className="jd-management-link-button" onClick={() => onOpenDrawer(row)}>
              查看完整 JD
            </button>
          </div>
          <p className="jd-management-summary-text">{job.summary || job.description || "暂无 JD 摘要。"}</p>
        </section>
      </div>
    </aside>
  );
}

function JdFullDrawer({
  row,
  creating,
  saving,
  onClose,
  onSave,
  onDelete,
}: {
  row: JdManagementRow | null;
  creating: boolean;
  saving: boolean;
  onClose(): void;
  onSave(form: JdFormState): Promise<void> | void;
  onDelete(row: JdManagementRow): Promise<void> | void;
}): JSX.Element {
  const [form, setForm] = useState<JdFormState>(() => makeFormState(row?.job ?? emptyJob));

  useEffect(() => {
    setForm(makeFormState(row?.job ?? emptyJob));
  }, [creating, row?.key]);

  const setField = <K extends keyof JdFormState>(key: K, value: JdFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  return (
    <div className="drawer-backdrop" role="presentation">
      <aside className="drawer jd-management-drawer" role="dialog" aria-modal="true" aria-label="JD 详情">
        <header className="drawer__header">
          <div>
            <div className="drawer__eyebrow">JD 详情</div>
            <h2 className="drawer__title">{creating ? "新建职位" : form.title || "未命名职位"}</h2>
            <p className="drawer__description">{form.jobDescriptionId || "保存后生成职位 ID"}</p>
          </div>
          <div className="jd-management-drawer__actions">
            <button type="button" className="jd-management-button" onClick={onClose}>收起</button>
            <button type="button" className="drawer__close" onClick={onClose} aria-label="关闭">×</button>
          </div>
        </header>

        <div className="drawer__body">
          <section className="jd-management-drawer__card">
            <div className="jd-management-drawer__actions">
              <button type="button" className="jd-management-button">编辑 JD</button>
              <button
                type="button"
                className="jd-management-button jd-management-button--danger"
                disabled={creating || !row?.job.jobDescriptionId || saving}
                onClick={() => row ? void onDelete(row) : undefined}
              >
                删除 JD
              </button>
            </div>
          </section>

          <form className="jd-management-drawer__form" onSubmit={(event) => {
            event.preventDefault();
            void onSave(form);
          }}>
            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">一、基本信息</strong>
              <div className="jd-management-drawer__grid">
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">JD名称</span>
                  <input className="jd-management-drawer__input" value={form.title} onChange={(event) => setField("title", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">职位ID</span>
                  <input className="jd-management-drawer__input" value={form.jobDescriptionId} disabled />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">城市</span>
                  <input className="jd-management-drawer__input" value={form.location} onChange={(event) => setField("location", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">部门</span>
                  <input className="jd-management-drawer__input" value={form.department} onChange={(event) => setField("department", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">招聘负责人</span>
                  <input className="jd-management-drawer__input" value={form.ownerName} onChange={(event) => setField("ownerName", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">招聘目标</span>
                  <input className="jd-management-drawer__input" value={form.headcount} onChange={(event) => setField("headcount", event.target.value)} />
                </label>
              </div>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">二、职位描述</strong>
              <div className="jd-management-drawer__toolbar">B I U · 对齐 · 列表 · 链接</div>
              <label className="jd-management-drawer__field">
                <span className="jd-management-drawer__label">职位描述</span>
                <textarea className="jd-management-drawer__textarea" value={form.description} onChange={(event) => setField("description", event.target.value)} />
              </label>
              <label className="jd-management-drawer__field">
                <span className="jd-management-drawer__label">任职要求</span>
                <textarea className="jd-management-drawer__textarea" value={form.requirements} onChange={(event) => setField("requirements", event.target.value)} />
              </label>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">三、招聘信息</strong>
              <div className="jd-management-drawer__grid">
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">学历要求</span>
                  <input className="jd-management-drawer__input" value={form.educationRequirement} onChange={(event) => setField("educationRequirement", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">工作经验</span>
                  <input className="jd-management-drawer__input" value={form.experienceRequirement} onChange={(event) => setField("experienceRequirement", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">薪资范围</span>
                  <input className="jd-management-drawer__input" value={form.compensationText} onChange={(event) => setField("compensationText", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">用工类型</span>
                  <input className="jd-management-drawer__input" value={form.employmentType} onChange={(event) => setField("employmentType", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">职位状态</span>
                  <select className="jd-management-drawer__select" value={form.status} onChange={(event) => setField("status", event.target.value as JdStatusBucket)}>
                    <option value="recruiting">招聘中</option>
                    <option value="paused">暂停中</option>
                    <option value="closed">已关闭</option>
                  </select>
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">来源</span>
                  <input className="jd-management-drawer__input" value={form.source} onChange={(event) => setField("source", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field jd-management-drawer__field--full">
                  <span className="jd-management-drawer__label">标签</span>
                  <input className="jd-management-drawer__input" value={form.benefitTags} onChange={(event) => setField("benefitTags", event.target.value)} />
                </label>
              </div>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">四、发布记录</strong>
              <div className="jd-management-drawer__history">
                <div className="jd-management-drawer__history-item">
                  <span className="jd-management-drawer__history-dot" />
                  <span>更新了 JD 内容</span>
                  <span>{formatMaybeDate(row?.job.updatedAt)}</span>
                </div>
                <div className="jd-management-drawer__history-item">
                  <span className="jd-management-drawer__history-dot" />
                  <span>发布了职位</span>
                  <span>{formatMaybeDate(row?.job.createdAt)}</span>
                </div>
              </div>
            </section>
          </form>
        </div>

        <footer className="drawer__footer">
          <button type="button" className="jd-management-button" onClick={onClose}>关闭</button>
          <button
            type="button"
            className="jd-management-button jd-management-button--primary"
            disabled={saving}
            onClick={() => void onSave(form)}
          >
            {saving ? "保存中" : "保存"}
          </button>
        </footer>
      </aside>
    </div>
  );
}

export function JdManagementView({
  applications,
  jobDescriptions,
  onRefresh,
}: JdManagementViewProps): JSX.Element {
  const model = useMemo(() => buildJdManagementModel(jobDescriptions, applications), [applications, jobDescriptions]);
  const [statusFilter, setStatusFilter] = useState<"all" | JdStatusBucket>("all");
  const [cityFilter, setCityFilter] = useState("all");
  const [departmentFilter, setDepartmentFilter] = useState("all");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerRow, setDrawerRow] = useState<JdManagementRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);

  const cityOptions = useMemo(() => [...new Set(model.rows.map((row) => row.job.location).filter(Boolean) as string[])], [model.rows]);
  const departmentOptions = useMemo(() => [...new Set(model.rows.map((row) => row.job.department).filter(Boolean) as string[])], [model.rows]);
  const ownerOptions = useMemo(() => [...new Set(model.rows.map(getDemoOwner).filter((owner) => owner !== "未设置"))], [model.rows]);

  const filteredRows = useMemo(
    () => model.rows.filter((row) => (
      (statusFilter === "all" || row.statusBucket === statusFilter) &&
      (cityFilter === "all" || row.job.location === cityFilter) &&
      (departmentFilter === "all" || row.job.department === departmentFilter) &&
      (ownerFilter === "all" || getDemoOwner(row) === ownerFilter) &&
      rowMatchesKeyword(row, keyword)
    )),
    [cityFilter, departmentFilter, keyword, model.rows, ownerFilter, statusFilter],
  );

  useEffect(() => {
    if (!filteredRows.length) {
      setSelectedKey(null);
      return;
    }
    if (!selectedKey || !filteredRows.some((row) => row.key === selectedKey)) {
      setSelectedKey(filteredRows[0]?.key ?? null);
    }
  }, [filteredRows, selectedKey]);

  const selectedRow = filteredRows.find((row) => row.key === selectedKey) ?? filteredRows[0] ?? null;

  const openDrawer = async (row: JdManagementRow) => {
    if (!row.job.jobDescriptionId) {
      setDrawerRow(row);
      setCreating(false);
      return;
    }
    try {
      const detail = await apiClient.getJobDescription(row.job.jobDescriptionId);
      setDrawerRow({ ...row, job: detail });
    } catch {
      setDrawerRow(row);
    }
    setCreating(false);
  };

  const saveDrawer = async (form: JdFormState) => {
    setSaving(true);
    try {
      const original = creating ? undefined : drawerRow?.job;
      const payload = formToPayload(form, original);
      if (creating || !drawerRow?.job.jobDescriptionId) {
        await apiClient.createJobDescription(payload);
      } else {
        await apiClient.updateJobDescription(drawerRow.job.jobDescriptionId, payload);
      }
      await onRefresh();
      setCreating(false);
      setDrawerRow(null);
    } finally {
      setSaving(false);
    }
  };

  const deleteDrawer = async (row: JdManagementRow) => {
    const jobDescriptionId = row.job.jobDescriptionId;
    if (!jobDescriptionId) {
      return;
    }
    if (!window.confirm(`确认删除 ${row.job.title}？相关投递记录会保留，但将不再关联该 JD。`)) {
      return;
    }
    setSaving(true);
    try {
      await apiClient.deleteJobDescription(jobDescriptionId);
      await onRefresh();
      setDrawerRow(null);
      setCreating(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="jd-management-page">
      <main className="jd-management-workspace">
        <header className="jd-management-titlebar">
          <h1>职位管理</h1>
          <div className="jd-management-titlebar__actions">
            <label className="jd-management-filter">
              岗位状态
              <select className="jd-management-select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | JdStatusBucket)}>
                <option value="all">全部</option>
                <option value="recruiting">招聘中</option>
                <option value="paused">暂停中</option>
                <option value="closed">已关闭</option>
              </select>
            </label>
          </div>
        </header>

        <div className="jd-management-filterbar">
          <div className="jd-management-filterbar__group">
            <label className="jd-management-filter">
              城市
              <select className="jd-management-select" value={cityFilter} onChange={(event) => setCityFilter(event.target.value)}>
                <option value="all">全部</option>
                {cityOptions.map((city) => <option key={city} value={city}>{city}</option>)}
              </select>
            </label>
            <label className="jd-management-filter">
              用人部门
              <select className="jd-management-select" value={departmentFilter} onChange={(event) => setDepartmentFilter(event.target.value)}>
                <option value="all">全部</option>
                {departmentOptions.map((department) => <option key={department} value={department}>{department}</option>)}
              </select>
            </label>
            <label className="jd-management-filter">
              招聘负责人
              <select className="jd-management-select" value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)}>
                <option value="all">全部</option>
                {ownerOptions.map((owner) => <option key={owner} value={owner}>{owner}</option>)}
              </select>
            </label>
          </div>
          <div className="jd-management-filterbar__group">
            <input
              className="jd-management-input"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索职位名称 / JD名称 / 职位ID"
            />
            <button type="button" className="jd-management-button jd-management-button--primary" onClick={() => {
              setCreating(true);
              setDrawerRow(null);
            }}>
              + 新建职位
            </button>
            <button type="button" className="jd-management-button" onClick={() => void onRefresh()}>
              刷新
            </button>
          </div>
        </div>

        <section className="jd-management-kpis">
          <JdStatCard label="全部职位" value={model.stats.total} caption="较昨日 +3" />
          <JdStatCard label="招聘中" value={model.stats.recruiting} caption="较昨日 +2" ratio={percentOf(model.stats.recruiting, model.stats.total)} />
          <JdStatCard label="暂停中" value={model.stats.paused} caption="较昨日 -1" ratio={percentOf(model.stats.paused, model.stats.total)} tone="warning" />
          <JdStatCard label="已关闭" value={model.stats.closed} caption="较昨日 +2" ratio={percentOf(model.stats.closed, model.stats.total)} tone="neutral" />
        </section>

        <section className="jd-management-table-card">
          <div className="jd-management-table-wrap">
            <table className="jd-management-table">
              <thead>
                <tr>
                  <th><input className="jd-management-checkbox" type="checkbox" aria-label="全选职位" /></th>
                  <th>职位名称</th>
                  <th>城市</th>
                  <th>部门</th>
                  <th>HC</th>
                  <th>在招状态</th>
                  <th>当前候选人</th>
                  <th>面试中</th>
                  <th>Offer中</th>
                  <th>最近更新</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <tr key={row.key} data-active={selectedRow?.key === row.key ? "true" : undefined} onClick={() => setSelectedKey(row.key)}>
                    <td><input className="jd-management-checkbox" type="checkbox" checked={selectedRow?.key === row.key} readOnly aria-label={`选择 ${row.job.title}`} /></td>
                    <td>
                      <span className="jd-management-role-cell">
                        <strong>{row.job.title}</strong>
                        <span>{row.job.jobDescriptionId || "—"}</span>
                      </span>
                    </td>
                    <td>{row.job.location || "—"}</td>
                    <td>{row.job.department || "—"}</td>
                    <td>{row.job.headcount ?? "—"}</td>
                    <td><JdStatusPill status={row.statusBucket} /></td>
                    <td>{row.currentApplicants}</td>
                    <td>{row.interviewing}</td>
                    <td>{row.offers}</td>
                    <td>{row.latestUpdateText || "—"}</td>
                    <td>
                      <button type="button" className="jd-management-link-button" onClick={(event) => {
                        event.stopPropagation();
                        void openDrawer(row);
                      }}>
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <footer className="jd-management-pagination">
          <span className="jd-management-detail__value">共 {filteredRows.length} 条</span>
          <select className="jd-management-select" defaultValue="20">
            <option value="20">20 条/页</option>
            <option value="50">50 条/页</option>
          </select>
          <span className="jd-management-detail__value">1 2 3 4 5 ...</span>
          <label className="jd-management-filter">
            前往
            <input className="jd-management-input" style={{ width: "56px" }} defaultValue="1" />
            页
          </label>
        </footer>
      </main>

      <JdDetailCard row={selectedRow} onOpenDrawer={(row) => void openDrawer(row)} />

      {(drawerRow || creating) ? (
        <JdFullDrawer
          row={drawerRow}
          creating={creating}
          saving={saving}
          onClose={() => {
            setDrawerRow(null);
            setCreating(false);
          }}
          onSave={saveDrawer}
          onDelete={deleteDrawer}
        />
      ) : null}
    </section>
  );
}

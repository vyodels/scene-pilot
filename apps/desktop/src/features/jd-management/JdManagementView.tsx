import React, { useEffect, useMemo, useState } from "react";
import {
  FormInput,
  FormSelect,
  FormTextarea,
  PageToolbar,
  PageToolbarGroup,
  ToolbarButton,
  ToolbarField,
  ToolbarInput,
  ToolbarRefreshButton,
  ToolbarSelect,
} from "../../components";
import type { ApplicationViewModel } from "../kanban-shared/kanbanUtils";
import { apiClient } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import type { JobDescriptionFunnelStatsRecord, JobDescriptionPayload, JobDescriptionSummaryRecord } from "../../lib/types";
import {
  buildJdManagementModel,
  getJdMetadataString,
  jdStatusLabel,
  type JdManagementRow,
  type JdManagementStats,
  type JdStatusBucket,
} from "./jdManagementUtils";

interface JdManagementViewProps {
  applications: ApplicationViewModel[];
  jobDescriptions: JobDescriptionSummaryRecord[];
  preferredJobKey?: string | null;
  preferredFocusToken?: number;
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
  title: "",
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
  source: "",
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
    source: job.source || "",
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
    title: form.title.trim(),
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
    source: form.source.trim() || undefined,
  };
}

function percentOf(value: number, total: number): string {
  if (!total) {
    return "0%";
  }
  return `${Math.round((value / total) * 1000) / 10}%`;
}

function optionalPercentOf(value: number | undefined, total: number | undefined): string | undefined {
  return value != null && total != null ? percentOf(value, total) : undefined;
}

function statValue(value: number | null | undefined): string | number {
  return value == null ? "—" : value;
}

function clampPage(value: number, pageCount: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }
  return Math.min(Math.max(1, Math.trunc(value)), pageCount);
}

function getOwnerDisplay(row: JdManagementRow): string {
  return row.ownerName && row.ownerName !== "—" ? row.ownerName : "—";
}

function getOwnerInitial(row: JdManagementRow | null): string {
  if (!row) {
    return "";
  }
  const owner = getOwnerDisplay(row);
  return owner !== "—" ? owner.slice(0, 1) : "";
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
  icon,
}: {
  label: string;
  value: number | string;
  caption?: string;
  ratio?: string;
  tone?: "positive" | "warning" | "neutral";
  icon: "briefcase" | "cap" | "pause" | "closed";
}): JSX.Element {
  return (
    <div className="jd-management-kpi" data-tone={tone}>
      <span className="jd-management-kpi__icon" data-icon={icon} aria-hidden="true" />
      <div className="jd-management-kpi__body">
        <span className="jd-management-kpi__label">{label}</span>
        <strong className="jd-management-kpi__value">{value}</strong>
        {caption ? <span className="jd-management-kpi__caption">{caption}</span> : null}
      </div>
      {ratio ? <span className="jd-management-kpi__ratio">{ratio}</span> : null}
    </div>
  );
}

function optionalJdMetadataString(job: JobDescriptionSummaryRecord, keys: string[]): string | undefined {
  const value = getJdMetadataString(job, keys, "");
  return value.trim() ? value : undefined;
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
      <aside className="jd-management-detail jd-management-detail--empty">
        <div className="jd-management-empty">还没有职位数据哦～</div>
      </aside>
    );
  }

  const job = row.job;
  const recommendedBy = optionalJdMetadataString(job, ["recommendedBy", "recommended_by", "sourceName"]);
  const focus = optionalJdMetadataString(job, ["focus", "focusText", "focus_text", "keyFocus"]) ?? job.requirements;

  return (
    <aside className="jd-management-detail">
      <header className="jd-management-detail__header">
        <div className="jd-management-detail__head">
          <div className="jd-management-detail__title-row">
            <strong className="jd-management-detail__title">{job.title}</strong>
            <JdStatusPill status={row.statusBucket} />
          </div>
          <span className="jd-management-detail__subtitle">{job.jobDescriptionId || "—"}</span>
          {recommendedBy ? <span className="jd-management-agent-badge">{recommendedBy}</span> : null}
        </div>
      </header>

      <div className="jd-management-detail__body">
        <section className="jd-management-detail__meta-grid jd-management-detail__meta-grid--primary">
          <span className="jd-management-detail__label">JD名称</span>
          <span className="jd-management-detail__value">{job.title}</span>
          <span className="jd-management-detail__label">城市</span>
          <span className="jd-management-detail__value">{job.location || "—"}</span>
          <span className="jd-management-detail__label">部门</span>
          <span className="jd-management-detail__value">{job.department || "—"}</span>
          <span className="jd-management-detail__label">负责人</span>
          <span className="jd-management-owner-line">
            <span className="jd-management-avatar jd-management-avatar--sm">{getOwnerInitial(row)}</span>
            <span>{getOwnerDisplay(row)}</span>
          </span>
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

        <section className="jd-management-panel-card">
          <div className="jd-management-detail__section-head">
            <strong className="jd-management-drawer__section-title">招聘进展</strong>
            <span>当前岗位</span>
          </div>
          <div className="jd-management-funnel">
            {row.funnelSteps.length ? row.funnelSteps.map((step) => (
              <div key={step.key} className="jd-management-funnel__step">
                <span>{step.label}</span>
                <strong>{statValue(step.value)}</strong>
                <span>{step.percent == null ? "—" : `${step.percent}%`}</span>
              </div>
            )) : <span className="jd-management-summary-text">—</span>}
          </div>
        </section>

        <section className="jd-management-panel-card">
          <div className="jd-management-detail__section-head">
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

        <div className="jd-management-detail__analysis-grid">
          <section className="jd-management-panel-card jd-management-panel-card--compact">
            <div className="jd-management-detail__section-head">
              <strong className="jd-management-drawer__section-title">当前转化概览</strong>
              <span>当前岗位</span>
            </div>
            <div className="jd-management-detail__metric-list" data-disabled={row.currentApplicants == null ? "true" : undefined}>
              <span>投递量</span>
              <strong>{statValue(row.currentApplicants)}</strong>
              <span>沟通率</span>
              <strong>
                {optionalPercentOf(row.communicating ?? undefined, row.currentApplicants ?? undefined) ?? "—"}
              </strong>
              <span>面试率</span>
              <strong>{optionalPercentOf(row.interviewing ?? undefined, row.currentApplicants ?? undefined) ?? "—"}</strong>
              <span>Offer率</span>
              <strong>{optionalPercentOf(row.offers ?? undefined, row.currentApplicants ?? undefined) ?? "—"}</strong>
            </div>
          </section>

          <section className="jd-management-panel-card jd-management-panel-card--compact">
            <div className="jd-management-detail__section-head">
              <strong className="jd-management-drawer__section-title">关键要点</strong>
              <span>摘要</span>
            </div>
            <p className="jd-management-summary-text">{focus || "—"}</p>
          </section>
        </div>

        <section className="jd-management-panel-card">
          <div className="jd-management-detail__section-head">
            <strong className="jd-management-drawer__section-title">JD 预览摘要</strong>
            <button type="button" className="jd-management-link-button" onClick={() => onOpenDrawer(row)}>
              查看完整 JD
            </button>
          </div>
          <p className="jd-management-summary-text">{job.summary || job.description || "—"}</p>
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
          <h2 className="drawer__title">JD 详情</h2>
          <div className="jd-management-drawer__actions">
            <button type="button" className="jd-management-drawer__collapse" onClick={onClose}>« 收起</button>
            <button type="button" className="drawer__close" onClick={onClose} aria-label="关闭">×</button>
          </div>
        </header>

        <div className="drawer__body">
          <div className="jd-management-drawer__toolbar-row">
            <div className="jd-management-drawer__actions">
              <button type="button" className="jd-management-button jd-management-button--outline-primary">编辑 JD</button>
              <button
                type="button"
                className="jd-management-button jd-management-button--danger"
                disabled={creating || !row?.job.jobDescriptionId || saving}
                onClick={() => row ? void onDelete(row) : undefined}
              >
                删除 JD
              </button>
            </div>
          </div>

          <form className="jd-management-drawer__form" onSubmit={(event) => {
            event.preventDefault();
            void onSave(form);
          }}>
            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">一、基本信息</strong>
              <div className="jd-management-drawer__grid">
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">JD名称</span>
                  <FormInput className="jd-management-drawer__input" value={form.title} onChange={(event) => setField("title", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">职位ID</span>
                  <FormInput className="jd-management-drawer__input" value={form.jobDescriptionId} disabled />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">城市</span>
                  <FormInput className="jd-management-drawer__input" value={form.location} onChange={(event) => setField("location", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">部门</span>
                  <FormInput className="jd-management-drawer__input" value={form.department} onChange={(event) => setField("department", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">招聘负责人</span>
                  <FormInput className="jd-management-drawer__input" value={form.ownerName} onChange={(event) => setField("ownerName", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">招聘目标</span>
                  <FormInput className="jd-management-drawer__input" value={form.headcount} onChange={(event) => setField("headcount", event.target.value)} />
                </label>
              </div>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">二、职位描述</strong>
              <div className="jd-management-drawer__formatbar" aria-label="编辑工具栏">
                {["↶", "↷", "B", "I", "U", "≡", "•", "↗"].map((item) => (
                  <button key={item} type="button" aria-label={`格式 ${item}`}>{item}</button>
                ))}
              </div>
              <label className="jd-management-drawer__field">
                <span className="jd-management-drawer__label">职位描述</span>
                <FormTextarea className="jd-management-drawer__textarea" value={form.description} onChange={(event) => setField("description", event.target.value)} />
              </label>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">三、任职要求</strong>
              <label className="jd-management-drawer__field">
                <span className="jd-management-drawer__label">任职要求</span>
                <FormTextarea className="jd-management-drawer__textarea" value={form.requirements} onChange={(event) => setField("requirements", event.target.value)} />
              </label>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">四、招聘信息</strong>
              <div className="jd-management-drawer__grid">
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">学历要求</span>
                  <FormInput className="jd-management-drawer__input" value={form.educationRequirement} onChange={(event) => setField("educationRequirement", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">工作经验</span>
                  <FormInput className="jd-management-drawer__input" value={form.experienceRequirement} onChange={(event) => setField("experienceRequirement", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">薪资范围</span>
                  <FormInput className="jd-management-drawer__input" value={form.compensationText} onChange={(event) => setField("compensationText", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">用工类型</span>
                  <FormInput className="jd-management-drawer__input" value={form.employmentType} onChange={(event) => setField("employmentType", event.target.value)} />
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">职位状态</span>
                  <FormSelect className="jd-management-drawer__select" value={form.status} onChange={(event) => setField("status", event.target.value as JdStatusBucket)}>
                    <option value="recruiting">招聘中</option>
                    <option value="paused">暂停中</option>
                    <option value="closed">已关闭</option>
                  </FormSelect>
                </label>
                <label className="jd-management-drawer__field">
                  <span className="jd-management-drawer__label">来源</span>
                  <FormInput className="jd-management-drawer__input" value={form.source} onChange={(event) => setField("source", event.target.value)} />
                </label>
              </div>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">五、标签</strong>
              <label className="jd-management-drawer__field">
                <span className="jd-management-drawer__label">岗位标签</span>
                <FormInput className="jd-management-drawer__input" value={form.benefitTags} onChange={(event) => setField("benefitTags", event.target.value)} />
              </label>
              <div className="jd-management-tag-list">
                {form.benefitTags.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean).slice(0, 8).map((tag) => (
                  <span key={tag} className="jd-management-tag">{tag}</span>
                ))}
              </div>
            </section>

            <section className="jd-management-drawer__card">
              <strong className="jd-management-drawer__section-title">六、发布记录</strong>
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
  preferredJobKey,
  preferredFocusToken,
  onRefresh,
}: JdManagementViewProps): JSX.Element {
  const [serverJobs, setServerJobs] = useState<JobDescriptionSummaryRecord[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [kpiTotals, setKpiTotals] = useState<JdManagementStats | null>(null);
  const [funnelStatsByJobId, setFunnelStatsByJobId] = useState<Record<string, JobDescriptionFunnelStatsRecord>>({});
  const [serverLoading, setServerLoading] = useState(true);
  const [serverError, setServerError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [statusFilter, setStatusFilter] = useState<"all" | JdStatusBucket>("all");
  const [cityFilter, setCityFilter] = useState("all");
  const [departmentFilter, setDepartmentFilter] = useState("all");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [applicantKeyword, setApplicantKeyword] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerRow, setDrawerRow] = useState<JdManagementRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);

  const catalogModel = useMemo(() => buildJdManagementModel(jobDescriptions, applications), [applications, jobDescriptions]);
  const model = useMemo(
    () => buildJdManagementModel(serverJobs, applications, funnelStatsByJobId),
    [applications, funnelStatsByJobId, serverJobs],
  );
  const cityOptions = useMemo(() => [...new Set(catalogModel.rows.map((row) => row.job.location).filter(Boolean) as string[])], [catalogModel.rows]);
  const departmentOptions = useMemo(() => [...new Set(catalogModel.rows.map((row) => row.job.department).filter(Boolean) as string[])], [catalogModel.rows]);
  const ownerOptions = useMemo(() => [...new Set(catalogModel.rows.map(getOwnerDisplay).filter((owner) => owner !== "—"))], [catalogModel.rows]);
  const kpiTotal = kpiTotals?.total;

  const filteredRows = useMemo(
    () => model.rows.filter((row) => (
      (statusFilter === "all" || row.statusBucket === statusFilter) &&
      (cityFilter === "all" || row.job.location === cityFilter) &&
      (departmentFilter === "all" || row.job.department === departmentFilter) &&
      (ownerFilter === "all" || getOwnerDisplay(row) === ownerFilter) &&
      rowMatchesKeyword(row, keyword)
    )),
    [cityFilter, departmentFilter, keyword, model.rows, ownerFilter, statusFilter],
  );
  const pageCount = Math.max(1, Math.ceil(serverTotal / pageSize));
  const currentPage = clampPage(page, pageCount);
  const paginatedRows = filteredRows;
  const pageStart = serverTotal ? (currentPage - 1) * pageSize + 1 : 0;
  const pageEnd = Math.min((currentPage - 1) * pageSize + paginatedRows.length, serverTotal);
  const pageNumbers = useMemo(() => {
    const windowSize = 5;
    const halfWindow = Math.floor(windowSize / 2);
    const start = Math.max(1, Math.min(currentPage - halfWindow, pageCount - windowSize + 1));
    const end = Math.min(pageCount, start + windowSize - 1);
    return Array.from({ length: end - start + 1 }, (_, index) => start + index);
  }, [currentPage, pageCount]);

  useEffect(() => {
    setPage(1);
  }, [applicantKeyword, cityFilter, departmentFilter, keyword, ownerFilter, pageSize, statusFilter]);

  useEffect(() => {
    setPage((current) => clampPage(current, pageCount));
  }, [pageCount]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      apiClient.listJobDescriptionsPage({ limit: 1, offset: 0 }),
      apiClient.listJobDescriptionsPage({ limit: 1, offset: 0, status: "active" }),
      apiClient.listJobDescriptionsPage({ limit: 1, offset: 0, status: "paused" }),
      apiClient.listJobDescriptionsPage({ limit: 1, offset: 0, status: "closed" }),
    ]).then(([all, recruiting, paused, closed]) => {
      if (!cancelled) {
        setKpiTotals({
          total: all.total,
          recruiting: recruiting.total,
          paused: paused.total,
          closed: closed.total,
        });
      }
    }).catch(() => {
      if (!cancelled) {
        setKpiTotals(null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  useEffect(() => {
    let cancelled = false;
    setServerLoading(true);
    setServerError(null);
    void apiClient.listJobDescriptionsPage({
      limit: pageSize,
      offset: (currentPage - 1) * pageSize,
      status: statusFilter === "all" ? null : statusApiValue(statusFilter),
      location: cityFilter === "all" ? null : cityFilter,
      department: departmentFilter === "all" ? null : departmentFilter,
      owner: ownerFilter === "all" ? null : ownerFilter,
      keyword: keyword.trim() || null,
      applicantKeyword: applicantKeyword.trim() || null,
    }).then((result) => {
      if (cancelled) {
        return;
      }
      setServerJobs(result.items);
      setServerTotal(result.total);
    }).catch((error) => {
      if (cancelled) {
        return;
      }
      setServerJobs([]);
      setServerTotal(0);
      setServerError(error instanceof Error ? error.message : "职位列表加载失败");
    }).finally(() => {
      if (!cancelled) {
        setServerLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [cityFilter, currentPage, departmentFilter, keyword, ownerFilter, pageSize, reloadToken, statusFilter]);

  useEffect(() => {
    const ids = serverJobs
      .map((job) => job.jobDescriptionId)
      .filter((id): id is string => Boolean(id));
    if (!ids.length) {
      setFunnelStatsByJobId({});
      return;
    }
    let cancelled = false;
    void Promise.all(
      ids.map((jobDescriptionId) =>
        apiClient.getJobDescriptionFunnelStats(jobDescriptionId).then((stats) => [jobDescriptionId, stats] as const),
      ),
    ).then((entries) => {
      if (!cancelled) {
        setFunnelStatsByJobId(Object.fromEntries(entries));
      }
    }).catch(() => {
      if (!cancelled) {
        setFunnelStatsByJobId({});
      }
    });
    return () => {
      cancelled = true;
    };
  }, [serverJobs]);

  useEffect(() => {
    if (!paginatedRows.length) {
      setSelectedKey(null);
      return;
    }
    if (!selectedKey || !paginatedRows.some((row) => row.key === selectedKey)) {
      setSelectedKey(paginatedRows[0]?.key ?? null);
    }
  }, [paginatedRows, selectedKey]);

  useEffect(() => {
    const key = String(preferredJobKey ?? "").trim();
    if (!key || preferredFocusToken == null) {
      return;
    }
    const matchingRow = paginatedRows.find((row) => row.key === key || row.job.jobDescriptionId === key || row.job.title === key);
    if (matchingRow) {
      setSelectedKey(matchingRow.key);
      return;
    }
    setKeyword(key);
    setPage(1);
  }, [paginatedRows, preferredFocusToken, preferredJobKey]);

  const selectedRow = paginatedRows.find((row) => row.key === selectedKey) ?? paginatedRows[0] ?? null;

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
      setReloadToken((value) => value + 1);
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
      setReloadToken((value) => value + 1);
      setDrawerRow(null);
      setCreating(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="jd-management-page">
      <main className="jd-management-workspace">
        <PageToolbar className="jd-management-filterbar">
          <PageToolbarGroup className="jd-management-filterbar__group">
            <ToolbarField label="岗位状态">
              <ToolbarSelect value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | JdStatusBucket)}>
                <option value="all">全部</option>
                <option value="recruiting">招聘中</option>
                <option value="paused">暂停中</option>
                <option value="closed">已关闭</option>
              </ToolbarSelect>
            </ToolbarField>
            <ToolbarField label="城市">
              <ToolbarSelect value={cityFilter} onChange={(event) => setCityFilter(event.target.value)}>
                <option value="all">全部</option>
                {cityOptions.map((city) => <option key={city} value={city}>{city}</option>)}
              </ToolbarSelect>
            </ToolbarField>
            <ToolbarField label="用人部门">
              <ToolbarSelect value={departmentFilter} onChange={(event) => setDepartmentFilter(event.target.value)}>
                <option value="all">全部</option>
                {departmentOptions.map((department) => <option key={department} value={department}>{department}</option>)}
              </ToolbarSelect>
            </ToolbarField>
            <ToolbarField label="招聘负责人">
              <ToolbarSelect value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)}>
                <option value="all">全部</option>
                {ownerOptions.map((owner) => <option key={owner} value={owner}>{owner}</option>)}
              </ToolbarSelect>
            </ToolbarField>
          </PageToolbarGroup>
          <PageToolbarGroup className="jd-management-filterbar__group jd-management-filterbar__group--search" align="end">
            <ToolbarField label="职位搜索">
              <ToolbarInput
                className="jd-management-toolbar-input"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="职位名称 / JD名称 / 职位ID"
              />
            </ToolbarField>
            <ToolbarField label="投递人搜索">
              <ToolbarInput
                className="jd-management-toolbar-input jd-management-toolbar-input--applicant"
                value={applicantKeyword}
                onChange={(event) => setApplicantKeyword(event.target.value)}
                placeholder="姓名 / 手机号"
              />
            </ToolbarField>
          </PageToolbarGroup>
        </PageToolbar>

        <section className="jd-management-kpis">
          <JdStatCard label="全部职位" value={kpiTotal ?? "—"} icon="briefcase" />
          <JdStatCard label="招聘中" value={kpiTotals?.recruiting ?? "—"} ratio={optionalPercentOf(kpiTotals?.recruiting, kpiTotal)} icon="cap" />
          <JdStatCard label="暂停中" value={kpiTotals?.paused ?? "—"} ratio={optionalPercentOf(kpiTotals?.paused, kpiTotal)} tone="warning" icon="pause" />
          <JdStatCard label="已关闭" value={kpiTotals?.closed ?? "—"} ratio={optionalPercentOf(kpiTotals?.closed, kpiTotal)} tone="neutral" icon="closed" />
        </section>

        <section className="jd-management-table-card">
          <div className="jd-management-table-wrap">
            <table className="jd-management-table">
              <thead>
                <tr>
                  <th>职位名称</th>
                  <th>城市</th>
                  <th>部门</th>
                  <th>HC</th>
                  <th>在招状态</th>
                  <th>当前候选人</th>
                  <th>沟通中</th>
                  <th>面试中</th>
                  <th>Offer中</th>
                  <th>最近更新</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {serverError ? (
                  <tr>
                    <td colSpan={11} className="jd-management-table__empty">{serverError}</td>
                  </tr>
                ) : null}
                {!serverError && !paginatedRows.length ? (
                  <tr>
                    <td colSpan={11} className="jd-management-table__empty">{serverLoading ? "加载中" : "还没有职位数据哦～"}</td>
                  </tr>
                ) : null}
                {paginatedRows.map((row) => (
                  <tr key={row.key} data-active={selectedRow?.key === row.key ? "true" : undefined} onClick={() => setSelectedKey(row.key)}>
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
                    <td>{statValue(row.currentApplicants)}</td>
                    <td>{statValue(row.communicating)}</td>
                    <td>{statValue(row.interviewing)}</td>
                    <td>{statValue(row.offers)}</td>
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
          <span className="jd-management-detail__value">共 {serverTotal} 条</span>
          <ToolbarSelect value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
            <option value="20">20 条/页</option>
            <option value="50">50 条/页</option>
          </ToolbarSelect>
          <span className="jd-management-detail__value">{pageStart}-{pageEnd}</span>
          <button
            type="button"
            className="jd-management-page-button"
            disabled={currentPage <= 1}
            onClick={() => setPage((value) => clampPage(value - 1, pageCount))}
          >
            ‹
          </button>
          {pageNumbers.map((pageNumber) => (
            <button
              key={pageNumber}
              type="button"
              className="jd-management-page-button"
              data-active={pageNumber === currentPage ? "true" : undefined}
              onClick={() => setPage(pageNumber)}
            >
              {pageNumber}
            </button>
          ))}
          <button
            type="button"
            className="jd-management-page-button"
            disabled={currentPage >= pageCount}
            onClick={() => setPage((value) => clampPage(value + 1, pageCount))}
          >
            ›
          </button>
          <label className="jd-management-filter">
            前往
            <ToolbarInput
              className="jd-management-page-jump-input"
              style={{ width: "56px" }}
              type="number"
              min={1}
              max={pageCount}
              value={currentPage}
              onChange={(event) => setPage(clampPage(Number(event.target.value), pageCount))}
            />
            页
          </label>
        </footer>
      </main>

      <div className="jd-management-side-rail">
        <PageToolbar className="jd-management-side-actions">
          <PageToolbarGroup align="end">
          <ToolbarButton variant="primary" onClick={() => {
            setCreating(true);
            setDrawerRow(null);
          }}>
            + 新建职位
          </ToolbarButton>
          <ToolbarRefreshButton
            onClick={() => {
              void onRefresh();
              setReloadToken((value) => value + 1);
            }}
            label="刷新"
            refreshingLabel="刷新中"
          />
          </PageToolbarGroup>
        </PageToolbar>
        <JdDetailCard row={selectedRow} onOpenDrawer={(row) => void openDrawer(row)} />
      </div>

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

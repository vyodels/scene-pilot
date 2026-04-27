# Boss 直聘风格投递记录跟进页复刻要求

来源：`https://chatgpt.com/s/t_69ef36068d9c8191b37056abf96d1660`

提取时间：2026-04-27

适用范围：`apps/desktop` 中的投递记录跟进页、投递记录漏斗页、JD 管理页相关前端结构与样式。

## 0. 本项目口径适配

共享页原文使用了“候选人 / 候选人沟通页”等描述。落地到本仓库时必须遵守当前产品口径：

- 页面对象是投递记录，不是候选人池。
- UI 中面向当前页面的列表、详情、沟通、状态、历史记录应使用“投递记录 / 投递人 / 当前沟通岗位”口径。
- 只有内部组件或历史类型名暂未改名时，可以继续保留 `Candidate*` 这类代码层命名；对用户可见文案不得继续暴露候选人口径。
- 本文保留原文中的“候选人”字样用于还原共享页要求；实际实现时按上面的投递记录口径映射。

## 1. 原始修改说明全文

下面这段可以直接丢给 Codex，让它按前端结构和样式去改。重点不是业务字段，而是**布局密度、模块层级、滚动区域、消息方向、可折叠结构**。

## 2. 给 Codex 的修改说明

当前「投递记录 / 候选人沟通页」整体功能块基本具备，但页面信息密度偏低，核心问题是：上方区域占用过高、候选人信息卡不够紧凑、聊天区纵向空间不足、左侧候选人列表上方的数据看板入口样式不稳定、右侧评分卡片缺少可折叠交互、候选人与系统/Agent 的消息方向反了。

请只从 UI 结构和前端布局层面优化，不要大改业务逻辑。

## 3. 页面整体布局

页面应该采用一个高密度三栏工作台布局：

```tsx
<AppShell>
  <CollapsedSidebar />
  <MainArea>
    <FilterBar />
    <PipelineBar />
    <WorkspaceGrid>
      <CandidateQueue />
      <CandidateCommunicationPanel />
      <RightInsightPanel />
    </WorkspaceGrid>
  </MainArea>
</AppShell>
```

整体布局建议：

```css
.app-shell {
  height: 100vh;
  display: grid;
  grid-template-columns: 56px 1fr;
  background: #f7f9fb;
  overflow: hidden;
}

.main-area {
  min-width: 0;
  height: 100vh;
  display: grid;
  grid-template-rows: 48px 56px 1fr;
  overflow: hidden;
}

.workspace-grid {
  min-height: 0;
  display: grid;
  grid-template-columns: 300px minmax(720px, 1fr) 320px;
  gap: 12px;
  padding: 12px 16px 14px;
  overflow: hidden;
}
```

核心目标：

- 左侧栏固定 56px。
- 候选人列表栏控制在 280–300px。
- 右侧评分栏控制在 300–320px。
- 中间聊天区吃掉剩余宽度。
- 整页不要出现 body 滚动，内部列表、聊天内容、右侧面板各自独立滚动。
- 页面主内容上下间距压缩到 12px 左右，不要大面积留白。

## 4. 顶部筛选区

顶部只保留一行筛选项，不能换行，不能占两行。

```css
.filter-bar {
  height: 48px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border-bottom: 1px solid #e8edf3;
  background: #fff;
  overflow: hidden;
}

.filter-control {
  height: 32px;
  min-width: 120px;
  font-size: 13px;
}

.search-control {
  margin-left: auto;
  width: 280px;
  height: 32px;
}
```

要求：

- 岗位、时间、日期范围、状态视图、搜索、刷新、头像等全部在一行。
- 表单控件高度统一 32px。
- 字号 12–13px。
- 不要使用大按钮、大输入框。
- 右侧搜索框和刷新按钮靠右。

## 5. 状态机链区域

状态机链要保持一行展示，不要把主状态机链拆成两行。

当前主流程状态比较多，但仍然应该用横向滚动或压缩节点宽度解决，而不是换行撑高页面。

```css
.pipeline-bar {
  height: 56px;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e8edf3;
  overflow: hidden;
}

.pipeline-main {
  height: 40px;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  white-space: nowrap;
  scrollbar-width: none;
}

.pipeline-node {
  flex: 0 0 auto;
  min-width: 72px;
  max-width: 104px;
  height: 38px;
  padding: 4px 8px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 16px;
  text-align: center;
}

.pipeline-node.active {
  color: #00a88f;
  border-bottom: 2px solid #00a88f;
}
```

要求：

- 主状态链始终只占一行。
- 节点文案最多两行小字，但整体节点高度不超过 38px。
- 节点之间用细箭头连接。
- 当前状态节点高亮。
- 异常流程默认收起，只保留右侧「展开异常流程」按钮。
- 点击「展开异常流程」后，在主流程下方显示异常流程，但默认状态不要占空间。

结构建议：

```tsx
<PipelineBar>
  <div className="pipeline-main">
    {mainStatuses.map(status => <PipelineNode />)}
    <button className="expand-exception-btn">展开异常流程</button>
  </div>

  {expanded && (
    <div className="pipeline-exception">
      {exceptionStatuses.map(status => <ExceptionNode />)}
    </div>
  )}
</PipelineBar>
```

## 6. 左侧候选人列表区

左侧区域需要保持高密度，同时保留你喜欢的「数据看板入口」样式。

结构应该是：

```tsx
<CandidateQueue>
  <DashboardEntry />
  <CandidateListHeader />
  <CandidateSearch />
  <CandidateList />
</CandidateQueue>
```

### 6.1 数据看板入口

数据看板入口只保留一个卡片入口，不展示统计汇总。

样式应类似：

```css
.dashboard-entry {
  height: 48px;
  flex: 0 0 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border: 1px solid #e5edf2;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  margin-bottom: 10px;
}

.dashboard-entry:hover {
  border-color: #00a88f;
  background: #f2fbf9;
}
```

内容：

```tsx
<div className="dashboard-entry">
  <div className="entry-left">
    <Icon />
    <span>数据看板</span>
  </div>
  <ChevronRight />
</div>
```

不要在这里展示“沟通总数、AI分、今日推进”等统计块。

### 6.2 候选人列表头

```css
.candidate-list-header {
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.candidate-list-title {
  font-size: 15px;
  font-weight: 600;
}

.status-filter {
  height: 28px;
  font-size: 12px;
}
```

标题样式：

```tsx
<div className="candidate-list-header">
  <div>沟通中（20）</div>
  <Select value="全部状态" />
</div>
```

这里的状态筛选要支持筛选状态机中的所有状态。

### 6.3 候选人卡片

当前候选人卡片高度可以再压缩，建议 68–76px。

```css
.candidate-card {
  height: 72px;
  display: grid;
  grid-template-columns: 42px 1fr auto;
  column-gap: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  cursor: pointer;
}

.candidate-card.active {
  background: #eaf8f6;
  border: 1px solid #8bded3;
}

.candidate-avatar {
  width: 40px;
  height: 40px;
  border-radius: 8px;
}

.candidate-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 20px;
}

.candidate-meta,
.candidate-job {
  font-size: 12px;
  color: #64748b;
  line-height: 18px;
}
```

要求：

- 一张候选人卡片最多三行信息。
- 第一行：姓名 + 在线点 + 时间。
- 第二行：城市 / 年限 / 学历。
- 第三行：当前沟通岗位 / 部门 / 状态。
- 红点未读数量放右侧。
- 列表区域内部滚动，不能撑开页面。

## 7. 中间候选人信息区

中间顶部候选人信息卡需要保持高密度，但不要丢失候选人信息。

当前沟通职位必须放在候选人姓名卡片的右上角区域，且需要明确标题。

推荐结构：

```tsx
<CandidateHeader>
  <CandidateBasicInfo />
  <CandidateDetailGrid />
  <CurrentJobCard />
</CandidateHeader>
```

布局：

```css
.candidate-header {
  flex: 0 0 auto;
  min-height: 150px;
  max-height: 170px;
  display: grid;
  grid-template-columns: 1.1fr 1.3fr 240px;
  gap: 14px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e6ebf0;
  border-radius: 12px;
}
```

左侧候选人基础信息：

```css
.candidate-basic {
  display: grid;
  grid-template-columns: 88px 1fr;
  column-gap: 14px;
}

.profile-photo {
  width: 86px;
  height: 104px;
  border-radius: 10px;
  object-fit: cover;
}

.candidate-name {
  font-size: 22px;
  font-weight: 700;
}

.candidate-summary-line {
  font-size: 13px;
  color: #475569;
  line-height: 22px;
}
```

中间候选人详情：

```css
.candidate-detail-grid {
  display: grid;
  grid-template-columns: 72px 1fr 72px 1fr;
  row-gap: 8px;
  column-gap: 8px;
  font-size: 13px;
}

.detail-label {
  color: #94a3b8;
}

.detail-value {
  color: #1e293b;
}
```

右上角当前沟通职位卡：

```css
.current-job-card {
  padding: 12px;
  border-radius: 10px;
  background: #fbfcfe;
  border: 1px solid #e5eaf0;
}

.current-job-title {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 8px;
}

.current-job-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}
```

内容应该简洁：

```tsx
<div className="current-job-card">
  <div className="current-job-title">当前沟通职位</div>
  <div className="current-job-name">销售工程师</div>
  <div className="current-job-meta">上海 · 企业业务组</div>
  <button>查看 JD</button>
</div>
```

不要在当前沟通职位里放太多字段，重点空间给候选人本身。

## 8. 聊天区需要明显增大

中间主区域应该是 flex column。

```css
.communication-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.candidate-header {
  flex: 0 0 auto;
}

.chat-tabs {
  flex: 0 0 42px;
}

.chat-thread {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 18px;
  background: #fff;
}

.message-composer {
  flex: 0 0 72px;
  border-top: 1px solid #e8edf3;
  padding: 8px 12px;
  background: #fff;
}
```

目标：

- 在 1440×900 视口下，聊天消息区高度至少 420px。
- 不要让候选人信息卡、状态机链、tabs、按钮区挤压聊天区。
- 输入框固定在中间聊天面板底部。
- 聊天消息区独立滚动。

## 9. 消息方向必须修正

现在候选人与 Agent/系统操作人的消息方向反了。

规则：

- 候选人的消息在右侧。
- Agent、系统操作人、招聘负责人、系统消息在左侧。

请按 senderType / role 映射，不要按当前用户是否本人简单判断。

```ts
const isCandidateMessage = message.senderType === 'candidate';

const isOperatorMessage =
  message.senderType === 'agent' ||
  message.senderType === 'operator' ||
  message.senderType === 'system' ||
  message.senderType === 'recruiter';
```

样式：

```css
.message-row {
  display: flex;
  margin: 12px 0;
  gap: 8px;
}

.message-row.candidate {
  justify-content: flex-end;
}

.message-row.operator {
  justify-content: flex-start;
}

.message-row.candidate .avatar {
  order: 2;
}

.message-row.candidate .bubble {
  order: 1;
  background: #e7f7f4;
  border: 1px solid #d2efea;
  border-radius: 12px 12px 2px 12px;
}

.message-row.operator .bubble {
  background: #fff;
  border: 1px solid #e5eaf0;
  border-radius: 12px 12px 12px 2px;
}

.message-bubble {
  max-width: 68%;
  padding: 9px 12px;
  font-size: 13px;
  line-height: 20px;
}
```

时间和已读状态：

```css
.message-time {
  font-size: 11px;
  color: #94a3b8;
  margin-bottom: 4px;
}
```

要求：

- 候选人头像显示在右侧气泡右边。
- Agent/系统操作人头像显示在左侧气泡左边。
- 候选人气泡颜色使用浅绿色。
- 系统/Agent 气泡使用白色或浅灰。
- 不要让气泡宽度超过 68%。

## 10. 聊天 Tabs 和操作按钮

Tabs 和操作按钮要在同一行，不要额外占高度。

```css
.chat-tabs-row {
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #e8edf3;
  border-bottom: 1px solid #e8edf3;
  padding: 0 16px;
  background: #fff;
}

.chat-tabs {
  display: flex;
  align-items: center;
  gap: 24px;
}

.chat-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-action-btn {
  height: 30px;
  padding: 0 10px;
  font-size: 12px;
}
```

结构：

```tsx
<div className="chat-tabs-row">
  <Tabs>
    <Tab>沟通聊天</Tab>
    <Tab>沟通记录</Tab>
    <Tab>面试安排</Tab>
    <Tab>评价反馈</Tab>
    <Tab>备注</Tab>
  </Tabs>

  <div className="chat-actions">
    <Button>常用语</Button>
    <Button>发送职位</Button>
    <Button>交换微信</Button>
    <Button>更多</Button>
  </div>
</div>
```

## 11. 右侧评分面板要恢复可折叠能力

右侧内容保留，但所有评分卡和信息卡都要是 Accordion。

结构：

```tsx
<RightInsightPanel>
  <ScoreAccordion title="AI 综合评分" defaultOpen />
  <ScoreAccordion title="在线简历评分" defaultOpen />
  <ScoreAccordion title="离线简历评分" defaultOpen />
  <Accordion title="当前沟通职位" />
  <Accordion title="在线简历预览" />
  <Accordion title="离线简历预览" />
  <Accordion title="历史投递记录" />
  <Accordion title="历史状态流转记录" />
</RightInsightPanel>
```

样式：

```css
.right-panel {
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.accordion-card {
  background: #fff;
  border: 1px solid #e6ebf0;
  border-radius: 12px;
  overflow: hidden;
}

.accordion-header {
  height: 42px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.score-card-body {
  padding: 10px 14px 14px;
}
```

评分卡默认展开时：

```css
.score-summary {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 12px;
}

.score-number {
  font-size: 34px;
  font-weight: 700;
  color: #00a88f;
  line-height: 1;
}

.score-dimension {
  display: grid;
  grid-template-columns: 72px 1fr 28px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
```

折叠状态：

- 只显示标题、总分、状态、chevron。
- 不显示维度条。
- 卡片高度约 42–48px。

## 12. 信息密度统一规范

当前页面显得不够紧凑，核心是 spacing、font、card height 不统一。请统一以下设计 token：

```css
:root {
  --space-2: 2px;
  --space-4: 4px;
  --space-6: 6px;
  --space-8: 8px;
  --space-10: 10px;
  --space-12: 12px;
  --space-16: 16px;

  --font-xs: 11px;
  --font-sm: 12px;
  --font-md: 13px;
  --font-lg: 15px;
  --font-xl: 20px;

  --line-xs: 16px;
  --line-sm: 18px;
  --line-md: 20px;

  --radius-card: 12px;
  --radius-item: 10px;
}
```

全局要求：

```css
.card {
  border-radius: 12px;
  border: 1px solid #e6ebf0;
  background: #fff;
}

.compact-text {
  font-size: 13px;
  line-height: 20px;
}

.muted-text {
  color: #64748b;
}
```

禁止：

- 大量 `padding: 24px`。
- 大量 `margin-bottom: 24px`。
- 高度超过 180px 的候选人头部卡片。
- 聊天区外层再嵌套多层 padding 导致空间浪费。
- 候选人列表卡片超过 80px。
- 右侧评分卡片不可折叠。

## 13. 当前页面和目标页面的主要差异

需要重点修复这些结构差异：

### 当前问题 1：页面纵向空间浪费

现状：

- 顶部筛选、状态链、二级导航之间留白偏多。
- 状态链节点高度偏高。
- 候选人信息卡下方与聊天区之间留白多。

修改：

- filter bar 固定 48px。
- pipeline bar 固定 56px。
- candidate header 控制在 150–170px。
- tabs row 控制 42px。
- composer 控制 72px。
- 剩余全部给 chat-thread。

### 当前问题 2：左侧候选人列表上方的数据看板样式不稳定

修改：

- 数据看板只做一个入口卡片。
- 放在候选人状态标题上方。
- 不展示统计数字。
- 高度 48px。
- 卡片右侧有箭头。
- hover 和 active 使用浅绿色背景。

### 当前问题 3：聊天消息方向错误

修改：

- candidate 右侧。
- agent/operator/system/recruiter 左侧。
- 不要按登录用户判断方向。
- 方向只由 message.senderType 判断。

### 当前问题 4：右侧评分折叠丢失

修改：

- 右侧所有模块统一使用 Accordion。
- 三个评分默认展开。
- 其余模块默认折叠。
- 每个评分卡也可以折叠。
- 折叠后只显示标题和总分。

### 当前问题 5：聊天区不够大

修改：

- 中间列改成 `display: flex; flex-direction: column; min-height: 0;`
- chat-thread 使用 `flex: 1; overflow-y: auto;`
- composer 固定底部。
- 不要让页面 body 滚动。
- 主工作区内部滚动。

## 14. 建议的验收标准

请按下面标准检查：

- 1440×900 视口下，顶部筛选 + 状态机链总高度不超过 104px。
- 左侧数据看板入口高度约 48px，只显示入口，不显示统计。
- 左侧候选人卡片高度不超过 76px。
- 中间候选人信息卡高度不超过 170px。
- 聊天消息区可视高度不少于 420px。
- 候选人消息在右侧，Agent/系统操作人消息在左侧。
- 右侧 AI 综合评分、在线简历评分、离线简历评分均可展开/收起。
- 页面 body 不滚动，候选人列表、聊天消息、右侧信息面板独立滚动。
- 状态机主链一行展示，异常链默认收起。
- 当前沟通职位位于候选人信息卡右上角，并有明确标题「当前沟通职位」。

可以让 Codex 先只做这几个组件的重构：`AppLayout`、`PipelineBar`、`CandidateQueue`、`CandidateHeader`、`ChatThread`、`RightInsightPanel`。这样不会牵动业务逻辑，但视觉密度会接近你喜欢的那版。

## 15. 本仓库执行验收清单

为避免上下文丢失，后续实现必须逐项核对：

- [ ] 页面主骨架：`56px` 全局折叠侧栏 + 高密度三栏工作台。
- [ ] 顶部筛选条：一行、固定约 `48px`、控件 `32px`、字号 `12–13px`。
- [ ] 状态机链：主链一行、节点高度不超过 `38px`、异常链默认收起。
- [ ] 左侧投递记录队列：宽度 `280–300px`、数据看板入口 `48px`、不展示统计块。
- [ ] 左侧投递记录卡片：高度不超过 `76px`、最多三行信息、内部滚动。
- [ ] 中间投递人信息卡：高度不超过 `170px`、当前沟通岗位在右上角并有明确标题。
- [ ] 聊天区：消息区可视高度不少于 `420px`、输入框固定底部、消息区独立滚动。
- [ ] 消息方向：投递人消息在右侧；Agent / operator / system / recruiter 在左侧。
- [ ] 聊天 tabs 与操作按钮：同一行，行高约 `42px`。
- [ ] 右侧洞察区：AI 综合评分、在线简历评分、离线简历评分默认展开且可折叠；其余模块默认折叠。
- [ ] 滚动行为：body 不滚动，左侧队列、聊天消息、右侧面板各自滚动。
- [ ] 术语口径：用户可见文案使用投递记录 / 投递人 / 当前沟通岗位，不暴露候选人池口径。

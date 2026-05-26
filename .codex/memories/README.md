---
name: user-memories-index
description: 用户级 memories 目录结构和渐进式披露索引，区分规范类记忆和其他长期上下文。
load_when: 需要查找、添加、移动或整理用户级 memory；需要判断某条长期用户偏好或规范应放在哪个目录时加载。
not_for: 项目级规则、当前任务状态、代码实现细节、运行时事实、凭证或临时 handoff。
---

# User Memories

`~/.codex/memories/` 存放用户级长期上下文。这里的内容应保持可渐进式披露：先读索引和 metadata，只在当前任务匹配 `load_when` 时再读取正文。

## 目录约定

- `guidelines/`：用户级规范类记忆，例如开发规范、编码规范、设计规范、review 规范、测试规范、subagent 协作规范。先读该目录自己的 README，再按 metadata 加载具体规范。
- `<domain-or-product>/`：和某个长期主题、产品、工作流或领域相关的记忆。
- 其他并列目录：后续可以按需要新增，例如 `preferences/`、`workflows/`、`research/`、`integrations/`。新增前应先确认它和现有目录没有明显重叠。

## 添加规则

- 每个 memory 文件必须带 metadata：`name`、`description`、`load_when`、`not_for`。
- 文件名使用小写 kebab-case：`development-execution-guidelines.md`。
- 规范类内容优先放入 `guidelines/`。
- 不把项目级规则放进用户级 memories；项目级规则应留在项目自己的 `AGENTS.md`、`docs/`、README 或 spec 中。
- 不存放 secret、token、private key、passphrase、完整签名材料或临时运行状态。
- 不把 Markdown memory 当作产品事实源、任务状态源、验证证据或恢复状态。

## 当前索引

- [guidelines/README.md](guidelines/README.md): 用户级规范类 memory 索引，覆盖开发、编码、设计、review、测试和协作节奏等规范。

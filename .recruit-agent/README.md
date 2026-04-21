# `.recruit-agent` 统一资源根目录

本目录用于统一管理项目内面向 Agent 的项目级资源资产，是 `prompts`、`skills` 与 `plugin` 资产/配置/元数据的统一根目录。

当前收口范围：
- `prompts/`
  - `base/`：基础行为、身份、输出格式、共享补充规则
  - `tasks/`：任务级提示词
  - `scene_templates/`：共享场景模板
- `mcp/`
  - `presets/`：MCP 预置模板等文件型配置资产
- `plugins/`
  - 插件自有的资产、配置、元数据与 persona 片段
- `skills/`
  - 仓库内版本化的 skill 包

当前不收进本目录的内容：
- `services/backend/src/recruit_agent/plugins/**/*.py`
  这些仍然是 backend 中可 import 的薄运行时 shell / mount code，用于读取 `.recruit-agent/plugins/` 下资产并挂到系统底座
- `services/backend/src/recruit_agent/skills/*.py`
  这些仍然是 skill 机制代码，不是 skill 资产内容
- `services/backend/src/recruit_agent/services/mcp_registry.py`
  这里仍然是 backend 中可 import 的薄运行时 shell，用于读取 `.recruit-agent/mcp/` 下资产并维持 DB 驱动的 MCP 注册/探活流程

约束：
- 面向 LLM 的自然语言文件资源，优先放在本目录下
- 插件专属但仍属于文件型资源的内容，优先放在 `plugins/<plugin>/`
- 可版本化的项目级 skill 包，优先放在本目录下
- backend 运行时代码可以读取本目录资源，但不应把项目级 plugin 资产的事实来源重新散落回 `services/backend/src/recruit_agent/plugins/**`
- 运行时代码可以读取本目录资源，但不应继续把大段 prompt / persona 文本硬编码回 Python

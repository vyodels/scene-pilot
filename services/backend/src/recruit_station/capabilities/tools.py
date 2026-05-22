# mypy: ignore-errors
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Awaitable, Callable, Protocol, TypeVar

_T = TypeVar("_T")


class ToolExecutionError(RuntimeError):
    pass


class ToolHandler(Protocol):
    def __call__(self, arguments: dict[str, Any]) -> Any: ...


@dataclass(slots=True)
class ToolExecutionResult:
    tool_name: str
    output: Any
    is_error: bool = False
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_message_content(self) -> str:
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output, ensure_ascii=False, sort_keys=True, default=str)


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    category: str = "core"
    external_target: bool = False
    resource_target_kind: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "ToolDefinition":
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=deepcopy(self.parameters),
            handler=self.handler,
            category=self.category,
            external_target=self.external_target,
            resource_target_kind=self.resource_target_kind,
            metadata=deepcopy(self.metadata),
        )

    def to_provider_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _runtime_requires_browser_computer_scene(runtime: dict[str, Any]) -> bool:
    constraints = runtime.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    context_hints = runtime.get("context_hints")
    if not isinstance(context_hints, dict):
        context_hints = {}
    plan_kind = str(
        runtime.get("plan_kind")
        or constraints.get("plan_kind")
        or context_hints.get("plan_kind")
        or ""
    ).strip().lower()
    return plan_kind == "jd_sync"


@dataclass(slots=True)
class ToolRegistry:
    tools: dict[str, ToolDefinition] = field(default_factory=dict)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self.tools:
            raise ToolExecutionError(f"Tool already registered: {tool.name}")
        self.tools[tool.name] = tool

    def has(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def merge(self, other: "ToolRegistry") -> None:
        for tool in other.tools.values():
            self.register(tool)

    def filtered(self, predicate: Callable[[ToolDefinition], bool]) -> "ToolRegistry":
        registry = ToolRegistry()
        for tool in self.tools.values():
            if predicate(tool):
                registry.register(tool.clone())
        return registry

    def describe(
        self,
        *,
        capabilities: list[str] | None = None,
        preferred_tool_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            tool.to_provider_spec()
            for tool in self._select_tools(capabilities=capabilities, preferred_tool_names=preferred_tool_names)
        ]

    def to_agent_runtime_tools(self) -> list[Any]:
        from recruit_station.agent_runtime.types import (
            ToolCall as AgentRuntimeToolCall,
            ToolDefinition as AgentRuntimeToolDefinition,
            ToolResult as AgentRuntimeToolResult,
            ToolSchema,
            TurnContext,
        )

        registry = self

        @dataclass(slots=True)
        class _Handler:
            tool: ToolDefinition

            def normalize_call_input(
                self,
                call: AgentRuntimeToolCall,
                context: TurnContext,
            ) -> dict[str, Any]:
                return self._prepare_arguments(call, context)

            def handle(self, call: AgentRuntimeToolCall, context: TurnContext) -> AgentRuntimeToolResult:
                arguments = self._prepare_arguments(call, context)
                result = registry.execute(self.tool.name, arguments)
                content = result.output
                metadata = dict(result.metadata or {})
                if self.tool.name == "delegate_scene_context":
                    content = _project_scene_result_for_parent_context(content)
                    metadata["scene_result_projection"] = True
                return AgentRuntimeToolResult(
                    tool_call_id=call.id,
                    tool_use_id=call.tool_use_id,
                    name=call.name,
                    content=content,
                    is_error=result.is_error,
                    metadata=metadata,
                )

            def _prepare_arguments(self, call: AgentRuntimeToolCall, context: TurnContext) -> dict[str, Any]:
                arguments = dict(call.input or {})
                if self.tool.name == "delegate_scene_context":
                    from recruit_station.product_adapters.target_contracts import merge_browser_target_into_scene_arguments

                    runtime = dict(context.runtime or {})
                    arguments = merge_browser_target_into_scene_arguments(
                        arguments,
                        structured_sources=(
                            runtime,
                            runtime.get("constraints"),
                            runtime.get("context_hints"),
                        ),
                    )
                    if _runtime_requires_browser_computer_scene(runtime) and not arguments.get("preferred_capabilities"):
                        arguments["preferred_capabilities"] = ["browser", "computer"]
                    if _runtime_requires_browser_computer_scene(runtime) and not arguments.get("max_llm_invocations"):
                        arguments["max_llm_invocations"] = 20
                    if _runtime_requires_browser_computer_scene(runtime):
                        arguments = _normalize_jd_sync_scene_arguments(arguments)
                return arguments

        return [
            AgentRuntimeToolDefinition(
                name=tool.name,
                description=tool.description,
                schema=ToolSchema(
                    name=tool.name,
                    description=tool.description,
                    input_schema=deepcopy(tool.parameters),
                ),
                handler=_Handler(tool),
                metadata={
                    **deepcopy(tool.metadata),
                    "category": tool.category,
                    "external_target": tool.external_target,
                    "resource_target_kind": tool.resource_target_kind,
                },
            )
            for tool in self.tools.values()
        ]

    def capability_tool_names(self, capability: str) -> list[str]:
        normalized = capability.strip().lower()
        names: list[str] = []
        for tool in self.tools.values():
            tool_capabilities = {
                str(item).strip().lower()
                for item in list(tool.metadata.get("capabilities") or [])
                if str(item).strip()
            }
            if normalized in tool_capabilities or tool.metadata.get("terminal_result_submission"):
                names.append(tool.name)
        return names

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        return run_awaitable_blocking(lambda: self.execute_async(tool_name, arguments))

    async def execute_async(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        if tool_name not in self.tools:
            raise ToolExecutionError(f"Unknown tool: {tool_name}")
        tool = self.tools[tool_name]
        payload = dict(arguments or {})
        try:
            if tool_name == "delegate_scene_context":
                timeout_seconds = _delegate_scene_context_timeout_seconds(payload)
                output = await asyncio.wait_for(
                    asyncio.to_thread(_invoke_handler, tool.handler, payload),
                    timeout=timeout_seconds,
                )
            else:
                output = _invoke_handler(tool.handler, payload)
            if inspect.isawaitable(output):
                output = await output
            return ToolExecutionResult(
                tool_name=tool_name,
                output=output,
                is_error=False,
                arguments=payload,
                metadata=_tool_metadata(tool),
            )
        except TimeoutError as exc:
            timeout_seconds = _delegate_scene_context_timeout_seconds(payload)
            return ToolExecutionResult(
                tool_name=tool_name,
                output=(
                    "E_SCENE_TIMEOUT: delegate_scene_context did not return "
                    f"within timeoutSeconds={timeout_seconds}"
                ),
                is_error=True,
                arguments=payload,
                metadata={
                    **_tool_metadata(tool),
                    "timeout_seconds": timeout_seconds,
                    "timeout_kind": "delegate_scene_context_outer_timeout",
                },
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            return ToolExecutionResult(
                tool_name=tool_name,
                output=str(exc),
                is_error=True,
                arguments=payload,
                metadata=_tool_metadata(tool),
            )

    def build_system_command_tool(
        self,
        handler: ToolHandler,
        *,
        name: str = "request_system_command",
    ) -> ToolDefinition:
        return ToolDefinition(
            name=name,
            description="Request a whitelisted system command via desktop approval. Execution is disabled by default.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "rationale": {"type": "string"},
                    "requested_by": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            handler=handler,
            metadata={
                "requires_approval": True,
                "feature_flag": "skills.system_command",
                "execution_enabled": False,
                "capabilities": ["command", "approval"],
            },
        )

    def _select_tools(
        self,
        *,
        capabilities: list[str] | None = None,
        preferred_tool_names: list[str] | None = None,
    ) -> list[ToolDefinition]:
        if not capabilities:
            candidates = list(self.tools.values())
        else:
            normalized = {str(item).strip().lower() for item in capabilities if str(item).strip()}
            candidates: list[ToolDefinition] = []
            for tool in self.tools.values():
                tool_capabilities = {
                    str(item).strip().lower()
                    for item in list(tool.metadata.get("capabilities") or [])
                    if str(item).strip()
                }
                if not tool_capabilities or normalized & tool_capabilities or tool.metadata.get("terminal_result_submission"):
                    candidates.append(tool)

        if not preferred_tool_names:
            return candidates

        preferred = {str(item).strip() for item in preferred_tool_names if str(item).strip()}
        prioritized = [
            tool
            for tool in candidates
            if tool.name in preferred
        ]
        if not prioritized:
            return candidates
        remaining = [tool for tool in candidates if tool.name not in preferred]
        return [*prioritized, *remaining]


def register_core_tools(
    registry: ToolRegistry,
    *,
    read_memory_handler: ToolHandler | None = None,
    list_memory_files_handler: ToolHandler | None = None,
    read_memory_file_handler: ToolHandler | None = None,
    write_memory_file_handler: ToolHandler | None = None,
    delete_memory_file_handler: ToolHandler | None = None,
    record_learning_handler: ToolHandler | None = None,
) -> None:
    registry.register(
        ToolDefinition(
            name="read_memory",
            description="Read a progressive-disclosure memory index for a scope. Use read_memory_file for full markdown content.",
            parameters={
                "type": "object",
                "properties": {"scope_kind": {"type": "string"}, "scope_ref": {"type": "string"}},
                "additionalProperties": True,
            },
            handler=read_memory_handler or (lambda arguments: {"accepted": True, "action": "read_memory", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_read"], "permission_scope": "memory_read", "risk_level": "low"},
        )
    )
    memory_scope_properties = {
        "scope_kind": {"type": "string"},
        "scope_ref": {"type": "string"},
        "agent_definition_id": {"type": "string"},
    }
    registry.register(
        ToolDefinition(
            name="list_memory_files",
            description="List markdown memory files available inside a memory scope without reading full content.",
            parameters={
                "type": "object",
                "properties": memory_scope_properties,
                "required": ["scope_kind", "scope_ref"],
                "additionalProperties": True,
            },
            handler=list_memory_files_handler
            or (lambda arguments: {"accepted": True, "action": "list_memory_files", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_read"], "permission_scope": "memory_read", "risk_level": "low"},
        )
    )
    registry.register(
        ToolDefinition(
            name="read_memory_file",
            description="Read a markdown memory file inside a memory scope.",
            parameters={
                "type": "object",
                "properties": {**memory_scope_properties, "path": {"type": "string", "default": "MEMORY.md"}},
                "required": ["scope_kind", "scope_ref"],
                "additionalProperties": True,
            },
            handler=read_memory_file_handler
            or (lambda arguments: {"accepted": True, "action": "read_memory_file", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_read"], "permission_scope": "memory_read", "risk_level": "low"},
        )
    )
    registry.register(
        ToolDefinition(
            name="write_memory_file",
            description=(
                "Write or append a markdown memory file inside a memory scope. "
                "Use this only for durable user-requested memories or memory maintenance."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **memory_scope_properties,
                    "path": {"type": "string", "default": "MEMORY.md"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
                },
                "required": ["scope_kind", "scope_ref", "content"],
                "additionalProperties": True,
            },
            handler=write_memory_file_handler
            or (lambda arguments: {"accepted": True, "action": "write_memory_file", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_write"], "permission_scope": "memory_write", "risk_level": "medium"},
        )
    )
    registry.register(
        ToolDefinition(
            name="delete_memory_file",
            description="Delete a markdown memory file inside a memory scope when the user asks to forget it.",
            parameters={
                "type": "object",
                "properties": {**memory_scope_properties, "path": {"type": "string"}},
                "required": ["scope_kind", "scope_ref", "path"],
                "additionalProperties": True,
            },
            handler=delete_memory_file_handler
            or (lambda arguments: {"accepted": True, "action": "delete_memory_file", "arguments": arguments}),
            category="memory",
            external_target=False,
            resource_target_kind="memory",
            metadata={"capabilities": ["memory", "memory_write"], "permission_scope": "memory_write", "risk_level": "medium"},
        )
    )
    registry.register(
        ToolDefinition(
            name="record_learning",
            description="Record a learning candidate for evolution.",
            parameters={
                "type": "object",
                "properties": {"kind": {"type": "string"}, "payload": {"type": "object"}},
                "additionalProperties": True,
            },
            handler=record_learning_handler or (lambda arguments: {"accepted": True, "action": "record_learning", "arguments": arguments}),
            category="learning",
            external_target=False,
            resource_target_kind="learning",
        )
    )
    registry.register(
        ToolDefinition(
            name="enqueue_follow_up",
            description="Schedule a follow up task for later execution.",
            parameters={
                "type": "object",
                "properties": {"task_type": {"type": "string"}, "payload": {"type": "object"}},
                "additionalProperties": True,
            },
            handler=lambda arguments: {"accepted": True, "action": "enqueue_follow_up", "arguments": arguments},
            category="core",
            external_target=False,
            resource_target_kind="queue",
        )
    )
    registry.register(
        ToolDefinition(
            name="schedule_self_wakeup",
            description="Request a future wakeup for the current run.",
            parameters={
                "type": "object",
                "properties": {"delay_seconds": {"type": "integer"}, "reason": {"type": "string"}},
                "additionalProperties": True,
            },
            handler=lambda arguments: {"accepted": True, "action": "schedule_self_wakeup", "arguments": arguments},
            category="core",
            external_target=False,
            resource_target_kind="run",
        )
    )


def tool_capabilities(tool: ToolDefinition) -> set[str]:
    return {
        str(item).strip().lower()
        for item in list(tool.metadata.get("capabilities") or [])
        if str(item).strip()
    }


def is_approval_tool(tool: ToolDefinition) -> bool:
    capabilities = tool_capabilities(tool)
    return "approval" in capabilities or bool(tool.metadata.get("requires_confirmation"))


def is_scene_context_tool(tool: ToolDefinition) -> bool:
    capabilities = tool_capabilities(tool)
    if "scene" in capabilities:
        return True
    if not (
        tool.external_target
        or bool(tool.metadata.get("external_tool"))
        or bool(tool.metadata.get("real_environment"))
    ):
        return False
    return bool(capabilities & {"browser", "document", "search", "computer", "computer_read", "computer_write"})


def build_delegate_scene_context_tool(
    handler: ToolHandler,
    *,
    name: str = "delegate_scene_context",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=(
            "Delegate a capability-oriented runtime scene task to an isolated scene context and return a structured scene result. "
            "For multi-step site tasks, completed means the full requested scene goal is complete. "
            "Partial progress with blockers, limitations, or remaining required steps must be treated as blocked/continuable, not as terminal success."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "instruction": {"type": "string"},
                "success_criteria": {"type": "object"},
                "output_contract": {
                    "type": "object",
                    "description": "Expected structured result. Put artifact_expectations here when local files matter; browser-triggered downloads should use local_download_create_attempt before HID and local_download_attribute after HID/browser observation before business path/format verification. A completed local attribution record with file_path/file_name is valid path evidence; timeout or ambiguous is not. If a download affordance is selected, preserve browser-derived sourceUrl/href, expected filename, finalUrl/referrer hints, and startedAt when available. When a local artifact is located, return it in result_data.artifact plus result_data.download_attribution and include business_writeback arguments suitable for the later business tool such as attach_resume_artifact.",
                },
                "preferred_capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "environment_requirements": {
                    "type": "object",
                    "description": "Scene prerequisites and stable targets such as browser_target, computer_target, target_regions, and action_plan. Put these as structured fields here instead of embedding pseudo-JSON in instruction prose.",
                },
                "browser_target": {
                    "type": "object",
                    "description": "Optional top-level shortcut for the browser target; equivalent to environment_requirements.browser_target. When the operator instruction or current contract includes an explicit web target URL, preserve it here as browser_target.url and derive host from that URL/browser evidence so stale tabs on a different origin are rejected. The URL is an entrypoint hint; only its full origin is the hard boundary, and same-origin paths may change during the workflow.",
                },
                "computer_target": {
                    "type": "object",
                    "description": "Optional top-level shortcut for the computer/HID target; equivalent to environment_requirements.computer_target.",
                },
                "target_regions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional top-level shortcut for candidate landing regions; equivalent to environment_requirements.target_regions.",
                },
                "action_plan": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional top-level shortcut for intent-level scene actions; equivalent to environment_requirements.action_plan. Download actions may include download_source with source_url/sourceUrl/href, expected_filename/fileName/download, started_at/startedAt, final_url/finalUrl, or referrer fields copied from browser evidence.",
                },
                "artifact_expectations": {
                    "type": "object",
                    "description": "Optional top-level shortcut for artifact expectations; equivalent to output_contract.artifact_expectations. For browser downloads, include download_attribution/source_url/expected_filename/started_at when available so the local watcher can correlate a newly created file with the clicked link.",
                },
                "anti_detection_policy": {
                    "type": "object",
                    "description": "Generic human-paced execution policy. Do not use this for site-specific selectors, site workflow branches, JS stealth, or fingerprinting logic.",
                },
                "behavior_budget": {
                    "type": "object",
                    "description": "Generic account/run behavior budget such as candidate rate, page dwell, HID action cap, and retry backoff.",
                },
                "approval_policy": {"type": "object"},
                "input": {"type": "object"},
                "context": {
                    "type": "object",
                    "description": "Episode-scoped scene context, including browser/computer targets, candidate landing regions, action intent, and artifact_expectations. Use structured fields, not site-specific hardcoded flow.",
                },
                "requested_by": {"type": "string"},
                "max_llm_invocations": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional explicit safety budget for this delegated scene. Only set it when the operator/test request explicitly provides a finite budget; otherwise omit it so the scene runs until terminal outcome, cancellation, or human boundary.",
                },
            },
            "required": ["instruction"],
            "additionalProperties": True,
        },
        handler=handler,
        category="scene",
        external_target=False,
        resource_target_kind="execution_episode",
        metadata={"capabilities": ["scene", "scene_delegate"]},
    )


def _normalize_jd_sync_scene_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments or {})
    normalized["instruction"] = _JD_SYNC_SCENE_INSTRUCTION
    normalized["output_contract"] = _merge_dicts(
        _jd_sync_scene_output_contract(),
        _as_dict(normalized.get("output_contract")),
    )
    context = _as_dict(normalized.get("context"))
    context["prompt_policy"] = {
        **_as_dict(context.get("prompt_policy")),
        "instruction_is_rule_only": True,
        "do_not_embed_observed_counts_or_job_names_in_future_prompts": True,
        "progress_must_be_returned_as_structured_result_data": True,
    }
    normalized["context"] = context
    return normalized


_JD_SYNC_SCENE_INSTRUCTION = (
    "执行招聘站点 JD 同步 scene。规则：从当前同源招聘网页出发，使用 browser 观察和 computer/HID 页面内操作，"
    "基于页面可见导航发现职位列表并逐个进入职位详情；列表摘要、职位数量或候选人概况不能作为职位详情完成证据。"
    "如果列表页文本、计数器或 snapshot/clickables 表明有 N 个招聘中岗位，必须把 N 当作本轮最小发现数量；"
    "即使部分“查看职位详情”链接 inViewport=false，也必须先用 HID 滚动让该入口进入 viewport，再重新观察并点击，不能跳过。"
    "每个完成详情必须同时具备当前目标 host 的详情 URL、详情页标题/职位名、职责和要求等页面证据；"
    "不得把旧页面、其他端口、历史摘要或模型推断中的职位名当作当前站点证据。"
    "不得处理请求目标之外的业务域、业务实体或业务流程；不得主动聚焦浏览器地址栏、输入 URL 或粘贴 URL。"
    "如果误入目标之外的业务页面，只能用页面内导航返回请求目标所需的页面。"
    "遇到可恢复的点击、滚动、返回、前台窗口、光标/按键或短暂执行异常时，应重新观察并改用页面内可见入口继续；"
    "只有登录、验证码、权限、必要执行工具缺失或目标站点不可达才可返回硬阻塞。"
    "返回必须遵守 output_contract：把本次实际观察到的职位发现、完整详情、未完成项、下架/关闭线索和生效入口线索写入结构化 result_data。"
    "不要把历史摘要中的具体职位名、数量、比例或推断进度写进 instruction 或自然语言结论；具体进度只允许出现在结构化字段中。"
    "若已发现岗位数量大于已完成详情数量，或仍有 offscreen 详情入口未进入详情页读取，status 必须是 partial/blocked，不能 completed。"
)


def _jd_sync_scene_output_contract() -> dict[str, Any]:
    return {
        "format": "json",
        "result_data_required": True,
        "status_values": ["completed", "partial", "blocked"],
        "required_fields": [
            "status",
            "observed_jobs",
            "completed_job_details",
            "inactive_or_closed_jobs",
            "activation_entry_observed",
            "blockers",
            "limitations",
            "evidence",
        ],
        "field_contract": {
            "observed_jobs": "Jobs actually observed in this scene turn; use stable current-host page-visible identifiers when available. If the list shows a total count, observed_jobs must account for every listed/open job, including entries below the viewport.",
            "completed_job_details": "Only jobs whose current-host detail page was opened/read in this scene turn or whose full detail evidence is present. Each item must include title, department, location, status, external_id or external_url, summary/description, requirements when visible, and detail evidence from the current detail URL.",
            "inactive_or_closed_jobs": "Jobs observed as inactive, closed, unavailable, or removed.",
            "activation_entry_observed": "Whether the scene observed a page entry for choosing active/effective JD.",
            "blockers": "Hard blockers only: login, captcha, permission, missing required tools, or unreachable target site.",
            "limitations": "Recoverable or incomplete conditions; include any offscreen details not yet opened and any mismatch between listed open jobs and completed detail pages.",
            "evidence": "Short current-host evidence references or page facts that justify each completed job detail.",
        },
        "completion_rule": (
            "status may be completed only when the scene has returned all currently required complete JD details in completed_job_details "
            "and no required detail is missing. If only list summaries, partial details, offscreen links, stale-host evidence, or inferred jobs are available, status must be partial or blocked."
        ),
    }


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in dict(override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _project_scene_result_for_parent_context(output: Any) -> Any:
    if not isinstance(output, dict):
        return output
    evidence_refs = _scene_evidence_refs(output)
    business_result = _scene_business_result(output)
    coverage = _project_scene_coverage(business_result)
    projection = {
        "status": output.get("status"),
        "business_result": business_result,
        **coverage,
        "blockers": _project_scene_blockers(output.get("blockers")),
        "evidence_refs": evidence_refs,
        "projection": {
            "kind": "scene_result_summary",
            "raw_scene_context_stored": True,
            "raw_scene_context_access": "Use evidence_refs to inspect ExecutionEpisode, EnvironmentSnapshot, and runtime events when debugging or distilling skills.",
        },
    }
    return {key: value for key, value in projection.items() if value not in (None, [], {})}


def _scene_business_result(output: dict[str, Any]) -> dict[str, Any]:
    result_data = _as_dict(output.get("result_data"))
    if result_data:
        return result_data
    current_progress = _as_dict(output.get("current_progress"))
    if current_progress:
        return current_progress
    progress = _as_dict(output.get("progress"))
    if progress:
        return progress
    real_progress = _as_dict(output.get("real_progress"))
    if real_progress:
        return real_progress
    return output


def _project_scene_coverage(result: dict[str, Any]) -> dict[str, Any]:
    observed = _list_of_dicts_for_projection(
        result.get("observed_jobs") or result.get("jobs") or result.get("discovered_jobs")
    )
    observed_titles = _scene_title_list(
        observed
        or result.get("job_titles_discovered")
        or result.get("confirmed_from_latest_observation")
        or result.get("still_hiring_jobs")
    )
    completed = _list_of_dicts_for_projection(
        result.get("completed_job_details")
        or result.get("fully_read_jobs")
        or result.get("verified_job_details")
        or result.get("completed_jobs")
        or result.get("verified_jobs")
        or result.get("confirmed_jobs")
    )
    remaining = _scene_title_list(
        result.get("remaining_targets")
        or result.get("remaining_jobs")
        or result.get("remaining_jobs_to_open")
        or result.get("remaining_jobs_to_process")
        or result.get("remaining_job_titles")
        or result.get("unfinished_jobs")
        or result.get("pending_jobs")
        or result.get("unread_details")
    )
    completed_titles = _scene_title_list(
        completed
        or result.get("previous_detail_verification_already_completed")
        or result.get("detail_pages_verified")
    )
    if not remaining and observed_titles:
        completed_key = {item.strip().lower() for item in completed_titles}
        remaining = [
            title
            for title in observed_titles
            if title.strip().lower() not in completed_key
        ]
    coverage: dict[str, Any] = {}
    if observed_titles or completed:
        coverage["coverage"] = {
            "observed_count": len(observed_titles),
            "completed_detail_count": len(completed),
            "remaining_count": len(remaining),
        }
    if remaining:
        coverage["remaining_targets"] = remaining
    if completed_titles:
        coverage["already_verified"] = completed_titles
    if remaining:
        coverage["must_continue"] = True
    if _scene_coverage_schema_incomplete(result=result, observed=observed, completed=completed):
        coverage["must_continue"] = True
        coverage["coverage_schema_incomplete"] = True
    return coverage


def _scene_coverage_schema_incomplete(
    *,
    result: dict[str, Any],
    observed: list[dict[str, Any]],
    completed: list[dict[str, Any]],
) -> bool:
    if observed or result.get("remaining_targets") or result.get("remaining_jobs"):
        return False
    if result.get("verified_jobs") or result.get("verified_jobs_total"):
        return True
    if completed and not (
        result.get("observed_jobs")
        or result.get("jobs")
        or result.get("discovered_jobs")
    ):
        return True
    return False


def _list_of_dicts_for_projection(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _scene_title_list(value: Any) -> list[str]:
    raw_items: list[Any]
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, dict):
        raw_items = list(value.values())
    elif value in (None, ""):
        raw_items = []
    else:
        raw_items = [value]
    titles: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if isinstance(item, dict):
            raw_title = (
                item.get("title")
                or item.get("job_title")
                or item.get("name")
                or item.get("external_id")
                or item.get("external_url")
            )
        else:
            raw_title = item
        title = str(raw_title or "").strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def _scene_evidence_refs(output: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    episode_id = str(output.get("episode_id") or "").strip()
    if episode_id:
        refs.append({"kind": "execution_episode", "id": episode_id})
    for artifact in output.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        kind = str(artifact.get("kind") or "").strip()
        ref_id = str(
            artifact.get("snapshot_id")
            or artifact.get("episode_id")
            or artifact.get("artifact_id")
            or artifact.get("id")
            or ""
        ).strip()
        if kind and ref_id:
            refs.append({"kind": kind, "id": ref_id})
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (str(ref["kind"]), str(ref["id"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _project_scene_blockers(value: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in value or []:
        if isinstance(item, dict):
            projected = {
                key: item.get(key)
                for key in ("kind", "status", "message", "reason", "code")
                if item.get(key) not in (None, "", [], {})
            }
            blockers.append(projected or {"message": str(item)})
        elif str(item or "").strip():
            blockers.append({"message": str(item)})
    return blockers


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _tool_metadata(tool: ToolDefinition) -> dict[str, Any]:
    metadata = dict(tool.metadata or {})
    metadata.setdefault("category", tool.category)
    metadata.setdefault("external_target", tool.external_target)
    metadata.setdefault("resource_target_kind", tool.resource_target_kind)
    return metadata


def _invoke_handler(
    handler: ToolHandler,
    arguments: dict[str, Any],
) -> Any:
    return handler(arguments)


def _delegate_scene_context_timeout_seconds(arguments: dict[str, Any]) -> int:
    raw_timeout = (
        arguments.get("turn_timeout_seconds")
        or arguments.get("turnTimeoutSeconds")
        or arguments.get("timeout_seconds")
        or arguments.get("timeoutSeconds")
    )
    try:
        if raw_timeout is not None:
            return max(int(raw_timeout), 1)
    except (TypeError, ValueError):
        pass
    return 420


def run_awaitable_blocking(factory: Callable[[], Awaitable[_T]]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    # Nested scene execution can enter synchronous runtime code while an event
    # loop is already active. Run the coroutine on an isolated loop instead of
    # calling asyncio.run() recursively in the same thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()

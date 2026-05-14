import React, { useEffect, useState } from "react";
import { FormButton, FormCheckbox, FormField, FormInput, StatusBadge } from "../../components";
import { apiClient } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { ProviderConfig, ProviderHealthcheckResult, SettingsSnapshot } from "../../lib/types";

interface SettingsViewProps {
  settings: SettingsSnapshot;
  saving?: boolean;
  onSave(settings: Partial<SettingsSnapshot>): Promise<void> | void;
}

type SettingsSection = "models" | "profile";

type ProviderCheckState = {
  running?: boolean;
  result?: ProviderHealthcheckResult;
};

const defaultProfile = {
  nickname: "招聘方",
  avatarUrl: null,
};

function providerHostExample(kind: ProviderConfig["kind"]): { example: string; noteEn: string; noteZh: string } {
  if (kind === "anthropic") {
    return {
      example: "https://api.anthropic.com",
      noteEn: "Host only. Do not append `/v1/messages`.",
      noteZh: "只填写 host，不要追加 `/v1/messages`。",
    };
  }
  return {
    example: "https://api.openai.com/v1",
    noteEn: "Use a base path such as `/v1`; do not append `/responses` or `/chat/completions`.",
    noteZh: "填写基础路径，例如 `/v1`；不要追加 `/responses` 或 `/chat/completions`。",
  };
}

function providerLabel(provider: ProviderConfig): string {
  if (provider.kind === "anthropic") {
    return "Anthropic";
  }
  return "OpenAI Compatible";
}

function healthTone(result?: ProviderHealthcheckResult): "positive" | "critical" | "neutral" | "warning" {
  if (!result) {
    return "neutral";
  }
  return result.ok ? "positive" : "critical";
}

export function SettingsView({ settings, saving, onSave }: SettingsViewProps): JSX.Element {
  const { copy } = useI18n();
  const [draft, setDraft] = useState(settings);
  const [activeSection, setActiveSection] = useState<SettingsSection>("models");
  const [checkStates, setCheckStates] = useState<Record<string, ProviderCheckState>>({});
  const [saveMessage, setSaveMessage] = useState<string>();
  const [avatarError, setAvatarError] = useState<string>();

  const isDirty = JSON.stringify(draft.providers) !== JSON.stringify(settings.providers) ||
    JSON.stringify(draft.userProfile ?? defaultProfile) !== JSON.stringify(settings.userProfile ?? defaultProfile);

  useEffect(() => {
    if (!isDirty) {
      setDraft(settings);
    }
  }, [isDirty, settings]);

  const profile = draft.userProfile ?? defaultProfile;

  const updateProvider = (index: number, patch: Partial<ProviderConfig>) => {
    setDraft((current) => ({
      ...current,
      providers: current.providers.map((provider, providerIndex) =>
        providerIndex === index ? { ...provider, ...patch } : provider,
      ),
    }));
    setCheckStates((current) => ({ ...current, [String(index)]: {} }));
  };

  const updateProfile = (patch: Partial<SettingsSnapshot["userProfile"]>) => {
    setAvatarError(undefined);
    setDraft((current) => ({
      ...current,
      userProfile: {
        ...(current.userProfile ?? defaultProfile),
        ...patch,
      },
    }));
  };

  const useAvatarFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setAvatarError(copy("Please choose an image file.", "请选择图片文件。"));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === "string" ? reader.result : "";
      if (!value) {
        setAvatarError(copy("Could not read the selected image.", "无法读取所选图片。"));
        return;
      }
      updateProfile({ avatarUrl: value });
    };
    reader.onerror = () => setAvatarError(copy("Could not read the selected image.", "无法读取所选图片。"));
    reader.readAsDataURL(file);
  };

  const saveSettings = async () => {
    setSaveMessage(undefined);
    await onSave({
      providers: draft.providers,
      userProfile: draft.userProfile ?? defaultProfile,
    });
    setSaveMessage(copy("Settings saved.", "设置已保存。"));
  };

  const checkProvider = async (provider: ProviderConfig, index: number) => {
    const key = String(index);
    setCheckStates((current) => ({ ...current, [key]: { running: true } }));
    try {
      const result = await apiClient.checkProvider(provider);
      setCheckStates((current) => ({ ...current, [key]: { running: false, result } }));
    } catch (error) {
      setCheckStates((current) => ({
        ...current,
        [key]: {
          running: false,
          result: {
            ok: false,
            status: "failed",
            message: error instanceof Error ? error.message : copy("Provider check failed.", "模型探活失败。"),
          },
        },
      }));
    }
  };

  return (
    <div className="settings-console">
      <div className="settings-console__nav" role="tablist" aria-label={copy("Settings sections", "设置分区")}>
        {[
          { key: "models" as const, label: copy("Model endpoints", "模型接口"), detail: copy("Keys, base URLs, timeouts, health checks", "密钥、地址、超时与探活") },
          { key: "profile" as const, label: copy("Operator profile", "使用者个人信息"), detail: copy("Nickname and avatar in IM", "IM 展示昵称与头像") },
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={activeSection === item.key}
            className="settings-console__nav-item"
            data-active={activeSection === item.key ? "true" : undefined}
            onClick={() => setActiveSection(item.key)}
          >
            <strong>{item.label}</strong>
            <span>{item.detail}</span>
          </button>
        ))}
      </div>

      <main className="settings-console__body">
        {activeSection === "models" ? (
          <section className="settings-panel" aria-labelledby="settings-models-title">
            <header className="settings-panel__header">
              <div>
                <h2 id="settings-models-title">{copy("Model endpoints", "模型接口")}</h2>
                <p>{copy("Keep one primary endpoint enabled. Health checks send a tiny live request with the current model and credentials.", "保持一个主接口启用。探活会使用当前模型和密钥发送一次小型真实请求。")}</p>
              </div>
              <FormButton type="button" variant="primary" onClick={saveSettings} disabled={saving || !isDirty}>
                {saving ? copy("Saving...", "保存中...") : copy("Save changes", "保存更改")}
              </FormButton>
            </header>

            <div className="settings-provider-table">
              <div className="settings-provider-table__head" aria-hidden="true">
                <span>{copy("Provider", "接口")}</span>
                <span>{copy("Model", "模型")}</span>
                <span>{copy("Base URL", "Base URL")}</span>
                <span>{copy("Timeout", "超时")}</span>
                <span>{copy("Credential", "密钥")}</span>
                <span>{copy("Status", "状态")}</span>
              </div>

              {draft.providers.map((provider, index) => {
                const hint = providerHostExample(provider.kind);
                const checkState = checkStates[String(index)];
                const result = checkState?.result;
                return (
                  <article key={`${provider.kind}-${provider.name}`} className="settings-provider-table__row">
                    <div className="settings-provider-cell settings-provider-cell--identity">
                      <label className="settings-provider-toggle">
                        <FormCheckbox
                          type="checkbox"
                          name={`provider-${index}-enabled`}
                          checked={provider.enabled}
                          onChange={(event) => updateProvider(index, { enabled: event.target.checked })}
                        />
                        <span>
                          <strong>{providerLabel(provider)}</strong>
                          <em>{provider.name}</em>
                        </span>
                      </label>
                    </div>

                    <FormField label={copy("Model", "模型")}>
                      <FormInput
                        type="text"
                        name={`provider-${index}-model`}
                        value={provider.model}
                        onChange={(event) => updateProvider(index, { model: event.target.value })}
                        placeholder={provider.kind === "anthropic" ? "claude-sonnet-4" : "gpt-5.4"}
                      />
                    </FormField>

                    <FormField label={copy("Base URL", "Base URL")}>
                      <FormInput
                        type="url"
                        name={`provider-${index}-baseUrl`}
                        value={provider.baseUrl ?? ""}
                        onChange={(event) => updateProvider(index, { baseUrl: event.target.value })}
                        placeholder={hint.example}
                        autoComplete="url"
                      />
                      <span className="settings-field-hint">{copy(hint.noteEn, hint.noteZh)}</span>
                    </FormField>

                    <FormField label={copy("Timeout seconds", "响应等待秒数")}>
                      <FormInput
                        type="number"
                        name={`provider-${index}-timeoutSeconds`}
                        min={1}
                        step={1}
                        value={provider.timeoutSeconds}
                        onChange={(event) =>
                          updateProvider(index, {
                            timeoutSeconds: Math.max(1, Number(event.target.value || provider.timeoutSeconds || 180)),
                          })
                        }
                      />
                    </FormField>

                    <FormField label={copy("API key", "访问密钥")}>
                      <FormInput
                        type="password"
                        name={`provider-${index}-apiKey`}
                        value={provider.apiKey ?? ""}
                        onChange={(event) => updateProvider(index, { apiKey: event.target.value })}
                        placeholder={provider.kind === "anthropic" ? "sk-ant-..." : "sk-..."}
                        autoComplete="new-password"
                      />
                    </FormField>

                    <div className="settings-provider-cell settings-provider-cell--status">
                      <StatusBadge tone={healthTone(result)}>
                        {checkState?.running
                          ? copy("Checking", "检测中")
                          : result
                            ? result.ok
                              ? copy("Healthy", "畅通")
                              : copy("Failed", "失败")
                            : copy("Not checked", "未检测")}
                      </StatusBadge>
                      {result?.latencyMs != null ? <span>{result.latencyMs} ms</span> : null}
                      {result?.message ? <em>{result.message}</em> : null}
                      <FormButton
                        type="button"
                        onClick={() => void checkProvider(provider, index)}
                        disabled={checkState?.running}
                      >
                        {checkState?.running ? copy("Checking...", "检测中...") : copy("Test", "探活检测")}
                      </FormButton>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ) : (
          <section className="settings-panel settings-panel--profile" aria-labelledby="settings-profile-title">
            <header className="settings-panel__header">
              <div>
                <h2 id="settings-profile-title">{copy("Operator profile", "使用者个人信息")}</h2>
                <p>{copy("This identity is used for recruiter-side bubbles in candidate IM conversations.", "这组身份会用于投递记录 IM 沟通里的招聘方消息气泡。")}</p>
              </div>
              <FormButton type="button" variant="primary" onClick={saveSettings} disabled={saving || !isDirty}>
                {saving ? copy("Saving...", "保存中...") : copy("Save changes", "保存更改")}
              </FormButton>
            </header>

            <div className="settings-profile-grid">
              <div className="settings-profile-preview">
                <div className="settings-profile-avatar">
                  {profile.avatarUrl ? <img src={profile.avatarUrl} alt="" /> : <span>{Array.from(profile.nickname || "招")[0]}</span>}
                </div>
                <div>
                  <strong>{profile.nickname || copy("Recruiter", "招聘方")}</strong>
                  <span>{copy("Recruiter side identity", "招聘方展示身份")}</span>
                </div>
              </div>

              <div className="settings-profile-form">
                <FormField label={copy("Nickname", "昵称")}>
                  <FormInput
                    type="text"
                    name="operatorNickname"
                    value={profile.nickname}
                    onChange={(event) => updateProfile({ nickname: event.target.value })}
                    autoComplete="name"
                  />
                </FormField>
                <FormField label={copy("Avatar", "头像")}>
                  <FormInput
                    type="url"
                    name="operatorAvatarUrl"
                    value={profile.avatarUrl ?? ""}
                    onChange={(event) => updateProfile({ avatarUrl: event.target.value || null })}
                    placeholder={copy("Image URL or uploaded image data", "图片 URL 或已上传图片数据")}
                    autoComplete="url"
                  />
                  <div className="settings-avatar-actions">
                    <label className="form-button settings-avatar-upload">
                      <input type="file" accept="image/*" name="operatorAvatarFile" onChange={useAvatarFile} />
                      {copy("Upload image", "上传图片")}
                    </label>
                    <FormButton type="button" onClick={() => updateProfile({ avatarUrl: null })} disabled={!profile.avatarUrl}>
                      {copy("Clear", "清除")}
                    </FormButton>
                  </div>
                  {avatarError ? <span className="settings-field-error">{avatarError}</span> : null}
                  <span className="settings-field-hint">
                    {copy("Use a local image file or paste an image URL. Leave empty to use the first character of the nickname.", "可上传本地图片，也可粘贴图片 URL。留空时使用昵称首字作为头像。")}
                  </span>
                </FormField>
              </div>
            </div>
          </section>
        )}
      </main>

      {saveMessage ? <div className="settings-console__toast" role="status">{saveMessage}</div> : null}
    </div>
  );
}

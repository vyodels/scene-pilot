import { DesktopWorkspace } from "./features/workspace/DesktopWorkspace";
import { ChatOverlayProvider } from "./features/chat-overlay";
import { I18nProvider } from "./lib/i18n";

export function App() {
  return (
    <I18nProvider>
      <ChatOverlayProvider>
        <DesktopWorkspace />
      </ChatOverlayProvider>
    </I18nProvider>
  );
}

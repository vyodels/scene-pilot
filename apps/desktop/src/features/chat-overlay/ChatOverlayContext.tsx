import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { AgentKind, ChatOverlayPanelKey } from "../../lib/types";

interface BubblePosition {
  x: number;
  y: number;
}

interface OverlayRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface ChatOverlayOpenOptions {
  agentKind?: AgentKind;
  panel?: ChatOverlayPanelKey;
}

interface ChatOverlayContextValue {
  isOpen: boolean;
  activeAgent: AgentKind;
  activePanel: ChatOverlayPanelKey;
  bubblePosition: BubblePosition;
  overlayRect: OverlayRect;
  open(options?: ChatOverlayOpenOptions): void;
  close(): void;
  toggle(options?: ChatOverlayOpenOptions): void;
  focusAgent(agentKind: AgentKind, panel?: ChatOverlayPanelKey): void;
  setActivePanel(panel: ChatOverlayPanelKey): void;
  setBubblePosition(position: BubblePosition): void;
  setOverlayRect(rect: OverlayRect): void;
}

const bubbleStorageKey = "scene-pilot.chat-bubble-position";
const overlayStorageKey = "scene-pilot.chat-overlay-rect";

const ChatOverlayContext = createContext<ChatOverlayContextValue | null>(null);

function defaultBubblePosition(): BubblePosition {
  if (typeof window === "undefined") {
    return { x: 24, y: 24 };
  }
  return {
    x: Math.max(24, window.innerWidth - 80),
    y: Math.max(24, window.innerHeight - 80),
  };
}

function defaultOverlayRect(): OverlayRect {
  if (typeof window === "undefined") {
    return { x: 120, y: 72, width: 960, height: 720 };
  }
  const width = Math.min(960, window.innerWidth - 120);
  const height = Math.min(720, window.innerHeight - 120);
  return {
    x: Math.max(88, window.innerWidth - width - 48),
    y: Math.max(64, window.innerHeight - height - 88),
    width,
    height,
  };
}

function clampBubblePosition(position: BubblePosition): BubblePosition {
  if (typeof window === "undefined") {
    return position;
  }
  return {
    x: Math.min(Math.max(16, position.x), window.innerWidth - 72),
    y: Math.min(Math.max(16, position.y), window.innerHeight - 72),
  };
}

function clampOverlayRect(rect: OverlayRect): OverlayRect {
  if (typeof window === "undefined") {
    return rect;
  }
  const width = Math.min(Math.max(760, rect.width), window.innerWidth - 40);
  const height = Math.min(Math.max(520, rect.height), window.innerHeight - 40);
  return {
    x: Math.min(Math.max(20, rect.x), window.innerWidth - width - 20),
    y: Math.min(Math.max(20, rect.y), window.innerHeight - height - 20),
    width,
    height,
  };
}

function readStoredBubblePosition(): BubblePosition {
  if (typeof window === "undefined") {
    return defaultBubblePosition();
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(bubbleStorageKey) ?? "null") as BubblePosition | null;
    return parsed ? clampBubblePosition(parsed) : defaultBubblePosition();
  } catch {
    return defaultBubblePosition();
  }
}

function readStoredOverlayRect(): OverlayRect {
  if (typeof window === "undefined") {
    return defaultOverlayRect();
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(overlayStorageKey) ?? "null") as OverlayRect | null;
    return parsed ? clampOverlayRect(parsed) : defaultOverlayRect();
  } catch {
    return defaultOverlayRect();
  }
}

export function ChatOverlayProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const [activeAgent, setActiveAgent] = useState<AgentKind>("assistant");
  const [activePanel, setActivePanel] = useState<ChatOverlayPanelKey>("conversation");
  const [bubblePosition, setBubblePositionState] = useState<BubblePosition>(() => readStoredBubblePosition());
  const [overlayRect, setOverlayRectState] = useState<OverlayRect>(() => readStoredOverlayRect());

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(bubbleStorageKey, JSON.stringify(bubblePosition));
  }, [bubblePosition]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(overlayStorageKey, JSON.stringify(overlayRect));
  }, [overlayRect]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onResize = () => {
      setBubblePositionState((current) => clampBubblePosition(current));
      setOverlayRectState((current) => clampOverlayRect(current));
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const value = useMemo<ChatOverlayContextValue>(
    () => ({
      isOpen,
      activeAgent,
      activePanel,
      bubblePosition,
      overlayRect,
      open(options) {
        if (options?.agentKind) {
          setActiveAgent(options.agentKind);
        }
        if (options?.panel) {
          setActivePanel(options.panel);
        }
        setIsOpen(true);
      },
      close() {
        setIsOpen(false);
      },
      toggle(options) {
        if (!isOpen) {
          if (options?.agentKind) {
            setActiveAgent(options.agentKind);
          }
          if (options?.panel) {
            setActivePanel(options.panel);
          }
        }
        setIsOpen((current) => !current);
      },
      focusAgent(agentKind, panel) {
        setActiveAgent(agentKind);
        if (panel) {
          setActivePanel(panel);
        }
        setIsOpen(true);
      },
      setActivePanel,
      setBubblePosition(position) {
        setBubblePositionState(clampBubblePosition(position));
      },
      setOverlayRect(rect) {
        setOverlayRectState(clampOverlayRect(rect));
      },
    }),
    [activeAgent, activePanel, bubblePosition, isOpen, overlayRect],
  );

  return <ChatOverlayContext.Provider value={value}>{children}</ChatOverlayContext.Provider>;
}

export function useChatOverlay(): ChatOverlayContextValue {
  const context = useContext(ChatOverlayContext);
  if (!context) {
    throw new Error("useChatOverlay must be used within ChatOverlayProvider");
  }
  return context;
}

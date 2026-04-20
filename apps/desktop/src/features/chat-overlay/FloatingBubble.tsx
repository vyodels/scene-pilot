import React, { useRef } from "react";
import { useChatOverlay } from "./ChatOverlayContext";
import type { AgentSnapshot } from "../../lib/types";

interface FloatingBubbleProps {
  status: AgentSnapshot["status"];
  pendingCount?: number;
}

export function FloatingBubble({ status, pendingCount = 0 }: FloatingBubbleProps): JSX.Element {
  const { bubblePosition, isOpen, toggle, setBubblePosition } = useChatOverlay();
  const dragRef = useRef<{
    pointerX: number;
    pointerY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);

  const startDrag = (event: React.MouseEvent<HTMLButtonElement>) => {
    dragRef.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      originX: bubblePosition.x,
      originY: bubblePosition.y,
      moved: false,
    };

    const handleMove = (moveEvent: MouseEvent) => {
      const current = dragRef.current;
      if (!current) {
        return;
      }
      const nextPosition = {
        x: current.originX + moveEvent.clientX - current.pointerX,
        y: current.originY + moveEvent.clientY - current.pointerY,
      };
      const moved =
        Math.abs(moveEvent.clientX - current.pointerX) > 4 ||
        Math.abs(moveEvent.clientY - current.pointerY) > 4;
      dragRef.current = {
        ...current,
        moved,
      };
      setBubblePosition(nextPosition);
    };

    const handleUp = () => {
      const current = dragRef.current;
      dragRef.current = null;
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
      if (!current?.moved) {
        toggle();
      }
    };

    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  };

  return (
    <button
      type="button"
      className="chat-bubble"
      data-status={status}
      data-open={isOpen ? "true" : undefined}
      aria-label="Open agent overlay"
      style={{
        left: `${bubblePosition.x}px`,
        top: `${bubblePosition.y}px`,
      }}
      onMouseDown={startDrag}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggle();
        }
      }}
    >
      <span className="chat-bubble__halo" aria-hidden="true" />
      <span className="chat-bubble__label">RA</span>
      <span className="chat-bubble__status" aria-hidden="true" />
      {pendingCount > 0 ? <span className="chat-bubble__count">{pendingCount > 9 ? "9+" : pendingCount}</span> : null}
    </button>
  );
}

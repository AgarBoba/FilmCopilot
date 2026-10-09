import { useEffect, useRef } from 'react';

/**
 * The agent's face: a plain dark ball with two eyes. Its mood says what the agent is
 * doing, so the user can tell at a glance without opening the panel.
 *
 *   idle     eyes open, blink now and then, glance toward the pointer
 *   working  eyes narrow and scan left-right; a thin light runs round the edge
 *   waiting  amber eyes and ring: something needs your confirmation
 *   happy    "^ ^" eyes for a moment after a round finished
 */
export type AgentMood = 'idle' | 'working' | 'waiting' | 'happy';

interface AgentAvatarProps {
  mood?: AgentMood;
  size?: number;
  /** Eyes glance toward the pointer (only for the big one; a header icon stays calm). */
  followPointer?: boolean;
}

const MAX_GLANCE = 0.08; // of the avatar size

export function AgentAvatar({ mood = 'idle', size = 44, followPointer = false }: AgentAvatarProps) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element || !followPointer || mood !== 'idle') {
      element?.style.removeProperty('--look-x');
      element?.style.removeProperty('--look-y');
      return undefined;
    }
    let frame = 0;
    let pointer: { x: number; y: number } | null = null;
    const update = () => {
      frame = 0;
      if (!pointer) return;
      const rect = element.getBoundingClientRect();
      const dx = pointer.x - (rect.left + rect.width / 2);
      const dy = pointer.y - (rect.top + rect.height / 2);
      const distance = Math.hypot(dx, dy) || 1;
      // Far away: look fully that way; close by: only a little.
      const reach = Math.min(1, distance / 240) * MAX_GLANCE * size;
      element.style.setProperty('--look-x', `${(dx / distance) * reach}px`);
      element.style.setProperty('--look-y', `${(dy / distance) * reach * 0.7}px`);
    };
    const onMove = (event: PointerEvent) => {
      pointer = { x: event.clientX, y: event.clientY };
      if (!frame) frame = requestAnimationFrame(update);
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [followPointer, mood, size]);

  return (
    <span
      ref={ref}
      className={`agent-avatar is-${mood}`}
      style={{ '--avatar-size': `${size}px` } as React.CSSProperties}
      aria-hidden="true"
    >
      <span className="agent-avatar-rim" />
      <span className="agent-avatar-face">
        <span className="agent-avatar-eyes">
          <span className="agent-avatar-eye" />
          <span className="agent-avatar-eye" />
        </span>
      </span>
    </span>
  );
}

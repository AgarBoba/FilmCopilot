import { useEffect, useRef } from 'react';

/**
 * The agent's face: a little line-drawn kitten. Its mood says what the agent is doing,
 * so the user can tell at a glance without opening the panel.
 *
 *   idle     eyes open, blink now and then, glance toward the pointer
 *   working  squints and looks left-right, ear twitches; a light runs round the edge
 *   waiting  ears up, a small hop and an amber "?" — something needs your confirmation
 *   happy    "^ ^" eyes and pink cheeks for a moment after a round finished
 */
export type AgentMood = 'idle' | 'working' | 'waiting' | 'happy';

interface AgentAvatarProps {
  mood?: AgentMood;
  size?: number;
  /** Eyes glance toward the pointer (only for the big one; a header icon stays calm). */
  followPointer?: boolean;
}

/** How far the eyes may glance, in the drawing's own units (the face is 100 wide). */
const MAX_GLANCE = 5;

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
      const reach = Math.min(1, distance / 240) * MAX_GLANCE;
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
  }, [followPointer, mood]);

  return (
    <span
      ref={ref}
      className={`agent-avatar is-${mood}`}
      style={{ '--avatar-size': `${size}px` } as React.CSSProperties}
      aria-hidden="true"
    >
      <span className="agent-avatar-rim" />
      <svg className="agent-kitty" viewBox="0 0 100 100">
        {/* Ears go first so the head covers their bases. */}
        <g className="kitty-ear kitty-ear-left">
          <path className="kitty-line kitty-fur" d="M20 52 L23 16 Q25 12 29 15 L47 33 Z" />
          <path className="kitty-inner" d="M26 40 L27 23 L38 34 Z" />
        </g>
        <g className="kitty-ear kitty-ear-right">
          <path className="kitty-line kitty-fur" d="M80 52 L77 16 Q75 12 71 15 L53 33 Z" />
          <path className="kitty-inner" d="M74 40 L73 23 L62 34 Z" />
        </g>
        <ellipse className="kitty-line kitty-fur" cx="50" cy="59" rx="35" ry="28" />

        <g className="kitty-whiskers kitty-line">
          <path d="M17 62 L5 59 M17 68 L5 70 M83 62 L95 59 M83 68 L95 70" />
        </g>
        <ellipse className="kitty-cheek" cx="29" cy="68" rx="6" ry="3.6" />
        <ellipse className="kitty-cheek" cx="71" cy="68" rx="6" ry="3.6" />

        <g className="kitty-look">
          <g className="kitty-eyes">
            <g className="kitty-eye">
              <ellipse cx="37" cy="57" rx="4.6" ry="6" />
              <circle className="kitty-shine" cx="38.6" cy="54.6" r="1.6" />
            </g>
            <g className="kitty-eye">
              <ellipse cx="63" cy="57" rx="4.6" ry="6" />
              <circle className="kitty-shine" cx="64.6" cy="54.6" r="1.6" />
            </g>
          </g>
          <path className="kitty-happy kitty-line" d="M31 59 Q37 51 43 59 M57 59 Q63 51 69 59" />
        </g>

        <path className="kitty-nose" d="M47 64.5 Q50 63 53 64.5 Q51.5 67.5 50 67.8 Q48.5 67.5 47 64.5 Z" />
        <path className="kitty-mouth kitty-line" d="M43.5 69.5 Q46.8 73.5 50 69.5 Q53.2 73.5 56.5 69.5" />

        <g className="kitty-ask">
          <circle cx="86" cy="18" r="11" />
          <text x="86" y="23.5" textAnchor="middle">?</text>
        </g>
      </svg>
    </span>
  );
}

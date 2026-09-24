import { useEffect, useRef } from 'react';

/**
 * The node's name on a small hang tag at the top-left of the frame, shown while the node is
 * not selected (selected, the name bar takes over). Dragging the node makes the tag swing
 * against the motion and settle back, like a tag on a string. Decorative: the same name is in
 * the real title control, so it's hidden from screen readers.
 */
export function NodeTag({ title, x }: { title: string; x?: number }) {
  const tagRef = useRef<HTMLDivElement>(null);
  const swing = useRef({ lastX: x ?? 0, push: 0, angle: 0, spin: 0, frame: 0 });

  useEffect(() => {
    const state = swing.current;
    if (x === undefined) return;
    const dx = x - state.lastX;
    state.lastX = x;
    if (dx === 0 || prefersReducedMotion()) return;
    // The tag lags behind the motion: moving left, its bottom trails out to the right, which
    // is a counter-clockwise turn about the string (negative angle), and vice versa.
    state.push = Math.max(-40, Math.min(40, state.push + dx));
    if (!state.frame) state.frame = requestAnimationFrame(step);

    function step() {
      state.push *= 0.82; // the push fades when the node stops moving
      const target = Math.max(-22, Math.min(22, state.push * 0.9));
      state.spin += (target - state.angle) * 0.12; // spring toward the target
      state.spin *= 0.86; // damping
      state.angle += state.spin;
      tagRef.current?.style.setProperty('--tag-swing', `${state.angle.toFixed(2)}deg`);
      const settled = Math.abs(state.angle) < 0.05 && Math.abs(state.spin) < 0.05 && Math.abs(state.push) < 0.05;
      if (settled) {
        state.angle = 0;
        state.spin = 0;
        tagRef.current?.style.setProperty('--tag-swing', '0deg');
        state.frame = 0;
        return;
      }
      state.frame = requestAnimationFrame(step);
    }
  }, [x]);

  useEffect(() => () => cancelAnimationFrame(swing.current.frame), []);

  return (
    <div className="node-tag" ref={tagRef} aria-hidden="true">
      <span className="node-tag-string" />
      <span className="node-tag-card">
        <i className="node-tag-hole" />
        <span className="node-tag-text">{title}</span>
      </span>
    </div>
  );
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
}

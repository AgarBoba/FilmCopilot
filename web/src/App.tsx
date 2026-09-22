import { useEffect, useState } from 'react';

import { ApiError, api } from './api/client';
import { CanvasShell } from './canvas/CanvasShell';
import { useCanvasStore } from './state/canvasStore';


export default function App() {
  const snapshot = useCanvasStore((state) => state.snapshot);
  const error = useCanvasStore((state) => state.error);
  const load = useCanvasStore((state) => state.load);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    let active = true;
    async function boot() {
      try {
        await load('default');
      } catch (loadError) {
        if (!(loadError instanceof ApiError) || loadError.status !== 404) {
          return;
        }
        await api.createCanvas('My creative canvas', 'default');
        if (active) {
          await load('default');
        }
      } finally {
        if (active) setBooting(false);
      }
    }
    void boot();
    return () => {
      active = false;
    };
  }, [load]);

  if (booting && !snapshot) {
    return <main className="app-shell loading-state">正在加载画布…</main>;
  }

  if (!snapshot) {
    return (
      <main className="app-shell loading-state">
        <h1>画布暂时无法加载</h1>
        <p>{error ?? '请检查本地 API 是否已启动。'}</p>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <CanvasShell />
    </main>
  );
}

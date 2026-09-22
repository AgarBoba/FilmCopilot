export default function App() {
  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">LOCAL CREATIVE WORKSPACE</p>
          <h1>Infinite Media Canvas</h1>
        </div>
        <span className="status-pill">准备开始</span>
      </header>
      <section className="empty-state" aria-label="画布空状态">
        <div className="empty-mark">✦</div>
        <h2>从一个素材节点开始</h2>
        <p>在无限画布上组织图片、视频、提示词和生成关系。</p>
      </section>
    </main>
  );
}

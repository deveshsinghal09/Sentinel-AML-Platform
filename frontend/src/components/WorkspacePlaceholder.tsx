export default function WorkspacePlaceholder({
  eyebrow,
  title,
  description,
  phase,
}: {
  eyebrow: string
  title: string
  description: string
  phase: string
}) {
  return (
    <main className="workspace-page">
      <header className="workspace-page__header">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <span className="phase-badge">{phase}</span>
      </header>
      <section className="workspace-placeholder">
        <span className="workspace-placeholder__mark" aria-hidden="true">◇</span>
        <div>
          <h2>Workspace foundation ready</h2>
          <p>
            Navigation and the page contract are in place. Operational data and
            write actions are introduced in the banking-workflow phase.
          </p>
        </div>
      </section>
    </main>
  )
}

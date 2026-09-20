import { Link, useLocation } from 'react-router-dom'

export default function NotFound() {
  const location = useLocation()

  return (
    <section className="not-found-page" aria-labelledby="not-found-title">
      <span className="not-found-page__code" aria-hidden="true">404</span>
      <div>
        <span className="section-kicker">Workspace route unavailable</span>
        <h1 id="not-found-title">This investigation view does not exist.</h1>
        <p>
          Sentinel could not match <code>{location.pathname}</code> to an
          approved analyst workspace. No data or workflow action was changed.
        </p>
        <Link className="not-found-page__action" to="/">
          Return to command center
          <span aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  )
}

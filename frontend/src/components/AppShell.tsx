import { NavLink, Outlet } from "react-router-dom";
import { NAV_SECTIONS } from "@/routes/navigation";

/**
 * Root application shell: a skip link, a persistent left navigation
 * landmark (`<nav aria-label="Primary">`), and a `<main>` outlet for the
 * routed page. `NavLink` sets `aria-current="page"` automatically on the
 * active link -- no manual active-state bookkeeping.
 */
export function AppShell() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className="app-shell__topbar">
        <span className="app-shell__brand">TDM Console</span>
        <span className="app-shell__environment-note" aria-hidden="true">
          Enterprise Healthcare Test Data Management Platform
        </span>
      </header>
      <div className="app-shell__body">
        <nav className="app-shell__nav" aria-label="Primary">
          {NAV_SECTIONS.map((section) => (
            <div key={section.title} className="app-shell__nav-section">
              <h2 className="app-shell__nav-heading">{section.title}</h2>
              <ul>
                {section.items.map((item) => (
                  <li key={item.path}>
                    <NavLink to={item.path} className={({ isActive }) => (isActive ? "is-active" : undefined)}>
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <main id="main-content" className="app-shell__main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

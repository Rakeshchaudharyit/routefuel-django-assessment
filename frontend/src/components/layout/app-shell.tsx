"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  ArrowUpRight,
  ChartNoAxesCombined,
  Code2,
  Fuel,
  Menu,
  Route,
  X,
} from "lucide-react";
export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to workspace
      </a>
      <div className="mobile-bar">
        <Link href="/" className="brand">
          <Fuel />
          RouteFuel<span className="brand-dot">.</span>
        </Link>
        <button
          className="icon-button"
          onClick={() => setOpen(!open)}
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          aria-controls="sidebar"
        >
          {open ? <X /> : <Menu />}
        </button>
      </div>
      <aside id="sidebar" className={`sidebar ${open ? "is-open" : ""}`}>
        <Link href="/" className="brand">
          <span className="brand-icon">
            <Fuel size={23} />
          </span>
          RouteFuel<span className="brand-dot">.</span>
        </Link>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          <Link
            href="/"
            className={`nav-item ${pathname === "/" ? "active" : ""}`}
            aria-current={pathname === "/" ? "page" : undefined}
            onClick={() => setOpen(false)}
          >
            <Route size={19} />
            Route Planner
            <span className="nav-active-dot" />
          </Link>
          <Link
            href="/#fuel-analysis"
            className="nav-item"
            onClick={() => setOpen(false)}
          >
            <ChartNoAxesCombined size={19} />
            Fuel Analysis
          </Link>
          <Link
            href="/api-documentation"
            className={`nav-item ${pathname === "/api-documentation" ? "active" : ""}`}
            aria-current={
              pathname === "/api-documentation" ? "page" : undefined
            }
            onClick={() => setOpen(false)}
          >
            <Code2 size={19} />
            API Documentation
          </Link>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Route size={22} />
            <h3>A better way to go.</h3>
            <p>
              Thoughtful routes.
              <br />
              Smarter fuel decisions.
            </p>
          </div>
          <div className="sidebar-footer">
            <span className="version-dot" /> RouteFuel{" "}
            <span>
              v0.5 <ArrowUpRight size={13} />
            </span>
          </div>
        </div>
      </aside>
      <main id="main-content" className="main-content">
        {children}
      </main>
    </div>
  );
}

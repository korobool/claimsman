import { NavLink, Outlet, Route, Routes } from "react-router-dom";
import DomainsList from "./settings/DomainsList";
import DomainDetail from "./settings/DomainDetail";

export default function Settings() {
  return (
    <Routes>
      <Route element={<SettingsShell />}>
        <Route index element={<DomainsList />} />
        <Route path="domains" element={<DomainsList />} />
        <Route path="domains/:code" element={<DomainDetail />} />
      </Route>
    </Routes>
  );
}

function SettingsShell() {
  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 border-r border-line bg-bg-raised px-3 py-5">
        <div className="mb-5 px-2 text-xs uppercase tracking-wide text-ink-faint">
          Settings
        </div>
        <nav className="flex flex-col gap-1">
          {[
            { to: "/settings/domains", label: "Domains" },
            { to: "/settings/schemas", label: "Schemas", disabled: true },
            { to: "/settings/llm", label: "LLM", disabled: true },
            { to: "/settings/health", label: "Health", disabled: true },
          ].map((item) =>
            item.disabled ? (
              <span
                key={item.to}
                className="cursor-not-allowed rounded-md px-3 py-2 text-sm text-ink-faint"
                title="Coming in a later milestone"
              >
                {item.label}
                <span className="ml-2 text-[10px] uppercase">soon</span>
              </span>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  [
                    "rounded-md px-3 py-2 text-sm",
                    isActive
                      ? "bg-accent/15 text-ink"
                      : "text-ink-dim hover:bg-bg-hover hover:text-ink",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ),
          )}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

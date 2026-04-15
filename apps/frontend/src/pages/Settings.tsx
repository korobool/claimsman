import { NavLink, Outlet, Route, Routes } from "react-router-dom";
import DomainsList from "./settings/DomainsList";
import DomainDetail from "./settings/DomainDetail";
import SchemasPage from "./settings/Schemas";
import Llm from "./settings/Llm";
import Health from "./settings/Health";

export default function Settings() {
  return (
    <Routes>
      <Route element={<SettingsShell />}>
        <Route index element={<DomainsList />} />
        <Route path="domains" element={<DomainsList />} />
        <Route path="domains/:code" element={<DomainDetail />} />
        <Route path="schemas" element={<SchemasPage />} />
        <Route path="llm" element={<Llm />} />
        <Route path="health" element={<Health />} />
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
            { to: "/settings/schemas", label: "Schemas" },
            { to: "/settings/llm", label: "LLM" },
            { to: "/settings/health", label: "Health" },
          ].map((item) => (
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
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

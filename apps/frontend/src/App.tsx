import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import Inbox from "./pages/Inbox";
import NewClaim from "./pages/NewClaim";
import ClaimDetail from "./pages/ClaimDetail";
import Audit from "./pages/Audit";
import Dev from "./pages/Dev";
import Settings from "./pages/Settings";
import { api, type DevState } from "./lib/api";

const navItems = [
  { to: "/", label: "Inbox", end: true },
  { to: "/new", label: "New Claim" },
  { to: "/audit", label: "Audit" },
  { to: "/settings", label: "Settings" },
  { to: "/dev", label: "Dev", badge: true },
];

export default function App() {
  const [dev, setDev] = useState<DevState | null>(null);

  useEffect(() => {
    let cancelled = false;
    const pull = () => {
      api.devState().then(
        (s) => !cancelled && setDev(s),
        () => undefined,
      );
    };
    pull();
    const interval = setInterval(pull, 10_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const version = dev?.app.version ?? "?";
  const milestone = dev?.milestone.id ?? "?";
  const milestoneLabel = dev?.milestone.label ?? "";

  return (
    <div className="flex h-full">
      <aside className="w-56 shrink-0 border-r border-line bg-bg-raised px-3 py-4">
        <div className="mb-6 px-2">
          <div className="text-lg font-semibold tracking-tight">Claimsman</div>
          <div className="mt-0.5 text-xs text-ink-faint">
            v{version} · {milestone}
          </div>
          {milestoneLabel && (
            <div
              className="mt-0.5 truncate text-[10px] text-ink-faint"
              title={milestoneLabel}
            >
              {milestoneLabel}
            </div>
          )}
        </div>
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                [
                  "flex items-center justify-between rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-accent/15 text-ink"
                    : "text-ink-dim hover:bg-bg-hover hover:text-ink",
                ].join(" ")
              }
            >
              <span>{item.label}</span>
              {item.badge && (
                <span className="rounded-full bg-severity-ok/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-severity-ok">
                  live
                </span>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route index element={<Inbox />} />
          <Route path="new" element={<NewClaim />} />
          <Route path="claims/:claimId" element={<ClaimDetail />} />
          <Route path="audit" element={<Audit />} />
          <Route path="settings/*" element={<Settings />} />
          <Route path="dev" element={<Dev />} />
        </Routes>
      </main>
    </div>
  );
}

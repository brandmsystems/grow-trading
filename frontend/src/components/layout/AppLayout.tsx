import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { MobileNav } from "./MobileNav";
import { NotificationPanel } from "./NotificationPanel";
import { NAV } from "./nav";
import { useLive } from "../../context/LiveContext";
import { ErrorNote } from "../common/States";

/** Sidebar + header + page. Phones get a bottom bar and a drawer instead of the sidebar. */
export function AppLayout() {
  const loc = useLocation();
  const [drawer, setDrawer] = useState(false);
  const [panel, setPanel] = useState(false);
  const { connection, error, markRead } = useLive();
  const current = NAV.find((n) => (n.to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(n.to)));
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar title={current?.label ?? "Grow Trading"} onBell={() => { setPanel(true); markRead(); }} />
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-3 pb-24 pt-4 sm:px-5 md:pb-8">
          {connection === "offline" && (
            <div className="mb-3"><ErrorNote offline>Backend unreachable: {error}. Retrying automatically; values shown may be stale.</ErrorNote></div>
          )}
          <Outlet />
        </main>
      </div>
      <MobileNav open={drawer} setOpen={setDrawer} />
      {panel && <NotificationPanel onClose={() => setPanel(false)} />}
    </div>
  );
}

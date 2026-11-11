import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { SettingsProvider } from "./context/SettingsContext";
import { LiveProvider } from "./context/LiveContext";
import { AppLayout } from "./components/layout/AppLayout";
import { Loading } from "./components/common/States";
import Overview from "./pages/Overview";
import LiveTrading from "./pages/LiveTrading";

// Heavier pages load on first visit.
const Signals = lazy(() => import("./pages/Signals"));
const Options = lazy(() => import("./pages/Options"));
const Backtest = lazy(() => import("./pages/Backtest"));
const Compare = lazy(() => import("./pages/Compare"));
const MarketData = lazy(() => import("./pages/MarketData"));
const HistoryCharts = lazy(() => import("./pages/HistoryCharts"));
const Account = lazy(() => import("./pages/Account"));

export default function App() {
  return (
    <SettingsProvider>
      <LiveProvider>
        <BrowserRouter basename="/app">
          <Suspense fallback={<Loading className="h-[60vh]" />}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<Overview />} />
                <Route path="live" element={<LiveTrading />} />
                <Route path="signals" element={<Signals />} />
                <Route path="options" element={<Options />} />
                <Route path="backtest" element={<Backtest />} />
                <Route path="compare" element={<Compare />} />
                <Route path="data" element={<MarketData />} />
                <Route path="history" element={<HistoryCharts />} />
                <Route path="account" element={<Account />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </LiveProvider>
    </SettingsProvider>
  );
}

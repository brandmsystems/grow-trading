import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { SettingsProvider } from "./context/SettingsContext";
import LiveDashboard from "./pages/LiveDashboard";

// Pages are ported one by one; until then the header links to the Flask-served versions.
export default function App() {
  return (
    <SettingsProvider>
      <BrowserRouter basename="/app">
        <Routes>
          <Route path="/" element={<LiveDashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SettingsProvider>
  );
}

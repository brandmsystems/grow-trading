import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { SettingsProvider, type Settings } from "../context/SettingsContext";
import { LiveProvider } from "../context/LiveContext";
import App from "../App";
import { mockApi, type MockApi } from "./mockApi";
import { lastSocket } from "./fakeSocket";

interface Options {
  route?: string;
  /** Route pattern to mount `ui` on (needed for pages that read params); default: render `ui` at any path. */
  path?: string;
  /** Saved browser settings (localStorage) before the app starts. */
  settings?: Partial<Settings>;
  /** A fake backend; created with the default routes when omitted. */
  api?: MockApi;
  /** Skip the shared live provider (for components that don't use useLive). */
  bare?: boolean;
}

export function ShowPath() {
  const l = useLocation();
  return <div data-testid="path">{l.pathname}{l.search}</div>;
}

/** Renders `ui` the way the app does: settings, the shared live poll and a router around it. */
export function renderWithProviders(ui: ReactElement, { route = "/", path, settings, api, bare }: Options = {}) {
  const backend = api ?? mockApi();
  if (settings) localStorage.setItem("gt-settings", JSON.stringify(settings));
  const body = (
    <MemoryRouter initialEntries={[route]}>
      {path ? <Routes><Route path={path} element={ui} /></Routes> : ui}
      <ShowPath />
    </MemoryRouter>
  );
  const user = userEvent.setup();
  const utils = render(
    <SettingsProvider>{bare ? body : <LiveProvider>{body}</LiveProvider>}</SettingsProvider>,
  );
  return { user, api: backend, ...utils };
}

/** The whole app at a given URL (real router, layout, lazy pages), under the /app base path. */
export function renderApp(url = "/app/", api: MockApi = mockApi()) {
  window.history.pushState({}, "", url);
  const user = userEvent.setup();
  return { user, api, ...render(<App />) };
}

/** Bring the fake WebSocket up, as the browser would once connected. */
export async function connectSocket() {
  await waitFor(() => expect(lastSocket()).toBeDefined());
  lastSocket().connect();
  return lastSocket();
}

export const text = (re: string | RegExp) => screen.findByText(re);

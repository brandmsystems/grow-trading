import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request } from "../services/api";

function mockFetch(impl: (path: string, init?: RequestInit) => Promise<Partial<Response>> | Partial<Response>) {
  const fn = vi.fn(async (path: string, init?: RequestInit) => impl(path, init) as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}
const json = (body: unknown, status = 200) => ({ status, json: async () => body });

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("returns just `data` from a successful envelope", async () => {
    mockFetch(() => json({ ok: true, data: { n: 1 } }));
    expect(await api<{ n: number }>("/api/x")).toEqual({ n: 1 });
  });

  it("returns the whole envelope from request()", async () => {
    mockFetch(() => json({ ok: true, job: "j-1" }));
    expect((await request("/api/x")).job).toBe("j-1");
  });

  it("POSTs JSON bodies with the right headers", async () => {
    const fetchMock = mockFetch(() => json({ ok: true, data: null }));
    await api("/api/live/stop", { json: { a: 1 } });
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ a: 1 }));
    expect(init?.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("throws ApiError carrying status and kind for backend errors", async () => {
    mockFetch(() => json({ ok: false, error: "Engine is not running", kind: "RuntimeError" }, 409));
    const err = await api("/api/live/confirm", { json: { id: "x" } }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ message: "Engine is not running", status: 409, kind: "RuntimeError" });
  });

  it("explains an unreachable backend", async () => {
    mockFetch(() => { throw new TypeError("fetch failed"); });
    const err = (await api("/api/x").catch((e) => e)) as Error;
    expect(err).toMatchObject({ status: 0, kind: "network" });
    expect(err.message).toMatch(/Backend unreachable/);
  });

  it("falls back to the HTTP status when the body is not JSON", async () => {
    mockFetch(() => ({ status: 500, json: async () => { throw new Error("bad json"); } }));
    await expect(api("/api/x")).rejects.toMatchObject({ message: "HTTP 500", status: 500 });
  });
});

/** A controllable stand-in for socket.io-client: no network, tests decide when it connects and what it receives. */
type Handler = (...args: unknown[]) => void;

export class FakeSocket {
  connected = false;
  emitted: { event: string; payload: unknown }[] = [];
  private handlers = new Map<string, Handler[]>();

  on(event: string, fn: Handler) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), fn]);
    return this;
  }
  removeAllListeners() { this.handlers.clear(); return this; }
  emit(event: string, payload?: unknown) { this.emitted.push({ event, payload }); return this; }
  disconnect() { this.connected = false; return this; }

  /** Server -> client event. */
  fire(event: string, ...args: unknown[]) { (this.handlers.get(event) ?? []).forEach((h) => h(...args)); }
  /** The transport comes up (the app subscribes in its `connect` handler). */
  connect() { this.connected = true; this.fire("connect"); }
  /** The transport goes away. */
  drop() { this.connected = false; this.fire("disconnect"); }
  subscribes() { return this.emitted.filter((e) => e.event === "subscribe"); }
}

export const sockets: FakeSocket[] = [];
export function createFakeSocket() { const s = new FakeSocket(); sockets.push(s); return s; }
export const lastSocket = () => sockets[sockets.length - 1];
export const resetSockets = () => { sockets.length = 0; };

import type { WsConnectionStatus, WsStreamMessage } from "../types";

interface WsClientOptions {
  url?: string;
  onStateChange: (status: WsConnectionStatus) => void;
  onMessage: (message: WsStreamMessage) => void;
  initialDelayMs?: number;
  maxDelayMs?: number;
}

const WS_ENV_URL = (import.meta.env.VITE_WS_URL ?? "").trim();
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").trim();

function deriveWsUrl(): string {
  if (WS_ENV_URL) {
    return WS_ENV_URL;
  }

  if (/^https?:\/\//i.test(API_BASE_URL)) {
    const parsed = new URL(API_BASE_URL);
    parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    parsed.pathname = "/ws/stream";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/stream`;
}

function parseWsMessage(raw: string): WsStreamMessage | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const messageType = typeof parsed.type === "string" ? parsed.type : "";

    if (messageType === "snapshot" || messageType === "event" || messageType === "symbol") {
      return {
        type: messageType,
        data: parsed.data
      } as WsStreamMessage;
    }

    return null;
  } catch {
    return null;
  }
}

export class WsStreamClient {
  private readonly url: string;
  private readonly onStateChange: (status: WsConnectionStatus) => void;
  private readonly onMessage: (message: WsStreamMessage) => void;
  private readonly initialDelayMs: number;
  private readonly maxDelayMs: number;

  private socket: WebSocket | null = null;
  private reconnectTimer: number | null = null;
  private attempt = 0;
  private isManualClose = false;

  constructor(options: WsClientOptions) {
    this.url = options.url ?? deriveWsUrl();
    this.onStateChange = options.onStateChange;
    this.onMessage = options.onMessage;
    this.initialDelayMs = options.initialDelayMs ?? 1000;
    this.maxDelayMs = options.maxDelayMs ?? 15000;
  }

  connect(): void {
    this.isManualClose = false;
    this.open();
  }

  disconnect(): void {
    this.isManualClose = true;

    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }

    this.onStateChange({
      state: "disconnected",
      attempt: this.attempt,
      message: "连接已关闭"
    });
  }

  private open(): void {
    this.onStateChange({
      state: this.attempt === 0 ? "connecting" : "reconnecting",
      attempt: this.attempt,
      message: this.attempt === 0 ? "正在连接实时流" : `正在重连（第 ${this.attempt} 次）`
    });

    this.socket = new WebSocket(this.url);

    this.socket.onopen = () => {
      this.attempt = 0;
      this.onStateChange({
        state: "connected",
        attempt: this.attempt,
        message: "实时流连接成功"
      });
    };

    this.socket.onmessage = (event) => {
      const parsed = parseWsMessage(String(event.data));
      if (parsed) {
        this.onMessage(parsed);
      }
    };

    this.socket.onerror = () => {
      this.onStateChange({
        state: "error",
        attempt: this.attempt,
        message: "实时流发生错误"
      });
    };

    this.socket.onclose = () => {
      if (this.isManualClose) {
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    this.attempt += 1;
    const delay = Math.min(this.initialDelayMs * 2 ** (this.attempt - 1), this.maxDelayMs);

    this.onStateChange({
      state: "reconnecting",
      attempt: this.attempt,
      message: `${Math.round(delay / 1000)} 秒后自动重连`
    });

    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, delay);
  }
}


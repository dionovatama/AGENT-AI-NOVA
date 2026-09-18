import { getToken } from "./auth";
import type {
  AuditLogEntry,
  ChatCompletionResult,
  Credential,
  CredentialCreateInput,
  Device,
  DeviceCreateInput,
  TaskCategory,
  ToolResult,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_NOVA_API_BASE_URL ?? "http://localhost:8000";

export class NovaApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "NovaApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // response tidak punya JSON body — pakai statusText.
    }
    throw new NovaApiError(response.status, detail);
  }

  // /health dan sejenisnya boleh mengembalikan body kosong.
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export interface HealthResponse {
  status: string;
  service: string;
  environment: string;
}

export const novaApi = {
  health: () => request<HealthResponse>("/health", {}, false),

  login: (email: string, password: string) =>
    request<{ access_token: string; token_type: string }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false
    ),

  register: (email: string, password: string) =>
    request<{ id: string; email: string; is_active: boolean }>(
      "/auth/register",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false
    ),

  me: () => request<{ id: string; email: string; is_active: boolean }>("/auth/me"),

  // useTools: kalau true, dikirim sebagai use_tools=true ke backend —
  // backend lalu boleh memanggil tool READ yang ada di allowlist
  // kategori ini (lihat _CATEGORY_TOOL_ALLOWLIST di
  // app/ai/tool_calling.py, saat ini hanya general_chat ->
  // web.search/web.read_page). Default false supaya perilaku chat lama
  // (murni reasoning, tanpa tool) tidak berubah kalau caller tidak
  // secara eksplisit minta ini.
  chatCompletion: (message: string, category: TaskCategory, useTools = false) =>
    request<ChatCompletionResult>("/chat/completions", {
      method: "POST",
      body: JSON.stringify({ message, category, use_tools: useTools }),
    }),

  listTools: () => request<string[]>("/tools/list"),

  executeTool: (
    toolName: string,
    args: Record<string, unknown>,
    confirmed: boolean
  ) =>
    request<ToolResult>("/tools/execute", {
      method: "POST",
      body: JSON.stringify({
        tool_name: toolName,
        arguments: args,
        confirmed,
      }),
    }),

  // --- Devices / Credentials / Audit Log ------------------------
  // Semua endpoint ini butuh Bearer token dan tenant-isolated di sisi
  // backend (owner_id dari JWT) — request() sudah otomatis menyertakan
  // Authorization header selama auth=true (default).

  listDevices: () => request<Device[]>("/devices"),

  createDevice: (payload: DeviceCreateInput) =>
    request<Device>("/devices", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listCredentials: () => request<Credential[]>("/credentials"),

  createCredential: (payload: CredentialCreateInput) =>
    request<Credential>("/credentials", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listAuditLogs: () => request<AuditLogEntry[]>("/audit-logs"),
};
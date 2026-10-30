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
  ConfigurationProposal,
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

export type LinuxGeneratorModule = "packages" | "ssh" | "bind9" | "firewall";
export interface LinuxGeneratorRequest { distro: "debian" | "ubuntu"; modules: LinuxGeneratorModule[]; hostname: string; ssh_port: number; dns_listen_address: string; dns_forwarders: string; firewall_ssh: boolean; }
export interface LinuxGeneratedFile { filename: string; mime_type: string; content: string; }
export interface LinuxGeneratorResponse { distro: string; modules: string[]; files: LinuxGeneratedFile[]; warnings: string[]; }


export type Bind9Profile = "resolver" | "master" | "slave" | "master-slave" | "custom";
export interface Bind9Record { record_type: "A" | "AAAA" | "CNAME" | "MX" | "NS" | "PTR" | "TXT"; name: string; value: string; priority?: number | null; ttl?: number; }
export interface Bind9GeneratorRequest {
  profile: Bind9Profile; domain: string; master_ip: string; slave_ip: string;
  network_cidr: string; resolver_listen: string; allow_recursion: string[];
  forwarders: string[]; forward_first: boolean; ipv6_listen: "any" | "none";
  primary_ns: string; secondary_ns: string; soa_contact: string;
  records: Bind9Record[]; include_reverse_zone: boolean;
  zone_config_target: "named.conf.local" | "named.conf.default-zones";
}
export interface Bind9GeneratedFile { filename: string; mime_type: string; content: string; }
export interface Bind9GeneratorResponse { profile: Bind9Profile; files: Bind9GeneratedFile[]; warnings: string[]; }
export type MikrotikGeneratorModule = "ip" | "dhcp" | "nat" | "firewall";

export interface MikrotikGeneratorRequest {
  routeros_version: "6" | "7";
  modules: MikrotikGeneratorModule[];
  lan_interface: string;
  wan_interface: string;
  ip_cidr: string;
  dhcp_pool_start: string;
  dhcp_pool_end: string;
  dns_servers: string;
}

export interface MikrotikGeneratedFile {
  filename: string;
  mime_type: string;
  content: string;
}

export interface MikrotikGeneratorResponse {
  routeros_version: string;
  modules: string[];
  files: MikrotikGeneratedFile[];
  warnings: string[];
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
  chatWithDocument: async (file: File, message: string): Promise<ChatCompletionResult> => {
    const form = new FormData();
    form.append("file", file);
    form.append("message", message);
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${BASE_URL}/chat/documents/completions`, { method: "POST", headers, body: form });
    if (!response.ok) {
      let detail = response.statusText;
      try { const body = await response.json(); detail = body.detail ?? JSON.stringify(body); } catch { /* non-JSON error */ }
      throw new NovaApiError(response.status, detail);
    }
    return await response.json() as ChatCompletionResult;
  },

  chatCompletion: (message: string, category: TaskCategory, useTools = false, configurationMode?: "file" | "direct") =>
    request<ChatCompletionResult>("/chat/completions", {
      method: "POST",
      body: JSON.stringify({
        message,
        category,
        use_tools: useTools,
        ...(configurationMode ? { configuration_mode: configurationMode } : {}),
      }),
    }),

  listTools: () => request<string[]>("/tools/list"),

  createConfiguration: (payload: { device_id: string; change_set: { description: string; operations: Array<Record<string, unknown>> } }) =>
    request<ConfigurationProposal>("/configurations", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  approveConfiguration: (configurationId: string) =>
    request<ConfigurationProposal>(`/configurations/${configurationId}/approve`, { method: "POST" }),

  applyConfiguration: (configurationId: string) =>
    request<ConfigurationProposal>(`/configurations/${configurationId}/apply`, { method: "POST" }),

  generateLinuxConfig: (payload: LinuxGeneratorRequest) => request<LinuxGeneratorResponse>("/linux-config-generator/generate", { method: "POST", body: JSON.stringify(payload) }),

  generateBind9Config: (payload: Bind9GeneratorRequest) => request<Bind9GeneratorResponse>("/bind9-config-generator/generate", { method: "POST", body: JSON.stringify(payload) }),\n\n  generateMikrotikConfig: (payload: MikrotikGeneratorRequest) =>
    request<MikrotikGeneratorResponse>("/mikrotik-config-generator/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  executeTool: (
    toolName: string,
    args: Record<string, unknown>,
    confirmed: boolean,
    deviceId?: string
  ) =>
    request<ToolResult>("/tools/execute", {
      method: "POST",
      body: JSON.stringify({
        tool_name: toolName,
        arguments: args,
        confirmed,
        ...(deviceId ? { device_id: deviceId } : {}),
      }),
    }),

  // --- Devices / Credentials / Audit Log ------------------------
  // Semua endpoint ini butuh Bearer token dan tenant-isolated di sisi
  // backend (owner_id dari JWT) — request() sudah otomatis menyertakan
  // Authorization header selama auth=true (default).

  listDevices: () => request<Device[]>("/devices"),

  deleteDevice: (deviceId: string) =>
    request<void>(`/devices/${deviceId}`, { method: "DELETE" }),

  updateDevice: (deviceId: string, payload: { metadata?: Record<string, unknown> | null }) =>
    request<Device>(`/devices/${deviceId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  createDevice: (payload: DeviceCreateInput) =>
    request<Device>("/devices", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listCredentials: () => request<Credential[]>("/credentials"),

  deleteCredential: (credentialId: string) =>
    request<void>(`/credentials/${credentialId}`, { method: "DELETE" }),

  createCredential: (payload: CredentialCreateInput) =>
    request<Credential>("/credentials", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listAuditLogs: () => request<AuditLogEntry[]>("/audit-logs"),
};
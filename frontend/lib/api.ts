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
  ConversationSummary,
  PersistedChatMessage,
  RelayTarget,
  RelayTargetCreateInput,
  ManualTopology,
  ManualTopologyNode,
  ManualTopologyLink,
  MikrotikMonitoringHistory,
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

export type MikrotikMonitoringSnapshot = {
  device_id: string;
  collected_at: string;
  router: {
    identity?: string; board_name?: string; model?: string; routeros_version?: string;
    uptime?: string; cpu_load_percent?: number; free_memory_bytes?: number;
    total_memory_bytes?: number; memory_used_percent?: number;
    free_storage_bytes?: number; total_storage_bytes?: number; storage_used_percent?: number;
  };
  interfaces: Array<{ name: string; type?: string; running: boolean; disabled: boolean; rx_bps?: number; tx_bps?: number; mac_address?: string }>;
  neighbors: Array<{ identity?: string; address?: string; mac_address?: string; interface?: string; platform?: string; version?: string }>;
  arp: Array<{ address?: string; mac_address?: string; interface?: string; complete?: boolean }>;
  dhcp_leases: Array<{ address?: string; mac_address?: string; host_name?: string; status?: string }>;
  bridge_hosts: Array<{ mac_address?: string; bridge?: string; on_interface?: string }>;
};

export interface HealthResponse {
  status: string;
  service: string;
  environment: string;
}

export type LinuxGeneratorModule = "ssh" | "ufw";
export interface LinuxGeneratorRequest { distro: "debian" | "ubuntu"; modules: LinuxGeneratorModule[]; ssh_port: number; ufw_allow_ssh: boolean; }
export interface LinuxGeneratedFile { filename: string; mime_type: string; content: string; }
export interface LinuxGeneratorResponse { distro: string; modules: string[]; files: LinuxGeneratedFile[]; warnings: string[]; }


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


export interface RemoteAgent {
  id: string;
  owner_id: string;
  name: string;
  status: "offline" | "connecting" | "online" | "disconnected" | "error" | string;
  os: string | null;
  hostname: string | null;
  agent_version: string | null;
  last_heartbeat_at: string | null;
  last_connected_at: string | null;
  last_disconnected_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface RemoteAgentProvisioned extends RemoteAgent {
  token: string;
  connect_path: string;
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

  generateMikrotikConfig: (payload: MikrotikGeneratorRequest) =>
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
  getMikrotikMonitoring: (deviceId: string, signal?: AbortSignal) =>
    request<MikrotikMonitoringSnapshot>(`/devices/${deviceId}/monitoring`, { signal }),
  getMikrotikMonitoringHistory: (deviceId: string, minutes: number, iface?: string, signal?: AbortSignal) => {
    const params = new URLSearchParams({ minutes: String(minutes) });
    if (iface) params.set("interface", iface);
    return request<MikrotikMonitoringHistory>(`/devices/${deviceId}/monitoring/history?${params}`, { signal });
  },

  deleteDevice: (deviceId: string) =>
    request<void>(`/devices/${deviceId}`, { method: "DELETE" }),

  getObservedDeviceTlsFingerprint: (deviceId: string) =>
    request<{ observed: string; expires_in_seconds: number }>(
      `/devices/${deviceId}/observed-tls-fingerprint`,
    ),
  updateDevice: (deviceId: string, payload: Partial<Pick<Device, "name" | "platform" | "host" | "port" | "connection_type" | "status" | "credential_id" | "metadata">> & { tls_fingerprint?: string | null; confirm_tls_fingerprint_change?: boolean }) =>
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

  // --- Account-scoped chat history --------------------------------
  listConversations: () => request<ConversationSummary[]>("/conversations"),
  createConversation: (title = "New chat") =>
    request<ConversationSummary>("/conversations", {
      method: "POST", body: JSON.stringify({ title }),
    }),
  getConversationMessages: (conversationId: string) =>
    request<PersistedChatMessage[]>("/conversations/" + conversationId + "/messages"),
  appendConversationMessage: (
    conversationId: string,
    role: "user" | "assistant",
    content: string,
    metadata?: Record<string, unknown>,
  ) =>
    request<PersistedChatMessage>("/conversations/" + conversationId + "/messages", {
      method: "POST", body: JSON.stringify({ role, content, metadata: metadata ?? null }),
    }),
  renameConversation: (conversationId: string, title: string) =>
    request<ConversationSummary>("/conversations/" + conversationId, {
      method: "PATCH", body: JSON.stringify({ title }),
    }),
  deleteConversation: (conversationId: string) =>
    request<void>("/conversations/" + conversationId, { method: "DELETE" }),

  // --- Remote Agent management ----------------------------------
  // Token hanya dikembalikan pada create/rotate; backend menyimpan hash.
  listAgents: () => request<RemoteAgent[]>("/agents"),
  createAgent: (name: string) =>
    request<RemoteAgentProvisioned>("/agents", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  rotateAgentToken: (agentId: string) =>
    request<RemoteAgentProvisioned>(`/agents/${agentId}/rotate-token`, { method: "POST" }),
  disconnectAgent: (agentId: string) =>
    request<{ disconnected: boolean }>(`/agents/${agentId}/disconnect`, { method: "POST" }),
  deleteAgent: (agentId: string) =>
    request<void>(`/agents/${agentId}`, { method: "DELETE" }),
  listRelayTargets: (agentId: string) =>
    request<RelayTarget[]>(`/agents/${agentId}/targets`),
  createRelayTarget: (agentId: string, payload: RelayTargetCreateInput) =>
    request<RelayTarget>(`/agents/${agentId}/targets`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  getObservedRelayFingerprint: (agentId: string, targetId: string) =>
    request<{ observed: string; expires_in_seconds: number }>(
      `/agents/${agentId}/targets/${targetId}/observed-fingerprint`,
    ),
  updateRelayTargetPin: (
    agentId: string,
    targetId: string,
    tls_fingerprint: string | null,
    expected_current_fingerprint: string | null,
    confirm: boolean,
  ) =>
    request<RelayTarget>(`/agents/${agentId}/targets/${targetId}`, {
      method: "PATCH",
      body: JSON.stringify({ tls_fingerprint, expected_current_fingerprint, confirm }),
    }),
  deleteRelayTarget: (agentId: string, targetId: string) =>
    request<void>(`/agents/${agentId}/targets/${targetId}`, { method: "DELETE" }),

  getManualTopology: () => request<ManualTopology>("/network/manual-topology"),
  createManualNode: (payload: { device_id?: string | null; name: string; kind?: string; x?: number; y?: number }) =>
    request<ManualTopologyNode>("/network/manual-topology/nodes", { method: "POST", body: JSON.stringify(payload) }),
  updateManualNode: (nodeId: string, payload: Partial<Pick<ManualTopologyNode, "name" | "kind" | "x" | "y">>) =>
    request<ManualTopologyNode>(`/network/manual-topology/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteManualNode: (nodeId: string) =>
    request<void>(`/network/manual-topology/nodes/${nodeId}`, { method: "DELETE" }),
  createManualLink: (payload: { source_node_id: string; target_node_id: string; label?: string | null; connection_type?: string }) =>
    request<ManualTopologyLink>("/network/manual-topology/links", { method: "POST", body: JSON.stringify(payload) }),
  deleteManualLink: (linkId: string) =>
    request<void>(`/network/manual-topology/links/${linkId}`, { method: "DELETE" }),

  listAuditLogs: () => request<AuditLogEntry[]>("/audit-logs"),
};
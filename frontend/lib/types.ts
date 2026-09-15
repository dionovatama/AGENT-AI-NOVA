// Tipe-tipe ini mencerminkan schema Pydantic di backend
// (app/tools/schemas.py, app/ai/model_router.py). Kalau backend berubah,
// file ini yang pertama harus disinkronkan — belum ada codegen otomatis
// (OpenAPI -> TS) di Milestone ini, sengaja belum, lihat README.

export type PermissionLevel = "read" | "modify" | "high_risk";
export type RiskLevel = "low" | "medium" | "high";

export interface ToolResult {
  success: boolean;
  tool_name: string;
  permission_level: PermissionLevel;
  risk_level: RiskLevel;
  output: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number;
}

export type TaskCategory =
  | "general_chat"
  | "technical_reasoning"
  | "troubleshooting"
  | "network_diagnostic"
  | "configuration_generation"
  | "coding"
  | "summarization";

export const TASK_CATEGORIES: { value: TaskCategory; label: string }[] = [
  { value: "general_chat", label: "General Chat" },
  { value: "technical_reasoning", label: "Technical Reasoning" },
  { value: "troubleshooting", label: "Troubleshooting" },
  { value: "network_diagnostic", label: "Network Diagnostic" },
  { value: "configuration_generation", label: "Configuration Generation" },
  { value: "coding", label: "Coding" },
  { value: "summarization", label: "Summarization" },
];

// Kategori yang backend-nya benar-benar mengekspos tool ke LLM lewat
// use_tools=True (lihat _CATEGORY_TOOL_ALLOWLIST di
// backend/app/ai/tool_calling.py). Dipakai supaya toggle "pakai tools"
// di UI chat cuma muncul untuk kategori yang memang didukung backend —
// bukan ditampilkan untuk semua kategori lalu diam-diam tidak berefek.
export const TOOL_CALLING_CATEGORIES: TaskCategory[] = ["general_chat"];

export interface ChatCompletionResult {
  content: string;
  model_used: string;
  category: TaskCategory;
  used_fallback: boolean;
  // Additive -- kosong untuk jalur chat biasa (use_tools=false). Diisi
  // backend hanya kalau tool-calling benar-benar memanggil tool (lihat
  // app/ai/tool_calling.py). Dipakai UI untuk menunjukkan tool APA
  // yang benar-benar jalan, bukan menebak dari isi jawaban model --
  // penting karena model kadang menjawab dari memori sendiri meski
  // use_tools=true (lihat catatan di ChatWindow.tsx).
  tools_used: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  meta?: {
    model_used?: string;
    used_fallback?: boolean;
    tools_used?: string[];
    // True kalau request ini dikirim dengan use_tools=true (checkbox
    // "gunakan web.search" dicentang) -- dipakai ChatWindow untuk
    // membedakan "memang tidak ditawarkan tool" vs "ditawarkan tapi
    // model tidak memanggilnya sama sekali".
    tools_offered?: boolean;
    error?: string;
  };
}

// --- Tool input registry (frontend-side, sementara) -------------------
//
// /tools/list backend cuma mengembalikan array nama (lihat
// backend/app/api/tools.py). Belum ada endpoint yang mengembalikan
// input_model tiap tool sebagai JSON schema, jadi bentuk form di sini
// di-mirror manual dari backend/app/tools/*.py. TODO nyata untuk
// Milestone berikutnya: tambahkan GET /tools/schema/{name} di backend
// supaya console tidak perlu disinkronkan tangan tiap ada tool baru.

export type ToolFieldType = "text" | "number";

export interface ToolFieldSpec {
  name: string;
  label: string;
  type: ToolFieldType;
  required: boolean;
  default?: string | number;
  min?: number;
  max?: number;
  placeholder?: string;
  helpText?: string;
}

export interface KnownToolSpec {
  name: string;
  label: string;
  platform: "network" | "linux" | "general";
  permission_level: PermissionLevel;
  risk_level: RiskLevel;
  fields: ToolFieldSpec[];
}

export const KNOWN_TOOLS: Record<string, KnownToolSpec> = {
  ping: {
    name: "ping",
    label: "Ping",
    platform: "network",
    permission_level: "read",
    risk_level: "low",
    fields: [
      { name: "target", label: "Target (host/IP)", type: "text", required: true, placeholder: "192.168.1.1" },
      { name: "count", label: "Jumlah paket", type: "number", required: false, default: 4, min: 1, max: 10 },
    ],
  },
  "linux.system_info": {
    name: "linux.system_info",
    label: "System Info",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [],
  },
  "linux.network_info": {
    name: "linux.network_info",
    label: "Network Info",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [],
  },
  "linux.disk_info": {
    name: "linux.disk_info",
    label: "Disk Info",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [],
  },
  "linux.memory_info": {
    name: "linux.memory_info",
    label: "Memory Info",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [],
  },
  "linux.service_status": {
    name: "linux.service_status",
    label: "Service Status",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [
      {
        name: "service_name",
        label: "Nama systemd service",
        type: "text",
        required: true,
        placeholder: "sshd",
        helpText: "Hanya huruf, angka, . _ @ - (divalidasi backend).",
      },
    ],
  },
  "linux.process_status": {
    name: "linux.process_status",
    label: "Process Status",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [
      { name: "name_filter", label: "Filter nama proses (opsional)", type: "text", required: false },
      { name: "limit", label: "Limit", type: "number", required: false, default: 10, min: 1, max: 50 },
    ],
  },
  "linux.docker_status": {
    name: "linux.docker_status",
    label: "Docker Status",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [],
  },
  "linux.log_check": {
    name: "linux.log_check",
    label: "Log Check (journalctl)",
    platform: "linux",
    permission_level: "read",
    risk_level: "low",
    fields: [
      { name: "service_name", label: "Nama systemd service", type: "text", required: true, placeholder: "ssh" },
      { name: "lines", label: "Jumlah baris", type: "number", required: false, default: 50, min: 1, max: 200 },
    ],
  },
  "web.search": {
    name: "web.search",
    label: "Web Search",
    platform: "general",
    permission_level: "read",
    risk_level: "low",
    fields: [
      { name: "query", label: "Kata kunci pencarian", type: "text", required: true, placeholder: "harga VPS 2 vCPU Indonesia" },
      { name: "max_results", label: "Jumlah hasil", type: "number", required: false, default: 5, min: 1, max: 10 },
    ],
  },
  "web.read_page": {
    name: "web.read_page",
    label: "Read Page",
    platform: "general",
    permission_level: "read",
    risk_level: "low",
    fields: [
      { name: "url", label: "URL", type: "text", required: true, placeholder: "https://example.com/artikel" },
      {
        name: "max_chars",
        label: "Batas karakter",
        type: "number",
        required: false,
        default: 6000,
        min: 500,
        max: 20000,
      },
    ],
  },
};
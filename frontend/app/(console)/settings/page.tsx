import { PlaceholderPanel } from "@/components/PlaceholderPanel";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1 className="text-base font-medium text-ink-100">Settings</h1>
        <p className="mt-1 text-[13px] text-ink-500">
          Belum ada endpoint pengaturan di backend. Bagian ini menandai apa yang
          akan hidup di sini sesuai roadmap PRD.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <PlaceholderPanel
          title="Voice Interface"
          milestone="Phase 11"
          description="STT → NOVA Backend → OpenRouter → Tool Execution → TTS. Tidak boleh bypass authentication/permission."
          prdReference="PRD §27 Voice System"
        />
        <PlaceholderPanel
          title="Automation (n8n)"
          milestone="Phase 12"
          description="Scheduled health check, notifikasi Discord/Telegram, webhook — n8n bukan core execution engine."
          prdReference="PRD §26 Automation & n8n"
        />
        <PlaceholderPanel
          title="Credential Management"
          milestone="Phase 5+"
          description="Secret storage terenkripsi per device. LLM hanya menerima device_id, tidak pernah credential mentah."
          prdReference="PRD §29 Credential Management"
        />
        <PlaceholderPanel
          title="RBAC & Roles"
          milestone="Phase 10"
          description="Role-based access control di atas permission level READ/MODIFY/HIGH_RISK yang sudah ada."
          prdReference="PRD §30 Security Architecture"
        />
      </div>
    </div>
  );
}

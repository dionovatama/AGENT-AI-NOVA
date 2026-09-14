import { MilestoneBadge } from "@/components/StatusBadge";
import { PlaceholderPanel } from "@/components/PlaceholderPanel";

const PREVIEW_DEVICES = [
  { name: "Core-Router", vendor: "MikroTik", type: "Router", address: "192.168.88.1", protocol: "API-SSL" },
  { name: "Core-Switch", vendor: "Cisco", type: "Switch", address: "192.168.10.2", protocol: "SSH" },
  { name: "lab-debian-01", vendor: "Linux", type: "Host", address: "192.168.1.10", protocol: "SSH" },
];

export default function DevicesPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1 className="text-base font-medium text-ink-100">Devices</h1>
        <p className="mt-1 text-[13px] text-ink-500">
          Belum ada endpoint <code className="font-mono text-ink-300">/devices</code> di
          backend — Device Management masuk lingkup Phase 5+ (PRD §35). Tabel di
          bawah adalah preview bentuk data, bukan koneksi nyata.
        </p>
      </header>

      <div className="panel mb-8 overflow-hidden">
        <div className="panel-header">
          <span className="text-[13px] text-ink-300">Preview — belum terhubung</span>
          <MilestoneBadge label="Phase 5+" />
        </div>
        <table className="w-full text-left text-[13px]">
          <thead>
            <tr className="text-ink-500">
              <th className="px-4 py-2 font-normal">Name</th>
              <th className="px-4 py-2 font-normal">Vendor</th>
              <th className="px-4 py-2 font-normal">Type</th>
              <th className="px-4 py-2 font-normal">Address</th>
              <th className="px-4 py-2 font-normal">Protocol</th>
            </tr>
          </thead>
          <tbody className="opacity-50">
            {PREVIEW_DEVICES.map((d) => (
              <tr key={d.name} className="border-t border-base-700">
                <td className="px-4 py-2 font-mono">{d.name}</td>
                <td className="px-4 py-2">{d.vendor}</td>
                <td className="px-4 py-2">{d.type}</td>
                <td className="px-4 py-2 font-mono">{d.address}</td>
                <td className="px-4 py-2">{d.protocol}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section>
        <h2 className="mb-2.5 text-[13px] text-ink-500">Menunggu implementasi</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <PlaceholderPanel
            title="Device Registry"
            milestone="Phase 5"
            description="CRUD device + credential reference (device_id, bukan credential mentah) sesuai PRD §29 & §35."
            prdReference="PRD §35 Device Management"
          />
          <PlaceholderPanel
            title="Tenant Isolation"
            milestone="Phase 10"
            description="Device, session, dan credential terisolasi per user — user A tidak bisa akses resource user B."
            prdReference="PRD §28 Multi-Tenancy"
          />
        </div>
      </section>
    </div>
  );
}

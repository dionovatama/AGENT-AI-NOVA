import Link from "next/link";

// Link nyata ke route yang beneran ada -- BUKAN mockup statis. "Technical
// Workspace" diarahkan ke /audit karena itu satu-satunya halaman existing
// yang mencerminkan "logs" secara nyata; belum ada halaman khusus
// configuration/coding workspace di backend saat ini.
const SHORTCUTS = [
  {
    href: "/tools",
    title: "System Assistant",
    description: "Linux and Windows system assistance",
  },
  {
    href: "/devices",
    title: "Network Operations",
    description: "MikroTik and Cisco troubleshooting",
  },
  {
    href: "/audit",
    title: "Technical Workspace",
    description: "Logs, configuration, coding and analysis",
  },
];

export function CapabilityShortcuts() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {SHORTCUTS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className="panel-glass p-4 transition-colors hover:border-signal-teal/40"
        >
          <h3 className="text-[14px] font-medium text-ink-100">{item.title}</h3>
          <p className="mt-1 text-[13px] leading-snug text-ink-500">{item.description}</p>
        </Link>
      ))}
    </div>
  );
}

import { TASK_CATEGORIES, type TaskCategory } from "@/lib/types";

export function CategoryPicker({
  value,
  onChange,
}: {
  value: TaskCategory;
  onChange: (category: TaskCategory) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {TASK_CATEGORIES.map((cat) => (
        <button
          key={cat.value}
          type="button"
          onClick={() => onChange(cat.value)}
          className={`rounded-sm border px-2.5 py-1 text-[12px] transition-colors ${
            value === cat.value
              ? "border-signal-teal/50 bg-signal-teal/10 text-signal-teal"
              : "border-base-600 text-ink-500 hover:text-ink-300"
          }`}
        >
          {cat.label}
        </button>
      ))}
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { TASK_CATEGORIES, type TaskCategory } from "@/lib/types";

// Didemote dari 7 tombol permanen berjejer jadi satu dropdown kompak --
// murni perubahan TAMPILAN. Logic tetap sama: user yang pilih kategori,
// backend tetap yang menentukan model + tool allowlist berdasarkan
// pilihan itu (_CATEGORY_TOOL_ALLOWLIST di tool_calling.py TIDAK
// berubah). Auto-detect kategori dari isi pesan SENGAJA tidak
// diimplementasikan di sini -- itu perubahan logic, bukan visual.
export function CategoryPicker({
  value,
  onChange,
}: {
  value: TaskCategory;
  onChange: (category: TaskCategory) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const current = TASK_CATEGORIES.find((c) => c.value === value);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-sm border border-base-600 bg-base-900 px-2.5 py-1.5 text-[12px] text-ink-300 transition-colors hover:border-signal-teal/50"
      >
        {current?.label}
        <span className={`text-ink-500 transition-transform ${open ? "rotate-180" : ""}`}>⌄</span>
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-10 mb-1.5 w-56 overflow-hidden rounded-md border border-base-600 bg-base-800 py-1 shadow-panel">
          {TASK_CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              type="button"
              onClick={() => {
                onChange(cat.value);
                setOpen(false);
              }}
              className={`block w-full px-3 py-1.5 text-left text-[12px] transition-colors ${
                value === cat.value ? "text-signal-teal" : "text-ink-300 hover:bg-base-700/60"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

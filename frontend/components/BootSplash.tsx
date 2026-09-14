"use client";

import { useEffect, useRef, useState } from "react";
import { HudLoader } from "@/components/HudLoader";

// sessionStorage (bukan localStorage) — sengaja: "sekali per sesi
// browser", bukan "sekali selamanya di device ini". Tab baru/browser
// baru = splash muncul lagi, tapi refresh/navigasi dalam tab yang sama
// tidak akan mengulang animasi.
const SESSION_KEY = "nova_boot_shown";

// Jaring pengaman UNTUK VIDEO YANG GAGAL START — bukan pemotong video
// yang sedang jalan normal. Kalau video berhasil mulai (event
// 'playing' terpicu), timer ini di-clear dan splash akan menunggu
// video sampai benar-benar selesai (event 'ended'). Timer ini hanya
// dipakai untuk kasus: file belum ada, network macet, browser diam
// tanpa pernah fire 'error' yang jelas — supaya orang tidak pernah
// terjebak di layar splash kosong.
const STUCK_TIMEOUT_MS = 4000;

// Batas atas absolut jaga-jaga kalau video ternyata sangat panjang /
// event 'ended' entah kenapa tidak pernah terpicu meski sudah playing.
// Naikkan angka ini kalau video boot resmi durasinya memang > 8 detik.
const HARD_CAP_MS = 8000;

type Phase = "checking" | "booting" | "leaving" | "done";

export function BootSplash({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [videoFailed, setVideoFailed] = useState(false);
  const hasStartedPlaying = useRef(false);

  useEffect(() => {
    const alreadyShown = window.sessionStorage.getItem(SESSION_KEY);
    setPhase(alreadyShown ? "done" : "booting");
  }, []);

  useEffect(() => {
    if (phase !== "booting") return;

    // Jaring pengaman video gagal start (file hilang, network stall, dll).
    const stuckTimeout = setTimeout(() => {
      if (!hasStartedPlaying.current) {
        console.warn(
          "[BootSplash] Video belum mulai playing setelah",
          STUCK_TIMEOUT_MS,
          "ms — kemungkinan file tidak ditemukan atau network stall. Skip splash.",
        );
        finish();
      }
    }, STUCK_TIMEOUT_MS);

    // Batas atas absolut — jaga-jaga event 'ended' tidak pernah terpicu.
    const hardCapTimeout = setTimeout(() => {
      console.warn(
        "[BootSplash] Hard cap",
        HARD_CAP_MS,
        "ms tercapai — event 'ended' tidak terpicu. Paksa selesai.",
      );
      finish();
    }, HARD_CAP_MS);

    return () => {
      clearTimeout(stuckTimeout);
      clearTimeout(hardCapTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  function finish() {
    window.sessionStorage.setItem(SESSION_KEY, "1");
    setPhase("leaving");
    setTimeout(() => setPhase("done"), 400); // durasi fade-out di bawah
  }

  function handleVideoPlaying() {
    hasStartedPlaying.current = true;
  }

  function handleVideoError(e: React.SyntheticEvent<HTMLVideoElement>) {
    const mediaError = e.currentTarget.error;
    console.error(
      "[BootSplash] Video gagal dimuat. code:",
      mediaError?.code,
      "message:",
      mediaError?.message || "(tidak ada pesan dari browser)",
    );
    setVideoFailed(true);
  }

  // Belum tahu status sessionStorage — render sebentar tanpa apa-apa
  // daripada salah nebak dan splash "berkedip" untuk repeat visit.
  if (phase === "checking") return null;

  return (
    <>
      {children}

      {(phase === "booting" || phase === "leaving") && (
        <div
          role="button"
          tabIndex={0}
          aria-label="Lewati animasi pembuka"
          onClick={finish}
          onKeyDown={(e) => e.key === "Enter" && finish()}
          className={`fixed inset-0 z-[100] flex cursor-pointer items-center justify-center bg-base-950 transition-opacity duration-[400ms] ${
            phase === "leaving" ? "pointer-events-none opacity-0" : "opacity-100"
          }`}
        >
          {!videoFailed ? (
            <video
              autoPlay
              muted
              playsInline
              onPlaying={handleVideoPlaying}
              onEnded={finish}
              onError={handleVideoError}
              className="max-h-[60vh] max-w-[85vw]"
            >
              {/* webm belum ada filenya — sengaja dihapus dulu supaya
                  tidak ada 404 yang mengaburkan debugging. Uncomment
                  baris di bawah kalau public/brand/nova-boot.webm
                  sudah tersedia (taruh SEBELUM baris mp4 — browser
                  coba urut dari atas):
              <source src="/brand/nova-boot.webm" type="video/webm" />
              */}
              <source src="/brand/nova-boot.mp4" type="video/mp4" />
            </video>
          ) : (
            <HudLoader size={96} label="INITIALIZING N.O.V.A" />
          )}

          <span className="pointer-events-none absolute bottom-6 right-6 font-mono text-[11px] text-ink-500">
            klik untuk lewati
          </span>
        </div>
      )}
    </>
  );
}
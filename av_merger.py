"""
AV Merger - standalone Windows exe
ffmpeg-et a saját mappájából vagy a PATH-ból keresi.
"""

import os
import sys
import threading
import subprocess
import itertools
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma"}

BG       = "#141414"
BG2      = "#1e1e1e"
BG3      = "#2a2a2a"
BORDER   = "#333333"
ACCENT   = "#5B7FFF"
ACCENT_H = "#7B9FFF"
TEXT     = "#e8e8e8"
TEXT2    = "#888888"
SUCCESS  = "#4CAF70"
ERROR    = "#E25555"

FONT_MAIN = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SM   = ("Segoe UI", 9)
FONT_H1   = ("Segoe UI", 13, "bold")


def get_base_dir() -> Path:
    """PyInstaller _MEIPASS vagy a script mappája."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def find_ffmpeg() -> str:
    """Beágyazott ffmpeg.exe, ha nincs, akkor PATH."""
    bundled = get_base_dir() / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return "ffmpeg"


FFMPEG = find_ffmpeg()


def detect_kind(path: str):
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def safe_stem(path: str) -> str:
    stem = Path(path).stem
    safe = "".join(c if c.isalnum() or c in " _-.()" else "_" for c in stem)
    return safe.strip("_").strip() or "file"


def get_video_ext(path: str) -> str:
    return Path(path).suffix.lower() or ".mp4"


class FileRow(tk.Frame):
    def __init__(self, parent, path, kind, on_remove, **kwargs):
        super().__init__(parent, bg=BG2, **kwargs)
        self.path = path
        self.kind = kind

        color = ACCENT if kind == "video" else SUCCESS
        tk.Label(
            self,
            text="▶ VID" if kind == "video" else "♪ AUD",
            bg=color, fg="white",
            font=("Segoe UI", 8, "bold"),
            padx=6, pady=2,
        ).pack(side="left", padx=(8, 6), pady=6)

        tk.Label(
            self, text=Path(path).name,
            bg=BG2, fg=TEXT, font=FONT_SM, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            self, text="✕", bg=BG2, fg=TEXT2,
            font=("Segoe UI", 9), bd=0, cursor="hand2",
            activebackground=BG3, activeforeground=ERROR,
            command=lambda: on_remove(self),
        ).pack(side="right", padx=8)

        self._sep = tk.Frame(parent, bg=BORDER, height=1)
        self._sep.pack(fill="x")

    def destroy(self):
        self._sep.destroy()
        super().destroy()


class AVMerger(TkinterDnD.Tk if HAS_DND else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AV Merger")
        self.geometry("680x620")
        self.minsize(560, 480)
        self.configure(bg=BG)

        self.files = []
        self.out_dir = tk.StringVar()
        self.status_var = tk.StringVar(value="Huezd be a fajlokat, vagy kattints a Hozzaadas gombra.")
        self.progress_var = tk.DoubleVar(value=0)
        self.running = False

        self._build_ui()

        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG, padx=20, pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="AV Merger", font=FONT_H1, bg=BG, fg=TEXT).pack(side="left")
        tk.Label(
            hdr, text="video + audio kombinalas",
            font=FONT_SM, bg=BG, fg=TEXT2,
        ).pack(side="left", padx=12, pady=3)

        drop_outer = tk.Frame(self, bg=BG, padx=16)
        drop_outer.pack(fill="x")

        self.drop_zone = tk.Frame(
            drop_outer, bg=BG2,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            cursor="hand2",
        )
        self.drop_zone.pack(fill="x", ipady=18)

        inner = tk.Frame(self.drop_zone, bg=BG2)
        inner.pack(expand=True)
        tk.Label(inner, text="\u2b07", font=("Segoe UI", 22), bg=BG2, fg=ACCENT).pack()
        dnd_text = "Huzd ide a fajlokat  (vagy kattints ide)" if HAS_DND else "Kattints a Hozzaadas gombra"
        tk.Label(inner, text=dnd_text, font=FONT_MAIN, bg=BG2, fg=TEXT2).pack()

        for w in [self.drop_zone, inner] + list(inner.winfo_children()):
            w.bind("<Button-1>", lambda e: self._add_files_dialog())

        if HAS_DND:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)

        btn_row = tk.Frame(self, bg=BG, padx=16, pady=8)
        btn_row.pack(fill="x")
        self._btn(btn_row, "+ Fajlok hozzaadasa", self._add_files_dialog).pack(side="left", padx=(0, 8))
        self._btn(btn_row, "Lista torlese", self._clear_all).pack(side="left")

        list_outer = tk.Frame(self, bg=BG, padx=16)
        list_outer.pack(fill="both", expand=True)

        list_border = tk.Frame(list_outer, bg=BORDER, bd=1)
        list_border.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_border, bg=BG2, bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(list_border, orient="vertical", command=canvas.yview)
        self.list_frame = tk.Frame(canvas, bg=BG2)
        self.list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw", tags="frame")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("frame", width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.empty_lbl = tk.Label(
            self.list_frame,
            text="Meg nincs fajl hozzaadva.",
            font=FONT_SM, bg=BG2, fg=TEXT2, pady=20,
        )
        self.empty_lbl.pack()

        out_row = tk.Frame(self, bg=BG, padx=16, pady=8)
        out_row.pack(fill="x")
        tk.Label(out_row, text="Kimeneti mappa:", font=FONT_SM, bg=BG, fg=TEXT2).pack(side="left")
        tk.Entry(
            out_row, textvariable=self.out_dir,
            bg=BG3, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=FONT_SM, bd=0,
            highlightthickness=1, highlightbackground=BORDER,
        ).pack(side="left", fill="x", expand=True, padx=6)
        self._btn(out_row, "Talloz", self._choose_outdir).pack(side="left")

        tk.Label(self, textvariable=self.status_var, font=FONT_SM, bg=BG, fg=TEXT2, anchor="w").pack(
            fill="x", padx=16, pady=(4, 0)
        )
        self.progress = ttk.Progressbar(self, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x", padx=16, pady=4)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "TProgressbar",
            troughcolor=BG3, background=ACCENT,
            bordercolor=BG, lightcolor=ACCENT, darkcolor=ACCENT,
        )

        merge_row = tk.Frame(self, bg=BG, padx=16, pady=10)
        merge_row.pack(fill="x")
        self.merge_btn = tk.Button(
            merge_row,
            text="\u25b6  Osszefuzes inditasa",
            bg=ACCENT, fg="white", font=FONT_BOLD,
            bd=0, pady=10, cursor="hand2",
            activebackground=ACCENT_H, activeforeground="white",
            command=self._start_merge,
        )
        self.merge_btn.pack(fill="x")

    def _btn(self, parent, text, cmd):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=BG3, fg=TEXT, font=FONT_SM,
            bd=0, padx=12, pady=6, cursor="hand2",
            activebackground=BORDER, activeforeground=TEXT,
            relief="flat",
        )

    def _on_drop(self, event):
        self._add_paths(self.tk.splitlist(event.data))

    def _add_files_dialog(self):
        paths = filedialog.askopenfilenames(
            title="Video es audio fajlok kivalasztasa",
            filetypes=[
                ("Mediafajlok", " ".join(f"*{e}" for e in sorted(VIDEO_EXTS | AUDIO_EXTS))),
                ("Videofajlok", " ".join(f"*{e}" for e in sorted(VIDEO_EXTS))),
                ("Audiofajlok", " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))),
                ("Minden fajl", "*.*"),
            ],
        )
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths):
        existing = {f["path"] for f in self.files}
        added = skipped = 0
        for p in paths:
            p = p.strip('"').strip()
            if p in existing:
                continue
            kind = detect_kind(p)
            if kind is None:
                skipped += 1
                continue
            row = FileRow(self.list_frame, p, kind, self._remove_file)
            row.pack(fill="x")
            self.files.append({"path": p, "kind": kind, "row": row})
            existing.add(p)
            added += 1
        self._refresh_empty()
        msgs = []
        if added:
            msgs.append(f"{added} fajl hozzaadva.")
        if skipped:
            msgs.append(f"{skipped} nem tamogatott formatum kihagyva.")
        if msgs:
            self.status_var.set(" ".join(msgs))

    def _remove_file(self, row):
        self.files = [f for f in self.files if f["row"] is not row]
        row.destroy()
        self._refresh_empty()

    def _clear_all(self):
        for f in self.files:
            f["row"].destroy()
        self.files.clear()
        self._refresh_empty()
        self.status_var.set("Lista torolve.")

    def _refresh_empty(self):
        if self.files:
            self.empty_lbl.pack_forget()
        else:
            self.empty_lbl.pack()
        n_vid = sum(1 for f in self.files if f["kind"] == "video")
        n_aud = sum(1 for f in self.files if f["kind"] == "audio")
        if self.files:
            self.status_var.set(
                f"{n_vid} video  *  {n_aud} audio  =  {n_vid * n_aud} kombinacio lesz exportalva"
            )

    def _choose_outdir(self):
        d = filedialog.askdirectory(title="Kimeneti mappa")
        if d:
            self.out_dir.set(d)

    def _start_merge(self):
        if self.running:
            return
        videos = [f["path"] for f in self.files if f["kind"] == "video"]
        audios  = [f["path"] for f in self.files if f["kind"] == "audio"]
        if not videos:
            messagebox.showwarning("Nincs video", "Adj hozza legalabb egy videofajlt.")
            return
        if not audios:
            messagebox.showwarning("Nincs audio", "Adj hozza legalabb egy audiofajlt.")
            return
        out = self.out_dir.get().strip()
        if not out:
            out = str(Path(videos[0]).parent / "av_merger_output")
        Path(out).mkdir(parents=True, exist_ok=True)
        self.out_dir.set(out)
        self.running = True
        self.merge_btn.configure(state="disabled", bg=BG3, text="Folyamatban...")
        self.progress_var.set(0)
        threading.Thread(target=self._merge_worker, args=(videos, audios, out), daemon=True).start()

    def _merge_worker(self, videos, audios, out_dir):
        combos = list(itertools.product(videos, audios))
        total  = len(combos)
        errors = []
        for i, (vid, aud) in enumerate(combos):
            out_name = f"{safe_stem(vid)}__{safe_stem(aud)}{get_video_ext(vid)}"
            out_path = str(Path(out_dir) / out_name)
            self.after(0, self.status_var.set, f"[{i+1}/{total}] {out_name}")
            cmd = [
                FFMPEG, "-y",
                "-i", vid, "-i", aud,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0", "-map", "1:a:0",
                "-shortest",
                out_path,
            ]
            try:
                res = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=600,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if res.returncode != 0:
                    errors.append(f"{out_name}: ffmpeg hiba ({res.returncode})")
            except subprocess.TimeoutExpired:
                errors.append(f"{out_name}: idotullepes")
            except Exception as e:
                errors.append(f"{out_name}: {e}")
            self.after(0, self.progress_var.set, (i + 1) / total * 100)
        self.after(0, self._merge_done, total, errors, out_dir)

    def _merge_done(self, total, errors, out_dir):
        self.running = False
        self.merge_btn.configure(state="normal", bg=ACCENT, text="\u25b6  Osszefuzes inditasa")
        self.progress_var.set(100)
        if errors:
            err_text = "\n".join(errors[:10])
            if len(errors) > 10:
                err_text += f"\n... es meg {len(errors)-10} hiba."
            messagebox.showerror("Hibak", f"{len(errors)} fajl sikertelen:\n\n{err_text}")
            self.status_var.set(f"Kesz - {total-len(errors)}/{total} sikeres  |  {out_dir}")
        else:
            self.status_var.set(f"Kesz! {total} fajl exportalva  ->  {out_dir}")
            if messagebox.askyesno(
                "Exportalas kesz",
                f"{total} fajl sikeresen elkeszult.\n\nMegnyitod a kimeneti mappat?",
            ):
                os.startfile(out_dir)


if __name__ == "__main__":
    app = AVMerger()
    app.mainloop()

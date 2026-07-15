"""
silence.remove — Desktop Edition
A premium dark-themed Tkinter app that removes silence from videos locally.
Same processing engine as the web (Gradio) version — ffmpeg or auto-editor —
just a native desktop UI instead of a browser tab.

Requirements:
    - Python 3.10
    - ffmpeg (and ffprobe) available on PATH
    - pip install pydub pillow
    - (optional) pip install auto-editor   -> enables the auto-editor engine

Run:
    python app_tkinter.py
"""

import os
import sys
import json
import time
import uuid
import shutil
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# ── Windows DPI awareness ────────────────────────────────────────────────────
# Without this, Windows treats the app as DPI-unaware and bitmap-scales the
# whole window to match the display's scaling factor. That's what causes
# blurry/pixelated edges and layouts that look "too small" for their content
# on 125%/150%/200% scaled displays. Must run before any Tk window is created.
if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# ══════════════════════════════════════════════════════════════════════════
#  Paths / constants
# ══════════════════════════════════════════════════════════════════════════

APP_DIR       = Path(__file__).resolve().parent
APP_TEMP_ROOT = APP_DIR / "sr_app_temp"
WORK_ROOT     = APP_TEMP_ROOT / "work"
DEFAULT_OUTPUT_ROOT = APP_TEMP_ROOT / "outputs"
for _d in (WORK_ROOT, DEFAULT_OUTPUT_ROOT):
    _d.mkdir(parents=True, exist_ok=True)

SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

BACKEND_FFMPEG      = "ffmpeg"
BACKEND_AUTO_EDITOR = "auto-editor"

# ══════════════════════════════════════════════════════════════════════════
#  GPU detection
# ══════════════════════════════════════════════════════════════════════════

def detect_gpu():
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                            capture_output=True, text=True, timeout=10,
                            encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        if "h264_nvenc" in out:
            return "h264_nvenc", "NVIDIA NVENC · H.264", True
        if "hevc_nvenc" in out:
            return "hevc_nvenc", "NVIDIA NVENC · H.265", True
    except Exception:
        pass
    return "libx264", "CPU · libx264", False

GPU_ENCODER, GPU_LABEL, IS_GPU = detect_gpu()
AUTO_EDITOR_AVAILABLE = shutil.which("auto-editor") is not None

# ══════════════════════════════════════════════════════════════════════════
#  Small helpers
# ══════════════════════════════════════════════════════════════════════════

def fmt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h}h {m:02d}m {s:05.2f}s"
    if m:
        return f"{m}m {s:05.2f}s"
    return f"{s:.2f}s"


def get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_entries", "format=duration", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        r2 = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        return float(r2.stdout.strip())


def list_videos_in_dir(dir_path: str) -> list:
    p = Path(dir_path)
    return sorted(
        str(f) for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    )


def unique_output_path(input_path: str, out_dir: Path) -> str:
    p = Path(input_path)
    short_id = uuid.uuid4().hex[:6]
    filename = f"{p.stem}_removed_{short_id}{p.suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return str(out_dir / filename)


def open_in_file_manager(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Could not open folder", str(e))


# ══════════════════════════════════════════════════════════════════════════
#  Processing engines (same algorithm as the web version)
# ══════════════════════════════════════════════════════════════════════════

class Cancelled(Exception):
    pass


def run_ffmpeg_backend(video_path, pause_duration, work_dir, out_path, progress_cb, cancel_evt):
    t0 = time.time()

    progress_cb(0.05, "Extracting audio…")
    audio_path = work_dir / "audio.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
        str(audio_path)
    ], check=True, capture_output=True, encoding="utf-8", errors="replace")

    if cancel_evt.is_set():
        raise Cancelled()

    progress_cb(0.14, "Detecting speech regions…")
    audio  = AudioSegment.from_file(str(audio_path))
    ranges = detect_nonsilent(audio, min_silence_len=100, silence_thresh=-45)
    if not ranges:
        raise RuntimeError("No speech detected. Is there audio in this video?")

    pause_ms = int(pause_duration * 1000)
    orig_ms  = len(audio)
    keeps = []
    for s_ms, e_ms in ranges:
        ext = min(e_ms + pause_ms, orig_ms)
        if keeps and s_ms <= keeps[-1][1]:
            keeps[-1] = (keeps[-1][0], max(keeps[-1][1], ext))
        else:
            keeps.append((s_ms, ext))

    total = len(keeps)
    progress_cb(0.22, f"Cutting {total} segments…")

    clips_dir = work_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    clip_paths = []

    enc_flags = ["-c:v", GPU_ENCODER, "-c:a", "aac"]
    if not IS_GPU:
        enc_flags += ["-preset", "fast", "-crf", "18"]

    for idx, (s_ms, e_ms) in enumerate(keeps):
        if cancel_evt.is_set():
            raise Cancelled()
        progress_cb(0.22 + 0.62 * (idx / total), f"Segment {idx + 1} / {total}")
        clip = clips_dir / f"clip_{idx:05d}.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(s_ms / 1000.0),
            "-i", video_path,
            "-t", str((e_ms - s_ms) / 1000.0),
            *enc_flags,
            "-avoid_negative_ts", "1",
            str(clip)
        ], check=True, capture_output=True, encoding="utf-8", errors="replace")
        clip_paths.append(clip)

    progress_cb(0.86, "Merging clips…")
    concat_txt = work_dir / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p}'" for p in clip_paths), encoding="utf-8")

    merged = work_dir / "merged.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(merged)
    ], check=True, capture_output=True, encoding="utf-8", errors="replace")

    progress_cb(0.95, "Saving output…")
    shutil.move(str(merged), str(out_path))

    final_dur = get_duration(str(out_path))
    orig_dur  = orig_ms / 1000.0
    removed   = max(orig_dur - final_dur, 0)
    pct       = (removed / orig_dur * 100) if orig_dur else 0

    return dict(
        orig=fmt(orig_dur), final=fmt(final_dur), removed=fmt(removed),
        segments=total, cuts=total, proc=fmt(time.time() - t0),
        encoder=GPU_LABEL, pct=pct, out_path=str(out_path),
        orig_sec=orig_dur, final_sec=final_dur, removed_sec=removed,
    )


def run_auto_editor_backend(video_path, pause_duration, work_dir, out_path, progress_cb, cancel_evt):
    t0 = time.time()
    if shutil.which("auto-editor") is None:
        raise RuntimeError("auto-editor is not installed. Install it with: pip install auto-editor")

    progress_cb(0.05, "Reading source duration…")
    orig_dur = get_duration(video_path)

    ae_temp_dir = work_dir / "ae_temp"
    ae_temp_dir.mkdir(exist_ok=True)

    cmd = [
        "auto-editor", os.path.abspath(video_path),
        "--margin", f"{pause_duration}sec",
        "--no-open", "--temp-dir", str(ae_temp_dir),
        "-o", str(out_path),
    ]
    progress_cb(0.2, "Running auto-editor…")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"auto-editor failed:\n{result.stderr[-800:] or result.stdout[-800:]}")
    if not out_path.exists():
        raise RuntimeError("auto-editor finished but no output file was produced.")

    progress_cb(0.95, "Reading output duration…")
    final_dur = get_duration(str(out_path))
    removed   = max(orig_dur - final_dur, 0)
    pct       = (removed / orig_dur * 100) if orig_dur else 0

    return dict(
        orig=fmt(orig_dur), final=fmt(final_dur), removed=fmt(removed),
        segments="—", cuts="—", proc=fmt(time.time() - t0),
        encoder=BACKEND_AUTO_EDITOR, pct=pct, out_path=str(out_path),
        orig_sec=orig_dur, final_sec=final_dur, removed_sec=removed,
    )


# ══════════════════════════════════════════════════════════════════════════
#  Theme
# ══════════════════════════════════════════════════════════════════════════

BG        = "#0a0c11"
S1        = "#12151d"
S2        = "#171b26"
S3        = "#1d2330"
S4        = "#242b3a"
BORDER    = "#232a3b"
BORDER2   = "#313a4f"
TEXT      = "#edf0f7"
TEXT_DIM  = "#aab1c6"
MUTED     = "#626b81"
ACCENT    = "#e2a33d"
ACCENT_HI = "#f0b757"
TEAL      = "#5fd6c4"
CORAL     = "#ff7a6b"
CANCEL_BG = "#241a1a"
CANCEL_HI = "#2e2020"

FONT_FAMILY = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
MONO_FAMILY = "Consolas" if sys.platform.startswith("win") else "Courier New"


# ══════════════════════════════════════════════════════════════════════════
#  Pillow-based crisp rendering (buttons, logo)
# ══════════════════════════════════════════════════════════════════════════

_FONT_CACHE = {}


def _load_font(bold: bool, size: int):
    candidates = []
    if sys.platform.startswith("win"):
        candidates.append(f"C:/Windows/Fonts/{'segoeuib.ttf' if bold else 'segoeui.ttf'}")
    elif sys.platform == "darwin":
        candidates.append("/System/Library/Fonts/Helvetica.ttc")
    else:
        base = "/usr/share/fonts/truetype/dejavu/"
        candidates.append(base + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"))
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def get_font(bold=False, size=13):
    key = (bold, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = _load_font(bold, size)
    return _FONT_CACHE[key]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def render_pill(width, height, bg, text, text_color, font_size=12, bold=True, icon=None, scale=4):
    """Renders a rounded-rect button as a supersampled, anti-aliased PhotoImage."""
    W, H = width * scale, height * scale
    R = (height // 2) * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=hex_rgb(bg))

    font = get_font(bold, font_size * scale)
    tc = hex_rgb(text_color)

    icon_w = 0
    isz = H * 0.36
    if icon:
        icon_w = isz + 10 * scale

    bbox = d.textbbox((0, 0), text, font=font) if text else (0, 0, 0, 0)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    total_w = tw + icon_w
    start_x = (W - total_w) / 2

    if icon == "play":
        cx, cy = start_x + isz / 2, H / 2
        d.polygon([(cx - isz * 0.32, cy - isz * 0.42),
                   (cx - isz * 0.32, cy + isz * 0.42),
                   (cx + isz * 0.45, cy)], fill=tc)
        start_x += icon_w
    elif icon == "x":
        cx, cy = start_x + isz / 2, H / 2
        r = isz * 0.32
        lw = max(2, int(isz * 0.14))
        d.line([cx - r, cy - r, cx + r, cy + r], fill=tc, width=lw)
        d.line([cx - r, cy + r, cx + r, cy - r], fill=tc, width=lw)
        start_x += icon_w

    if text:
        d.text((start_x - bbox[0], H / 2 - th / 2 - bbox[1]), text, font=font, fill=tc)

    img = img.resize((width, height), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


class PillButton(tk.Label):
    """A crisp, anti-aliased rounded button (regular Tk/ttk buttons can't match this look)."""

    def __init__(self, parent, text, command=None, bg=ACCENT, hover_bg=ACCENT_HI,
                 text_color="#1a1206", width=260, height=44, font_size=12, bold=True,
                 icon=None, disabled=False):
        self.command = command
        self.btn_w, self.btn_h = width, height
        self.bg_color, self.hover_color, self.fg_color = bg, hover_bg, text_color
        self.font_size, self.bold_flag, self.icon = font_size, bold, icon
        self.label_text = text
        self.enabled = not disabled

        self._build_images()
        super().__init__(parent, image=self.img_normal, bg=parent["bg"], bd=0,
                          cursor="hand2" if self.enabled else "arrow")
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        if disabled:
            self.set_enabled(False)

    def _build_images(self):
        self.img_normal = render_pill(self.btn_w, self.btn_h, self.bg_color, self.label_text,
                                       self.fg_color, self.font_size, self.bold_flag, self.icon)
        self.img_hover = render_pill(self.btn_w, self.btn_h, self.hover_color, self.label_text,
                                      self.fg_color, self.font_size, self.bold_flag, self.icon)
        self.img_disabled = render_pill(self.btn_w, self.btn_h, S3, self.label_text,
                                         MUTED, self.font_size, self.bold_flag, self.icon)

    def _on_click(self, event):
        if self.enabled and self.command:
            self.command()

    def _on_enter(self, event):
        if self.enabled:
            self.config(image=self.img_hover)

    def _on_leave(self, event):
        if self.enabled:
            self.config(image=self.img_normal)

    def set_enabled(self, val: bool):
        self.enabled = val
        self.config(image=self.img_normal if val else self.img_disabled,
                    cursor="hand2" if val else "arrow")

    def set_state(self, text=None, bg=None, hover_bg=None, icon=None):
        if text is not None:
            self.label_text = text
        if bg is not None:
            self.bg_color = bg
        if hover_bg is not None:
            self.hover_color = hover_bg
        if icon is not None:
            self.icon = icon
        self._build_images()
        self.config(image=self.img_normal if self.enabled else self.img_disabled)


# ══════════════════════════════════════════════════════════════════════════
#  Simple native-text radio row (crisp by construction, no canvas drawing)
# ══════════════════════════════════════════════════════════════════════════

class RadioPill(tk.Frame):
    def __init__(self, parent, text, value, variable, enabled=True, command=None):
        super().__init__(parent, bg=S1, highlightthickness=1, highlightbackground=BORDER2, bd=0)
        self.value = value
        self.variable = variable
        self.enabled = enabled
        self.command = command

        self.dot = tk.Label(self, text="○", bg=S1, fg=BORDER2, font=(FONT_FAMILY, 11))
        self.dot.pack(side="left", padx=(14, 9), pady=9)
        self.lbl = tk.Label(self, text=text, bg=S1,
                             fg=TEXT_DIM if enabled else MUTED, font=(MONO_FAMILY, 10))
        self.lbl.pack(side="left", pady=9)

        for w in (self, self.dot, self.lbl):
            w.bind("<Button-1>", self._on_click)
            if enabled:
                w.bind("<Enter>", self._on_enter)
                w.bind("<Leave>", self._on_leave)

        variable.trace_add("write", lambda *a: self._refresh())
        self._refresh()

    def _on_click(self, event):
        if self.enabled:
            self.variable.set(self.value)
            if self.command:
                self.command()

    def _on_enter(self, event):
        if self.enabled and self.variable.get() != self.value:
            self._paint(S2, BORDER2)

    def _on_leave(self, event):
        self._refresh()

    def _refresh(self):
        selected = (self.variable.get() == self.value)
        if selected:
            self._paint(S2, ACCENT, dot="●", dot_color=ACCENT, text_color=ACCENT)
        else:
            self._paint(S1, BORDER2, dot="○",
                        dot_color=BORDER2 if self.enabled else MUTED,
                        text_color=TEXT_DIM if self.enabled else MUTED)

    def _paint(self, bg, border, dot=None, dot_color=None, text_color=None):
        self.config(bg=bg, highlightbackground=border)
        self.dot.config(bg=bg)
        self.lbl.config(bg=bg)
        if dot is not None:
            self.dot.config(text=dot, fg=dot_color)
        if text_color is not None:
            self.lbl.config(fg=text_color)
        self.config(cursor="hand2" if self.enabled else "arrow")


# ══════════════════════════════════════════════════════════════════════════
#  Scrollable sidebar (so nothing ever gets clipped by window height)
# ══════════════════════════════════════════════════════════════════════════

class ScrollableSidebar(tk.Frame):
    def __init__(self, parent, bg, width):
        super().__init__(parent, bg=bg, width=width)
        self.pack_propagate(False)

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=width)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._win, width=e.width))

        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_scroll(self, lo, hi):
        # only show the scrollbar when content actually overflows
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.scrollbar.pack_forget()
        else:
            self.scrollbar.pack(side="right", fill="y")
        self.scrollbar.set(lo, hi)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ══════════════════════════════════════════════════════════════════════════
#  Waveform visual (kept — plain rectangles render crisp natively)
# ══════════════════════════════════════════════════════════════════════════

class WaveformCanvas(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=S2, highlightthickness=0, bd=0, **kw)
        self._idle_phase = 0
        self._idle_job = None
        self._last_pct = None
        self.bind("<Configure>", self._on_resize)
        self.show_idle()

    def _on_resize(self, event):
        if self._last_pct is not None:
            self.show_result(self._last_pct)

    def show_idle(self):
        self._stop_idle()
        self._last_pct = None
        self._animate_idle()

    def _stop_idle(self):
        if self._idle_job:
            self.after_cancel(self._idle_job)
            self._idle_job = None

    def _animate_idle(self):
        import math
        self.delete("all")
        w = max(self.winfo_width(), 400)
        h = max(self.winfo_height(), 80)
        n = 48
        bar_w = w / n
        for i in range(n):
            v = (math.sin(i * 0.5 + self._idle_phase) * 0.5
                 + math.sin(i * 0.23 + self._idle_phase * 1.6) * 0.3)
            bh = (abs(v) * 0.7 + 0.2) * (h * 0.8)
            x0 = i * bar_w + 1
            x1 = x0 + bar_w - 2
            y1 = h * 0.9
            y0 = y1 - bh
            self.create_rectangle(x0, y0, x1, y1, fill=ACCENT, outline="")
        self._idle_phase += 0.18
        self._idle_job = self.after(90, self._animate_idle)

    def show_result(self, pct_removed: float):
        self._stop_idle()
        self._last_pct = pct_removed
        import math
        self.delete("all")
        w = max(self.winfo_width(), 400)
        h = max(self.winfo_height(), 80)
        n = 48
        bar_w = w / n
        kept_n = max(1, round(n * (1 - pct_removed / 100)))
        for i in range(n):
            v = (math.sin(i * 0.62 + 5.4) * 0.5
                 + math.sin(i * 0.27 + 9.2) * 0.32
                 + math.sin(i * 1.31 + 2.2) * 0.18)
            bh_full = (abs(v) * 0.85 + 0.15) * (h * 0.85)
            x0 = i * bar_w + 1
            x1 = x0 + bar_w - 2
            y1 = h * 0.92
            if i < kept_n:
                y0 = y1 - bh_full
                self.create_rectangle(x0, y0, x1, y1, fill=TEAL, outline="")
            else:
                y0 = y1 - bh_full * 0.4
                self.create_rectangle(x0, y0, x1, y1, fill=S4, outline="")


# ══════════════════════════════════════════════════════════════════════════
#  Main App
# ══════════════════════════════════════════════════════════════════════════

class SilenceRemoveApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("silence.remove — Desktop")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.configure(bg=BG)

        self.selected_files: list[str] = []
        self.output_dir = tk.StringVar(value=str(DEFAULT_OUTPUT_ROOT))
        self.pause_var = tk.DoubleVar(value=0.2)
        self.pause_entry_var = tk.StringVar(value="0.20")
        self.engine_var = tk.StringVar(value=BACKEND_FFMPEG)
        self.status_var = tk.StringVar(value="Idle")

        self.msg_queue: "queue.Queue" = queue.Queue()
        self.cancel_evt = threading.Event()
        self.worker_thread = None
        self.is_running = False
        self._pause_entry_widget = None
        self._last_output_dir = None

        self._setup_style()
        self._build_ui()
        self._poll_queue()

    # ── styling ──────────────────────────────────────────────────────────
    def _setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Horizontal.TScale", background=S1, troughcolor=S3)
        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor=S3, background=ACCENT, bordercolor=S3,
                         lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("Vertical.TScrollbar", background=S3, troughcolor=S1,
                         bordercolor=S1, arrowcolor=MUTED)

    # ── layout ───────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        self.sidebar = ScrollableSidebar(body, bg=S1, width=360)
        self.sidebar.pack(side="left", fill="y")

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_left_panel(self.sidebar.inner)
        self._build_right_panel(right)
        self._build_footer()

    def _build_header(self):
        header = tk.Frame(self.root, bg=S1, height=64)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=S1)
        left.pack(side="left", padx=20, pady=10)

        logo_img = render_pill(40, 40, ACCENT_HI, "", "#1a1206", icon="play")
        logo_label = tk.Label(left, image=logo_img, bg=S1, bd=0)
        logo_label.image = logo_img
        logo_label.pack(side="left", padx=(0, 10))

        title_box = tk.Frame(left, bg=S1)
        title_box.pack(side="left")
        tk.Label(title_box, text="silence.remove", bg=S1, fg=TEXT,
                 font=(MONO_FAMILY, 13, "bold")).pack(anchor="w")
        tk.Label(title_box, text="Desktop Edition — runs 100% locally", bg=S1, fg=MUTED,
                 font=(FONT_FAMILY, 8)).pack(anchor="w")

        right = tk.Frame(header, bg=S1)
        right.pack(side="right", padx=20, pady=10)
        pill_color = TEAL if IS_GPU else MUTED
        tk.Label(right, text=GPU_LABEL, bg=S1, fg=pill_color,
                 font=(MONO_FAMILY, 9, "bold")).pack(side="right")

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

    def _build_left_panel(self, parent):
        pad = dict(padx=22)

        # ── Source ──
        self._eyebrow(parent, "01 · Source", "video(s) in")
        btn_row = tk.Frame(parent, bg=S1)
        btn_row.pack(fill="x", **pad)
        PillButton(btn_row, "Choose file(s)", command=self._choose_files,
                   bg=S3, hover_bg=S4, text_color=TEXT_DIM,
                   width=310, height=40, font_size=10, bold=False
                   ).pack(fill="x", pady=(0, 6))
        PillButton(btn_row, "Choose folder", command=self._choose_folder,
                   bg=S3, hover_bg=S4, text_color=TEXT_DIM,
                   width=310, height=40, font_size=10, bold=False
                   ).pack(fill="x")

        self.files_label = tk.Label(parent, text="No videos selected", bg=S1, fg=MUTED,
                                     font=(MONO_FAMILY, 8), justify="left", anchor="w",
                                     wraplength=300)
        self.files_label.pack(fill="x", padx=22, pady=(8, 0))

        self._divider(parent)

        # ── Engine ──
        self._eyebrow(parent, "02 · Engine", "silence detector")
        eng_frame = tk.Frame(parent, bg=S1)
        eng_frame.pack(fill="x", padx=22)
        RadioPill(eng_frame, "ffmpeg", BACKEND_FFMPEG, self.engine_var,
                  enabled=True).pack(fill="x", pady=3)
        ae_text = "auto-editor" if AUTO_EDITOR_AVAILABLE else "auto-editor (not installed)"
        RadioPill(eng_frame, ae_text, BACKEND_AUTO_EDITOR, self.engine_var,
                  enabled=AUTO_EDITOR_AVAILABLE).pack(fill="x", pady=3)

        self._divider(parent)

        # ── Threshold ──
        self._eyebrow(parent, "03 · Threshold", "pause length")
        pause_frame = tk.Frame(parent, bg=S1)
        pause_frame.pack(fill="x", padx=22)

        top_row = tk.Frame(pause_frame, bg=S1)
        top_row.pack(fill="x")
        tk.Label(top_row, text="pause between segments", bg=S1, fg=MUTED,
                 font=(MONO_FAMILY, 8)).pack(side="left")

        entry_wrap = tk.Frame(top_row, bg=S2, highlightthickness=1, highlightbackground=BORDER2)
        entry_wrap.pack(side="right")
        pause_entry = tk.Entry(entry_wrap, textvariable=self.pause_entry_var, width=5,
                                justify="right", bg=S2, fg=ACCENT, insertbackground=ACCENT,
                                relief="flat", bd=0, font=(MONO_FAMILY, 11, "bold"))
        pause_entry.pack(side="left", ipady=4, padx=(8, 2))
        tk.Label(entry_wrap, text="s", bg=S2, fg=MUTED, font=(MONO_FAMILY, 10)).pack(side="left", padx=(0, 8))
        pause_entry.bind("<Return>", self._commit_pause_entry)
        pause_entry.bind("<FocusOut>", self._commit_pause_entry)
        self._pause_entry_widget = pause_entry

        scale = ttk.Scale(pause_frame, from_=0.05, to=5.0, variable=self.pause_var,
                          orient="horizontal", command=self._on_pause_slide)
        scale.pack(fill="x", pady=(8, 0))

        tk.Label(pause_frame,
                 text="Silence kept between speech segments after trimming.\n"
                      "Drag the slider, or type an exact value (0.01–5s) and press Enter.",
                 bg=S1, fg=MUTED, font=(FONT_FAMILY, 8), wraplength=300, justify="left"
                 ).pack(anchor="w", pady=(6, 0))

        self._divider(parent)

        # ── Output ──
        self._eyebrow(parent, "04 · Output", "where to save")
        out_frame = tk.Frame(parent, bg=S1)
        out_frame.pack(fill="x", padx=22)

        self.out_entry = tk.Entry(out_frame, textvariable=self.output_dir, bg=S2, fg=TEAL,
                                   insertbackground=TEXT, relief="flat",
                                   font=(MONO_FAMILY, 8), state="readonly",
                                   readonlybackground=S2)
        self.out_entry.pack(fill="x", ipady=6)

        out_btns = tk.Frame(out_frame, bg=S1)
        out_btns.pack(fill="x", pady=(6, 0))
        PillButton(out_btns, "Browse…", command=self._choose_output_dir,
                   bg=S3, hover_bg=S4, text_color=TEXT_DIM,
                   width=148, height=32, font_size=9, bold=False
                   ).pack(side="left")
        PillButton(out_btns, "Reset to default", command=self._reset_output_dir,
                   bg=S3, hover_bg=S4, text_color=TEXT_DIM,
                   width=148, height=32, font_size=9, bold=False
                   ).pack(side="right")

        self._divider(parent)

        # ── Run ──
        run_frame = tk.Frame(parent, bg=S1)
        run_frame.pack(fill="x", padx=22, pady=(4, 24))
        self.run_btn = PillButton(run_frame, "Remove silence", command=self._on_run_click,
                                   bg=ACCENT, hover_bg=ACCENT_HI, text_color="#1a1206",
                                   width=310, height=46, font_size=12, icon="play")
        self.run_btn.pack(fill="x")

    def _build_right_panel(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=22)

        # Waveform card
        wave_card = tk.Frame(wrap, bg=S2, highlightbackground=BORDER, highlightthickness=1)
        wave_card.pack(fill="x")
        self.wave = WaveformCanvas(wave_card, height=110)
        self.wave.pack(fill="x", padx=16, pady=(16, 8))

        legend = tk.Frame(wave_card, bg=S2)
        legend.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(legend, text="●", fg=TEAL, bg=S2, font=(FONT_FAMILY, 10)).pack(side="left")
        tk.Label(legend, text="Kept   ", fg=MUTED, bg=S2, font=(MONO_FAMILY, 8)).pack(side="left")
        tk.Label(legend, text="●", fg=S4, bg=S2, font=(FONT_FAMILY, 10)).pack(side="left")
        tk.Label(legend, text="Removed", fg=MUTED, bg=S2, font=(MONO_FAMILY, 8)).pack(side="left")
        self.pct_label = tk.Label(legend, text="", fg=MUTED, bg=S2, font=(MONO_FAMILY, 10, "bold"))
        self.pct_label.pack(side="right")

        # Progress bar + status
        prog_frame = tk.Frame(wrap, bg=BG)
        prog_frame.pack(fill="x", pady=(14, 4))
        self.progress = ttk.Progressbar(prog_frame, style="Accent.Horizontal.TProgressbar",
                                         orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.status_label = tk.Label(wrap, textvariable=self.status_var, bg=BG, fg=TEXT_DIM,
                                      font=(MONO_FAMILY, 9), anchor="w")
        self.status_label.pack(fill="x", pady=(6, 0))

        # Stats card
        self.stats_card = tk.Frame(wrap, bg=S1, highlightbackground=BORDER, highlightthickness=1)
        self.stats_card.pack(fill="both", expand=True, pady=(16, 0))
        tk.Label(self.stats_card,
                 text="Your results will appear here once processing finishes.",
                 bg=S1, fg=MUTED, font=(FONT_FAMILY, 10)).pack(expand=True, pady=40)

        # Bottom action row (hidden until results exist)
        self.action_row = tk.Frame(wrap, bg=BG)
        self.open_folder_btn = PillButton(
            self.action_row, "Open output folder", command=self._open_output_folder,
            bg=S3, hover_bg=S4, text_color=TEXT_DIM, width=220, height=38, font_size=10, bold=False)

    def _build_footer(self):
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", side="bottom")
        footer = tk.Frame(self.root, bg=S1, height=30)
        footer.pack(fill="x", side="bottom")
        tk.Label(footer, text="silence.remove — nothing leaves your machine",
                 bg=S1, fg=MUTED, font=(MONO_FAMILY, 8)).pack(pady=6)

    # ── small UI builders ───────────────────────────────────────────────
    def _eyebrow(self, parent, title, subtitle):
        row = tk.Frame(parent, bg=S1)
        row.pack(fill="x", padx=22, pady=(18, 6))
        tk.Label(row, text="●", bg=S1, fg=ACCENT, font=(FONT_FAMILY, 8)).pack(side="left", padx=(0, 8))
        tk.Label(row, text=title, bg=S1, fg=MUTED, font=(MONO_FAMILY, 9, "bold")).pack(side="left")
        tk.Label(row, text=f"  {subtitle}", bg=S1, fg=MUTED, font=(MONO_FAMILY, 8)).pack(side="left")

    def _divider(self, parent):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=22, pady=14)

    # ── input handlers ──────────────────────────────────────────────────
    def _on_pause_slide(self, val):
        if self.root.focus_get() is not self._pause_entry_widget:
            self.pause_entry_var.set(f"{float(val):.2f}")

    def _commit_pause_entry(self, event=None):
        raw = self.pause_entry_var.get().strip().rstrip("sS")
        try:
            v = float(raw)
        except ValueError:
            v = self.pause_var.get()
        v = max(0.01, min(v, 5.0))
        self.pause_var.set(round(v, 2))
        self.pause_entry_var.set(f"{v:.2f}")

    def _choose_files(self):
        paths = filedialog.askopenfilenames(
            title="Choose video file(s)",
            filetypes=[("Video files", " ".join(f"*{e}" for e in SUPPORTED_EXTS)),
                       ("All files", "*.*")]
        )
        if paths:
            valid = [p for p in paths if Path(p).suffix.lower() in SUPPORTED_EXTS]
            if not valid:
                messagebox.showwarning("Unsupported files", "None of the selected files are supported video formats.")
                return
            self.selected_files = valid
            self._refresh_files_label()

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder of videos")
        if folder:
            vids = list_videos_in_dir(folder)
            if not vids:
                messagebox.showwarning("No videos found", f"No supported video files found in:\n{folder}")
                return
            self.selected_files = vids
            self._refresh_files_label()

    def _refresh_files_label(self):
        n = len(self.selected_files)
        if n == 1:
            self.files_label.config(text=f"1 video selected:\n{Path(self.selected_files[0]).name}")
        else:
            names = "\n".join(Path(f).name for f in self.selected_files[:5])
            more = f"\n… and {n - 5} more" if n > 5 else ""
            self.files_label.config(text=f"{n} videos selected:\n{names}{more}")

    def _choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose where to save processed videos")
        if folder:
            self.output_dir.set(folder)

    def _reset_output_dir(self):
        self.output_dir.set(str(DEFAULT_OUTPUT_ROOT))

    def _open_output_folder(self):
        if self._last_output_dir:
            open_in_file_manager(self._last_output_dir)

    # ── run / processing ────────────────────────────────────────────────
    def _on_run_click(self):
        if self.is_running:
            self._cancel_run()
            return
        self._commit_pause_entry()
        if not self.selected_files:
            messagebox.showwarning("No videos", "Choose one or more video files, or a folder of videos, first.")
            return
        out_dir = Path(self.output_dir.get().strip() or str(DEFAULT_OUTPUT_ROOT))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Invalid output folder", f"Couldn't use that folder:\n{e}")
            return

        self.cancel_evt.clear()
        self.is_running = True
        self.run_btn.set_state(text="Cancel", bg=CANCEL_BG, hover_bg=CANCEL_HI, icon="x")
        self.run_btn.fg_color = CORAL
        self.run_btn._build_images()
        self.run_btn.config(image=self.run_btn.img_normal)
        self.progress["value"] = 0
        self.status_var.set("Starting…")

        for w in self.stats_card.winfo_children():
            w.destroy()
        tk.Label(self.stats_card, text="Processing…", bg=S1, fg=MUTED,
                 font=(FONT_FAMILY, 10)).pack(expand=True, pady=40)
        self.action_row.pack_forget()

        engine = self.engine_var.get()
        pause_duration = float(self.pause_var.get())
        files = list(self.selected_files)

        self.worker_thread = threading.Thread(
            target=self._worker, args=(files, engine, pause_duration, out_dir), daemon=True)
        self.worker_thread.start()

    def _cancel_run(self):
        self.cancel_evt.set()
        self.status_var.set("Cancelling…")

    def _worker(self, files, engine, pause_duration, out_dir):
        job_id = uuid.uuid4().hex[:10]
        n = len(files)
        batch_dir = out_dir if n == 1 else out_dir / f"batch_{job_id}"
        results = []
        t_batch0 = time.time()

        for idx, video_path in enumerate(files):
            work_dir = WORK_ROOT / f"{job_id}_{idx}"
            work_dir.mkdir(parents=True, exist_ok=True)
            out_path = Path(unique_output_path(video_path, batch_dir))

            def cb(frac, desc, _idx=idx, _n=n):
                overall = (_idx + frac) / _n
                tag = f"[{_idx + 1}/{_n}] " if _n > 1 else ""
                self.msg_queue.put(("progress", overall, f"{tag}{desc}"))

            try:
                if self.cancel_evt.is_set():
                    raise Cancelled()
                if engine == BACKEND_AUTO_EDITOR:
                    stats = run_auto_editor_backend(video_path, pause_duration, work_dir, out_path, cb, self.cancel_evt)
                else:
                    stats = run_ffmpeg_backend(video_path, pause_duration, work_dir, out_path, cb, self.cancel_evt)
                stats["name"] = Path(video_path).name
                results.append(stats)
            except Cancelled:
                shutil.rmtree(work_dir, ignore_errors=True)
                self.msg_queue.put(("cancelled",))
                return
            except Exception as e:
                self.msg_queue.put(("error", str(e)))
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

        elapsed = fmt(time.time() - t_batch0)
        self.msg_queue.put(("done", results, str(batch_dir), elapsed))

    # ── queue polling (runs on main thread) ─────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, frac, desc = msg
                    self.progress["value"] = max(0, min(100, frac * 100))
                    self.status_var.set(desc)
                elif kind == "error":
                    messagebox.showerror("Processing error", msg[1])
                elif kind == "cancelled":
                    self._finish_run(cancelled=True)
                elif kind == "done":
                    _, results, out_dir, elapsed = msg
                    self._finish_run(results=results, out_dir=out_dir, elapsed=elapsed)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _finish_run(self, results=None, out_dir=None, elapsed=None, cancelled=False):
        self.is_running = False
        self.run_btn.fg_color = "#1a1206"
        self.run_btn.set_state(text="Remove silence", bg=ACCENT, hover_bg=ACCENT_HI, icon="play")

        if cancelled:
            self.status_var.set("Cancelled")
            self.progress["value"] = 0
            for w in self.stats_card.winfo_children():
                w.destroy()
            tk.Label(self.stats_card, text="Cancelled — no output was produced.",
                     bg=S1, fg=MUTED, font=(FONT_FAMILY, 10)).pack(expand=True, pady=40)
            return

        if not results:
            self.status_var.set("Failed — no output produced")
            for w in self.stats_card.winfo_children():
                w.destroy()
            tk.Label(self.stats_card, text="Something went wrong — no output was produced.",
                     bg=S1, fg=MUTED, font=(FONT_FAMILY, 10)).pack(expand=True, pady=40)
            return

        self._last_output_dir = out_dir
        self.status_var.set(f"Done ✓  ·  {len(results)} video(s) processed in {elapsed}")
        self.progress["value"] = 100

        tot_orig  = sum(r["orig_sec"] for r in results)
        tot_final = sum(r["final_sec"] for r in results)
        tot_removed = max(tot_orig - tot_final, 0)
        tot_pct = (tot_removed / tot_orig * 100) if tot_orig else 0

        self.wave.show_result(tot_pct)
        self.pct_label.config(text=f"−{tot_pct:.1f}% runtime",
                               fg=(CORAL if tot_pct >= 25 else ACCENT if tot_pct >= 10 else MUTED))

        self._render_stats(results, tot_orig, tot_final, tot_removed, tot_pct, elapsed, out_dir)
        self.action_row.pack(fill="x", pady=(14, 0))
        self.open_folder_btn.pack(side="left")

    def _render_stats(self, results, tot_orig, tot_final, tot_removed, tot_pct, elapsed, out_dir):
        for w in self.stats_card.winfo_children():
            w.destroy()

        inner = tk.Frame(self.stats_card, bg=S1)
        inner.pack(fill="both", expand=True, padx=18, pady=16)

        grid = tk.Frame(inner, bg=S1)
        grid.pack(fill="x")
        cards = [
            ("Videos", str(len(results))),
            ("Original total", fmt(tot_orig)),
            ("Processed total", fmt(tot_final)),
            ("Removed total", fmt(tot_removed)),
            ("Time taken", elapsed),
            ("Avg cut", f"{tot_pct:.1f}%"),
        ]
        for i, (label, value) in enumerate(cards):
            card = tk.Frame(grid, bg=S2, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            grid.grid_columnconfigure(i % 3, weight=1)
            tk.Label(card, text=label.upper(), bg=S2, fg=MUTED,
                     font=(MONO_FAMILY, 7, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
            tk.Label(card, text=value, bg=S2, fg=TEXT,
                     font=(MONO_FAMILY, 13, "bold")).pack(anchor="w", padx=10, pady=(0, 8))

        if len(results) > 1:
            tk.Label(inner, text="FILES", bg=S1, fg=MUTED,
                     font=(MONO_FAMILY, 8, "bold")).pack(anchor="w", pady=(14, 4))
            list_frame = tk.Frame(inner, bg=S1)
            list_frame.pack(fill="both", expand=True)
            canvas = tk.Canvas(list_frame, bg=S1, highlightthickness=0, height=140)
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
            rows_frame = tk.Frame(canvas, bg=S1)
            rows_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=rows_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            for r in results:
                row = tk.Frame(rows_frame, bg=S2, highlightbackground=BORDER, highlightthickness=1)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=r["name"], bg=S2, fg=TEXT_DIM, font=(MONO_FAMILY, 8),
                         anchor="w").pack(side="left", padx=8, pady=6, fill="x", expand=True)
                tk.Label(row, text=f"{r['orig']} → {r['final']}", bg=S2, fg=MUTED,
                         font=(MONO_FAMILY, 8)).pack(side="left", padx=8)
                pct_color = CORAL if r["pct"] >= 25 else ACCENT if r["pct"] >= 10 else MUTED
                tk.Label(row, text=f"−{r['pct']:.1f}%", bg=S2, fg=pct_color,
                         font=(MONO_FAMILY, 8, "bold")).pack(side="right", padx=8)

        saved = tk.Frame(inner, bg=S2, highlightbackground=BORDER2, highlightthickness=1)
        saved.pack(fill="x", pady=(14, 0))
        tk.Label(saved, text="SAVED TO", bg=S2, fg=MUTED,
                 font=(MONO_FAMILY, 7, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(saved, text=out_dir, bg=S2, fg=TEAL, font=(MONO_FAMILY, 9),
                 wraplength=560, justify="left").pack(anchor="w", padx=10, pady=(0, 8))


def main():
    root = tk.Tk()

    if not PIL_AVAILABLE:
        root.withdraw()
        messagebox.showerror(
            "Missing dependency",
            "This app needs Pillow for crisp UI rendering.\n\nInstall it with:\n    pip install pillow\n\nthen run the app again."
        )
        return

    app = SilenceRemoveApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

import gradio as gr
import os
import time
import subprocess
import shutil
import json
import uuid
from pathlib import Path
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

# ── GPU detection ──────────────────────────────────────────────────────────────

def detect_gpu():
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=10,
                           encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        if "h264_nvenc" in out: return "h264_nvenc", "NVIDIA NVENC · H.264", True
        if "hevc_nvenc" in out: return "hevc_nvenc", "NVIDIA NVENC · H.265", True
    except Exception:
        pass
    return "libx264", "CPU · libx264", False

GPU_ENCODER, GPU_LABEL, IS_GPU = detect_gpu()

SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

# Everything (uploads, work clips, final outputs) lives under a temp folder
# created right next to this script — never the OS default temp dir, and
# never next to the source file (which may be on a drive/path Gradio isn't
# allowed to serve files from, e.g. E:\... on Windows).
APP_DIR        = Path.cwd()
APP_TEMP_ROOT  = APP_DIR / "sr_app_temp"
UPLOAD_ROOT    = APP_TEMP_ROOT / "uploads"
WORK_ROOT      = APP_TEMP_ROOT / "work"
OUTPUT_ROOT    = APP_TEMP_ROOT / "outputs"
for _d in (UPLOAD_ROOT, WORK_ROOT, OUTPUT_ROOT):
    _d.mkdir(parents=True, exist_ok=True)

# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h: return f"{h}h {m:02d}m {s:05.2f}s"
    if m: return f"{m}m {s:05.2f}s"
    return f"{s:.2f}s"

def get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet",
         "-print_format", "json",
         "-show_entries", "format=duration",
         path],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace"
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        # fallback: ask ffprobe for duration as plain text
        r2 = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        )
        return float(r2.stdout.strip())

# If a pasted path starts with one of these, we're on Colab with Google Drive
# mounted — output should be saved back into that same Drive folder instead
# of the app's local temp folder, since that's the whole point of Colab.
COLAB_DRIVE_PREFIXES = ("/content/gdrive/MyDrive/", "/content/drive/MyDrive/")

def is_colab_drive_path(path_str: str) -> bool:
    norm = str(path_str).replace("\\", "/")
    return any(norm.startswith(prefix) for prefix in COLAB_DRIVE_PREFIXES)

def make_output_path(input_path: str, job_dir: Path) -> str:
    """
    Every output is named <stem>_removed_<6-char-uuid><ext>.

    Colab / Google Drive path (starts with /content/gdrive/MyDrive/ or
    /content/drive/MyDrive/): saved straight back into that same folder —
    no per-job subfolder needed, the short uuid alone keeps re-runs from
    colliding.

    Anything else: <job_dir>/<stem>_removed_<6-char-uuid><ext> — one shared
    folder per run (single video or a whole batch), inside the app's own
    temp folder, so Gradio is always allowed to serve/download it.
    """
    p        = Path(input_path)
    short_id = uuid.uuid4().hex[:6]
    filename = f"{p.stem}_removed_{short_id}{p.suffix}"

    if is_colab_drive_path(input_path):
        return str(p.parent / filename)

    job_dir.mkdir(parents=True, exist_ok=True)
    return str(job_dir / filename)

def _check_ext(path_str: str):
    ext = Path(path_str).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise gr.Error(f"Unsupported format '{ext}'. Use mp4 / mov / mkv / avi / webm.")

def list_videos_in_dir(dir_path: str) -> list:
    """Top-level supported video files inside a folder, sorted by name."""
    p = Path(dir_path)
    vids = sorted(
        str(f) for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    )
    if not vids:
        raise gr.Error(f"No supported video files found in:\n{dir_path}")
    return vids

def validate_path(raw_path: str) -> list:
    """
    Accepts a path typed/pasted by the user and resolves it to real video
    file(s). Supports both Windows-style ('D:\\folder\\file.mp4') and
    Linux/macOS-style ('/home/user/file.mp4') paths, including the case
    where the string uses the "wrong" separator for the current OS
    (e.g. a Windows path pasted while running on Linux/Colab).

    A file path returns a single-item list; a folder path returns every
    supported video file found directly inside it.
    """
    raw = raw_path.strip().strip('"').strip("'")
    if not raw:
        raise gr.Error("Enter the full path to a video file or a folder of videos.")

    candidates = [raw]
    if "\\" in raw:
        candidates.append(raw.replace("\\", "/"))
    if "/" in raw:
        candidates.append(raw.replace("/", "\\"))

    for candidate in candidates:
        if os.path.isdir(candidate):
            return list_videos_in_dir(candidate)
        if os.path.isfile(candidate):
            _check_ext(candidate)
            return [candidate]

    raise gr.Error(f"Path not found:\n{raw}")

def stage_uploaded_files(uploaded_paths) -> list:
    """
    Copy manually-uploaded (gr.File, multiple) videos into our own local
    temp folder and return the new paths, so the rest of the pipeline can
    treat them exactly like paths typed into the textbox.
    """
    if not uploaded_paths:
        return []
    if isinstance(uploaded_paths, str):
        uploaded_paths = [uploaded_paths]

    session_dir = UPLOAD_ROOT / uuid.uuid4().hex[:10]
    session_dir.mkdir(parents=True, exist_ok=True)

    staged = []
    for up in uploaded_paths:
        src = Path(up)
        if not src.is_file():
            continue
        _check_ext(str(src))
        dest = session_dir / src.name
        shutil.copy2(str(src), str(dest))
        staged.append(str(dest))

    if not staged:
        raise gr.Error("No supported video files were uploaded.")
    return staged

def resolve_video_sources(raw_path: str, uploaded_files) -> list:
    """
    Decide which input to use: a typed/pasted path (file or folder) takes
    priority; otherwise fall back to manually uploaded file(s), staged into
    a local temp folder. Always returns a list of one or more video paths.
    """
    raw_path = (raw_path or "").strip()
    if raw_path:
        return validate_path(raw_path)
    if uploaded_files:
        return stage_uploaded_files(uploaded_files)
    raise gr.Error("Enter a video file/folder path, or upload one or more videos below.")

BACKEND_FFMPEG      = "ffmpeg"
BACKEND_AUTO_EDITOR = "auto-editor"

def _run_ffmpeg_backend(video_path, pause_duration, work_dir, out_path, t0, progress):
    # ── 1. Extract audio ──────────────────────────────────────────────────────
    progress(0.05, desc="Extracting audio…")
    audio_path = work_dir / "audio.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
        str(audio_path)
    ], check=True, capture_output=True,
       encoding="utf-8", errors="replace")

    # ── 2. Detect speech ──────────────────────────────────────────────────────
    progress(0.14, desc="Detecting speech regions…")
    audio  = AudioSegment.from_file(str(audio_path))
    ranges = detect_nonsilent(audio, min_silence_len=100, silence_thresh=-45)

    if not ranges:
        raise gr.Error("No speech detected. Is there audio in this video?")

    # ── 3. Build keep regions ─────────────────────────────────────────────────
    pause_ms = int(pause_duration * 1000)
    orig_ms  = len(audio)
    keeps    = []
    for s_ms, e_ms in ranges:
        ext = min(e_ms + pause_ms, orig_ms)
        if keeps and s_ms <= keeps[-1][1]:
            keeps[-1] = (keeps[-1][0], max(keeps[-1][1], ext))
        else:
            keeps.append((s_ms, ext))

    total = len(keeps)
    progress(0.22, desc=f"Cutting {total} segments…")

    # ── 4. Cut clips ────────────────────────────────────────────────────────────
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    clip_paths = []

    enc_flags = ["-c:v", GPU_ENCODER, "-c:a", "aac"]
    if not IS_GPU:
        enc_flags += ["-preset", "fast", "-crf", "18"]

    for idx, (s_ms, e_ms) in enumerate(keeps):
        progress(0.22 + 0.62 * (idx / total),
                 desc=f"Segment {idx+1} / {total}")
        clip = clips_dir / f"clip_{idx:05d}.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-ss", str(s_ms / 1000.0),
            "-i", video_path,
            "-t", str((e_ms - s_ms) / 1000.0),
            *enc_flags,
            "-avoid_negative_ts", "1",
            str(clip)
        ], check=True, capture_output=True,
           encoding="utf-8", errors="replace")
        clip_paths.append(clip)

    # ── 5. Merge ────────────────────────────────────────────────────────────────
    progress(0.86, desc="Merging clips…")
    concat_txt = work_dir / "concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p}'" for p in clip_paths), encoding="utf-8"
    )

    merged = work_dir / "merged.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt), "-c", "copy", str(merged)
    ], check=True, capture_output=True,
       encoding="utf-8", errors="replace")

    # ── 6. Save into the app's own temp/output folder ───────────────────────────
    progress(0.95, desc="Saving output…")
    shutil.move(str(merged), str(out_path))

    # ── 7. Stats ──────────────────────────────────────────────────────────────
    final_dur = get_duration(str(out_path))
    orig_dur  = orig_ms / 1000.0
    removed   = orig_dur - final_dur
    pct       = max(0, (removed / orig_dur) * 100) if orig_dur else 0

    return dict(
        orig     = fmt(orig_dur),
        final    = fmt(final_dur),
        removed  = fmt(max(removed, 0)),
        segments = total,
        cuts     = total,
        proc     = fmt(time.time() - t0),
        encoder  = GPU_LABEL,
        pct      = pct,
        out_path = str(out_path),
        orig_sec    = orig_dur,
        final_sec   = final_dur,
        removed_sec = max(removed, 0),
    )

def _run_auto_editor_backend(video_path, pause_duration, work_dir, out_path, t0, progress):
    if shutil.which("auto-editor") is None:
        raise gr.Error(
            "auto-editor is not installed. Install it with: pip install auto-editor "
            "(https://pypi.org/project/auto-editor/)"
        )

    progress(0.05, desc="Reading source duration…")
    orig_dur = get_duration(video_path)

    ae_temp_dir = work_dir / "ae_temp"
    ae_temp_dir.mkdir(exist_ok=True)

    cmd = [
        "auto-editor",
        os.path.abspath(video_path),
        "--margin", f"{pause_duration}sec",
        "--no-open",
        "--temp-dir", str(ae_temp_dir),
        "-o", str(out_path),
    ]

    progress(0.2, desc="Running auto-editor…")
    result = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise gr.Error(f"auto-editor failed:\n{result.stderr[-800:] or result.stdout[-800:]}")

    if not out_path.exists():
        raise gr.Error("auto-editor finished but no output file was produced.")

    progress(0.95, desc="Reading output duration…")
    final_dur = get_duration(str(out_path))
    removed   = orig_dur - final_dur
    pct       = max(0, (removed / orig_dur) * 100) if orig_dur else 0

    return dict(
        orig     = fmt(orig_dur),
        final    = fmt(final_dur),
        removed  = fmt(max(removed, 0)),
        segments = "—",
        cuts     = "—",
        proc     = fmt(time.time() - t0),
        encoder  = BACKEND_AUTO_EDITOR,
        pct      = pct,
        out_path = str(out_path),
        orig_sec    = orig_dur,
        final_sec   = final_dur,
        removed_sec = max(removed, 0),
    )

# ── Core ───────────────────────────────────────────────────────────────────────

def process_video(raw_path: str, uploaded_files, pause_duration: float,
                   backend: str, progress=gr.Progress()):
    videos = resolve_video_sources(raw_path, uploaded_files)
    n      = len(videos)

    t_batch0 = time.time()
    job_id   = uuid.uuid4().hex[:10]
    job_dir  = OUTPUT_ROOT / job_id   # shared save folder for this run

    per_video_stats = []

    for idx, video_path in enumerate(videos):
        # work folder lives under the app's own temp root — never the source
        # file's drive, never the OS temp dir
        work_dir = WORK_ROOT / f"{job_id}_{idx}"
        work_dir.mkdir(parents=True, exist_ok=True)
        out_path = Path(make_output_path(video_path, job_dir))

        def sub_progress(frac, desc="", _idx=idx, _n=n):
            tag = f"[{_idx + 1}/{_n}] " if _n > 1 else ""
            progress((_idx + frac) / _n, desc=f"{tag}{desc}")

        try:
            if backend == BACKEND_AUTO_EDITOR:
                stats = _run_auto_editor_backend(video_path, pause_duration, work_dir, out_path, time.time(), sub_progress)
            else:
                stats = _run_ffmpeg_backend(video_path, pause_duration, work_dir, out_path, time.time(), sub_progress)
            stats["name"] = Path(video_path).name
            per_video_stats.append(stats)
        finally:
            # always wipe the temp folder — clips, audio, concat.txt, all gone
            shutil.rmtree(work_dir, ignore_errors=True)

    progress(1.0, desc="Done ✓")

    if n == 1:
        s = per_video_stats[0]
        html = render_stats(s)
        # single video: show the file itself, "Saved to" points at that file
        return html, gr.update(value=s["out_path"], visible=True), s["out_path"]
    else:
        html = render_batch_stats(per_video_stats, str(job_dir), fmt(time.time() - t_batch0))
        # batch: no single file to hand back — point at the shared save folder instead
        return html, gr.update(value=None, visible=False), str(job_dir)


# ── Waveform generator (signature visual) ─────────────────────────────────────
# A small deterministic "waveform" made of bars — used both as an ambient
# idle animation and, after a run, as an actual to-scale picture of how much
# of the timeline was speech (kept, teal) vs silence (removed, coral).

import math

def _wave_heights(n: int, seed: float = 0.0):
    heights = []
    for i in range(n):
        v = (math.sin(i * 0.62 + seed) * 0.5
             + math.sin(i * 0.27 + seed * 1.7) * 0.32
             + math.sin(i * 1.31 + seed * 0.4) * 0.18)
        heights.append(round(14 + (abs(v) * 0.85 + 0.15) * 72, 1))  # 14–86 (%)
    return heights

def build_idle_waveform(n: int = 64) -> str:
    heights = _wave_heights(n, seed=2.1)
    bars = "".join(
        f'<span class="wv-bar wv-idle" style="height:{h}%; animation-delay:{(i%16)*0.07:.2f}s;"></span>'
        for i, h in enumerate(heights)
    )
    return f'<div class="wv-row wv-row-idle">{bars}</div>'

def build_result_waveform(pct_removed: float, n: int = 64) -> str:
    heights   = _wave_heights(n, seed=5.4)
    kept_n    = max(1, round(n * (1 - pct_removed / 100)))
    bars = []
    for i, h in enumerate(heights):
        if i < kept_n:
            bars.append(f'<span class="wv-bar wv-kept" style="height:{h}%; animation-delay:{i*0.012:.2f}s;"></span>')
        else:
            bars.append(f'<span class="wv-bar wv-cut" style="height:{h*0.42:.1f}%; animation-delay:{i*0.012:.2f}s;"></span>')
    return f'<div class="wv-row">{"".join(bars)}</div>'

# ── Stats HTML ─────────────────────────────────────────────────────────────────

def render_stats(s: dict) -> str:
    pct       = s["pct"]
    bar_color = "var(--coral)" if pct >= 25 else "var(--accent)" if pct >= 10 else "var(--muted)"
    enc_color = "var(--teal)" if IS_GPU else "var(--muted)"

    cards = [
        ("Original",   s["orig"],          ""),
        ("Processed",  s["final"],         "card-hi"),
        ("Removed",    s["removed"],        "card-cut"),
        ("Segments",   str(s["segments"]), ""),
        ("Cuts",       str(s["cuts"]),      ""),
        ("Time taken", s["proc"],           ""),
    ]
    card_html = "".join(f"""
      <div class="sc {cls}">
        <span class="sl">{lbl}</span>
        <span class="sv">{val}</span>
      </div>""" for lbl, val, cls in cards)

    # shorten the output path for display: show last 2 parts (job folder + file)
    p     = Path(s["out_path"])
    short = "…/" + "/".join(p.parts[-2:]) if len(p.parts) > 2 else s["out_path"]

    waveform_html = build_result_waveform(pct)

    return f"""
<div class="stats-wrap">
  <div class="stats-header">
    <div class="stats-title-group">
      <span class="status-dot"></span>
      <span class="stats-title">Processing complete</span>
    </div>
    <span class="enc-pill" style="color:{enc_color}; border-color:{enc_color}44;">⚡ {s['encoder']}</span>
  </div>

  <div class="wv-panel">
    {waveform_html}
    <div class="wv-legend">
      <span class="wv-key"><i class="wv-dot wv-dot-kept"></i>Kept</span>
      <span class="wv-key"><i class="wv-dot wv-dot-cut"></i>Removed</span>
      <span class="wv-pct" style="color:{bar_color};">−{pct:.1f}% runtime</span>
    </div>
  </div>

  <div class="sgrid">{card_html}</div>

  <div class="saved-row">
    <span class="saved-label">Saved to</span>
    <span class="saved-path" title="{s['out_path']}">{short}</span>
  </div>
</div>
"""

def render_batch_stats(stats_list: list, job_dir_str: str, proc_total: str) -> str:
    tot_orig    = sum(s["orig_sec"] for s in stats_list)
    tot_final   = sum(s["final_sec"] for s in stats_list)
    tot_removed = max(tot_orig - tot_final, 0)
    tot_pct     = (tot_removed / tot_orig * 100) if tot_orig else 0

    enc_color     = "var(--teal)" if IS_GPU else "var(--muted)"
    encoder_label = stats_list[0]["encoder"] if stats_list else GPU_LABEL
    pct_color     = "var(--coral)" if tot_pct >= 25 else "var(--accent)" if tot_pct >= 10 else "var(--muted)"

    rows = "".join(f"""
      <div class="fr">
        <span class="fr-name" title="{s['name']}">{s['name']}</span>
        <span class="fr-meta">{s['orig']} → {s['final']}</span>
        <span class="fr-pct" style="color:{'var(--coral)' if s['pct'] >= 25 else 'var(--accent)' if s['pct'] >= 10 else 'var(--muted)'};">−{s['pct']:.1f}%</span>
      </div>""" for s in stats_list)

    waveform_html = build_result_waveform(tot_pct)

    p     = Path(job_dir_str)
    short = "…/" + "/".join(p.parts[-2:]) if len(p.parts) > 2 else job_dir_str

    return f"""
<div class="stats-wrap">
  <div class="stats-header">
    <div class="stats-title-group">
      <span class="status-dot"></span>
      <span class="stats-title">{len(stats_list)} videos processed</span>
    </div>
    <span class="enc-pill" style="color:{enc_color}; border-color:{enc_color}44;">⚡ {encoder_label}</span>
  </div>

  <div class="wv-panel">
    {waveform_html}
    <div class="wv-legend">
      <span class="wv-key"><i class="wv-dot wv-dot-kept"></i>Kept</span>
      <span class="wv-key"><i class="wv-dot wv-dot-cut"></i>Removed</span>
      <span class="wv-pct" style="color:{pct_color};">−{tot_pct:.1f}% runtime · batch</span>
    </div>
  </div>

  <div class="sgrid">
    <div class="sc"><span class="sl">Videos</span><span class="sv">{len(stats_list)}</span></div>
    <div class="sc card-hi"><span class="sl">Processed total</span><span class="sv">{fmt(tot_final)}</span></div>
    <div class="sc card-cut"><span class="sl">Removed total</span><span class="sv">{fmt(tot_removed)}</span></div>
    <div class="sc"><span class="sl">Original total</span><span class="sv">{fmt(tot_orig)}</span></div>
    <div class="sc"><span class="sl">Time taken</span><span class="sv">{proc_total}</span></div>
    <div class="sc"><span class="sl">Avg cut</span><span class="sv">{tot_pct:.1f}%</span></div>
  </div>

  <div class="file-list">{rows}</div>

  <div class="saved-row">
    <span class="saved-label">Saved to</span>
    <span class="saved-path" title="{job_dir_str}">{short}</span>
  </div>
</div>
"""

# ── CSS ────────────────────────────────────────────────────────────────────────

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {
  /* surfaces — deep blue-charcoal, never pure black */
  --bg:        #0a0c11;
  --s1:        #12151d;
  --s2:        #171b26;
  --s3:        #1d2330;
  --s4:        #242b3a;
  --border:    #232a3b;
  --border2:   #313a4f;

  /* text */
  --text:      #edf0f7;
  --text-dim:  #aab1c6;
  --muted:     #626b81;

  /* signal palette — amber (engine/controls), teal (kept audio), coral (cut) */
  --accent:      #e2a33d;
  --accent-hi:   #f0b757;
  --accent-lo:   rgba(226,163,61,0.14);
  --teal:        #5fd6c4;
  --teal-lo:     rgba(95,214,196,0.14);
  --coral:       #ff7a6b;
  --coral-lo:    rgba(255,122,107,0.14);

  --r-sm:  7px;
  --r:     12px;
  --r-lg:  18px;
  --grotesk: 'Space Grotesk', sans-serif;
  --mono:    'JetBrains Mono', monospace;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

::selection { background: var(--accent-lo); color: var(--accent-hi); }
:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 2px; }

::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: var(--s1); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }

body, .gradio-container, .gradio-container * {
  font-family: var(--grotesk) !important;
}
body, .gradio-container {
  background:
    radial-gradient(ellipse 900px 500px at 15% -10%, rgba(226,163,61,0.05), transparent 60%),
    radial-gradient(ellipse 900px 600px at 100% 10%, rgba(95,214,196,0.045), transparent 55%),
    var(--bg) !important;
  color: var(--text) !important;
}
.gradio-container { padding: 0 !important; max-width: 100% !important; }
footer { display: none !important; }

/* ══════════════ header ══════════════ */
.app-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.95rem 2rem;
  background: linear-gradient(180deg, var(--s1) 0%, rgba(18,21,29,0.7) 100%);
  border-bottom: 1px solid var(--border);
  position: relative;
}
.app-head::after {
  content: "";
  position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
  background: linear-gradient(90deg, var(--accent) 0%, transparent 22%);
  opacity: 0.5;
}
.head-left { display: flex; align-items: center; gap: 0.8rem; }
.logo-box {
  width: 36px; height: 36px;
  background: linear-gradient(150deg, var(--accent-hi), #b9781f);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.08) inset, 0 6px 16px -6px rgba(226,163,61,0.55);
}
.logo-box svg { width: 18px; height: 18px; }
.logo-name {
  font-family: var(--mono) !important;
  font-size: 1.02rem; font-weight: 700;
  letter-spacing: -0.02em; color: var(--text);
}
.logo-name em { color: var(--accent); font-style: normal; }
.logo-sub { font-size: 0.72rem; color: var(--muted); margin-top: 2px; letter-spacing: 0.01em; }
.gpu-pill {
  font-family: var(--mono) !important;
  font-size: 0.67rem; font-weight: 600;
  padding: 0.32rem 0.75rem;
  border-radius: 999px; border: 1px solid;
  letter-spacing: 0.04em;
  background: rgba(255,255,255,0.02);
}
.head-right { display: flex; align-items: center; gap: 0.6rem; }
.github-pill {
  font-family: var(--mono) !important;
  font-size: 0.67rem; font-weight: 500;
  padding: 0.32rem 0.75rem;
  border-radius: 999px;
  border: 1px solid var(--border2);
  color: var(--text-dim);
  text-decoration: none;
  letter-spacing: 0.02em;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.github-pill:hover {
  border-color: var(--teal);
  color: var(--teal);
  background: var(--teal-lo);
}

/* ══════════════ two-column layout ══════════════ */
.app-body {
  display: grid !important;
  grid-template-columns: 380px 1fr !important;
  min-height: calc(100vh - 68px);
  gap: 0 !important;
}
.left-col {
  background: var(--s1);
  border-right: 1px solid var(--border);
  padding: 1.75rem 1.6rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
  position: relative;
}
.right-col {
  background: transparent;
  padding: 1.75rem 2.2rem 2.2rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

/* ══════════════ signal-chain module labels ══════════════ */
.mod-eyebrow {
  display: flex; align-items: center; gap: 0.55rem;
  margin: 0.15rem 0 0.65rem;
}
.mod-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-lo);
  flex-shrink: 0;
}
.mod-eyebrow span {
  font-family: var(--mono) !important;
  font-size: 0.66rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.14em !important;
  color: var(--muted) !important;
}
.mod-eyebrow small {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: var(--muted);
  opacity: 0.55;
  letter-spacing: 0.06em;
}

/* ══════════════ upload zone (gr.File) ══════════════ */
.gradio-container .upload-container,
.gradio-container div[data-testid="file-upload"] {
  background: var(--s2) !important;
  border: 1.5px dashed var(--border2) !important;
  border-radius: var(--r) !important;
  transition: border-color 0.18s, background 0.18s !important;
}
.gradio-container div[data-testid="file-upload"]:hover {
  border-color: var(--accent) !important;
  background: var(--accent-lo) !important;
}
.gradio-container label[data-testid="block-label"] {
  font-family: var(--mono) !important;
  font-size: 0.63rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.06em !important;
  color: var(--muted) !important;
  background: transparent !important;
}

/* ══════════════ or divider ══════════════ */
.or-divider {
  display: flex; align-items: center; gap: 0.7rem;
  margin: 0.35rem 0 0.1rem;
}
.or-divider .line { flex: 1; height: 1px; background: var(--border); }
.or-divider .word {
  font-family: var(--mono) !important;
  font-size: 0.6rem;
  color: var(--muted);
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

/* ══════════════ inputs ══════════════ */
.path-hint {
  font-family: var(--mono) !important;
  font-size: 0.63rem !important;
  color: var(--muted) !important;
  line-height: 1.55;
  padding: 0.55rem 0.75rem;
  background: var(--s3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  margin-top: 0.45rem;
}
.path-hint b { color: var(--text-dim); font-weight: 500; }

.gradio-container textarea,
.gradio-container input[type=text] {
  background: var(--s2) !important;
  border: 1.5px solid var(--border2) !important;
  border-radius: var(--r-sm) !important;
  color: var(--text) !important;
  font-family: var(--mono) !important;
  font-size: 0.79rem !important;
  padding: 0.65rem 0.85rem !important;
  resize: none !important;
  transition: border-color 0.18s, box-shadow 0.18s !important;
  line-height: 1.5 !important;
}
.gradio-container textarea:focus,
.gradio-container input[type=text]:focus {
  border-color: var(--accent) !important;
  outline: none !important;
  box-shadow: 0 0 0 3px var(--accent-lo) !important;
}
.gradio-container .gr-accordion {
  border: 1px solid var(--border) !important;
  border-radius: var(--r-sm) !important;
  background: var(--s2) !important;
  overflow: hidden;
}
.gradio-container .gr-accordion summary,
.gradio-container .label-wrap {
  font-family: var(--mono) !important;
  font-size: 0.73rem !important;
  font-weight: 600 !important;
  color: var(--text-dim) !important;
  padding: 0.6rem 0.85rem !important;
}

/* ══════════════ divider ══════════════ */
.divider { height: 1px; background: var(--border); margin: 0.15rem 0; }

/* ══════════════ radio (method) ══════════════ */
.gradio-container .wrap.svelte-1p9xokt,
.gradio-container fieldset {
  display: flex !important; gap: 0.5rem !important;
}
.gradio-container label.selected {
  background: var(--accent-lo) !important;
  border-color: var(--accent) !important;
}
.gradio-container fieldset label,
.gradio-container .gr-radio label {
  background: var(--s2) !important;
  border: 1.5px solid var(--border2) !important;
  border-radius: var(--r-sm) !important;
  padding: 0.55rem 0.7rem !important;
  font-family: var(--mono) !important;
  font-size: 0.75rem !important;
  color: var(--text-dim) !important;
  transition: border-color 0.15s, color 0.15s !important;
}

/* ══════════════ slider ══════════════ */
.gradio-container input[type=range] {
  accent-color: var(--accent) !important;
  height: 4px !important;
}
.gradio-container label > span,
.gradio-container span[data-testid="block-info"] {
  font-family: var(--mono) !important;
  font-size: 0.64rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.1em !important;
  color: var(--muted) !important;
}
.gradio-container .gr-form .info,
.gradio-container [data-testid="block-info"] {
  font-size: 0.68rem !important;
  font-weight: 400 !important;
  text-transform: none !important;
  letter-spacing: 0 !important;
  color: var(--muted) !important;
  line-height: 1.45;
}

/* quick picks */
.qp-row { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.65rem; }
.qp {
  font-family: var(--mono) !important;
  font-size: 0.64rem;
  padding: 0.22rem 0.6rem;
  border: 1px solid var(--border2);
  border-radius: 999px;
  color: var(--muted);
  background: var(--s3);
  user-select: none;
}
.qp b { color: var(--text-dim); font-weight: 600; }
.qp.qp-active { border-color: var(--accent); color: var(--accent); background: var(--accent-lo); }
.qp.qp-active b { color: var(--accent); }

/* ══════════════ primary button ══════════════ */
.gradio-container .gr-button-primary {
  width: 100% !important;
  background: linear-gradient(155deg, var(--accent-hi), #cf8e2e) !important;
  color: #1a1206 !important;
  border: none !important;
  border-radius: var(--r) !important;
  font-family: var(--grotesk) !important;
  font-size: 0.95rem !important;
  font-weight: 700 !important;
  padding: 0.85rem 1rem !important;
  letter-spacing: 0.01em !important;
  box-shadow: 0 1px 0 rgba(255,255,255,0.25) inset, 0 10px 24px -10px rgba(226,163,61,0.55) !important;
  transition: transform 0.12s, box-shadow 0.2s, filter 0.15s !important;
  cursor: pointer !important;
}
.gradio-container .gr-button-primary:hover {
  filter: brightness(1.06) !important;
  box-shadow: 0 1px 0 rgba(255,255,255,0.3) inset, 0 14px 30px -10px rgba(226,163,61,0.65) !important;
  transform: translateY(-1px) !important;
}
.gradio-container .gr-button-primary:active { transform: translateY(0) !important; }

/* ══════════════ waveform (signature element) ══════════════ */
.wv-panel {
  background: var(--s2);
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 1rem 1.1rem 0.9rem;
}
.wv-row {
  display: flex;
  align-items: flex-end;
  gap: 2.5px;
  height: 96px;
}
.wv-bar {
  flex: 1;
  min-width: 2px;
  border-radius: 2px 2px 0 0;
}
.wv-kept { background: linear-gradient(180deg, var(--teal), rgba(95,214,196,0.35)); }
.wv-cut  { background: var(--s4); }
.wv-legend {
  display: flex; align-items: center; gap: 1rem;
  margin-top: 0.7rem;
  padding-top: 0.7rem;
  border-top: 1px solid var(--border);
}
.wv-key {
  display: flex; align-items: center; gap: 0.4rem;
  font-family: var(--mono); font-size: 0.65rem;
  color: var(--muted); letter-spacing: 0.03em;
}
.wv-dot { width: 7px; height: 7px; border-radius: 2px; display: inline-block; }
.wv-dot-kept { background: var(--teal); }
.wv-dot-cut  { background: var(--s4); border: 1px solid var(--border2); }
.wv-pct {
  margin-left: auto;
  font-family: var(--mono); font-size: 0.78rem; font-weight: 700;
}

/* idle ambient waveform */
.idle-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.4rem;
  border: 1.5px dashed var(--border2);
  border-radius: var(--r-lg);
  min-height: 320px;
  padding: 2rem;
  color: var(--muted);
  background: radial-gradient(ellipse 500px 260px at 50% 45%, rgba(226,163,61,0.05), transparent 70%);
}
.wv-row-idle {
  width: min(420px, 90%);
  height: 64px;
  gap: 3px;
}
.wv-idle {
  background: linear-gradient(180deg, var(--accent), var(--teal));
  opacity: 0.5;
  animation: wv-breathe 2.4s ease-in-out infinite;
  transform-origin: bottom;
}
@keyframes wv-breathe {
  0%, 100% { transform: scaleY(0.72); opacity: 0.35; }
  50%      { transform: scaleY(1);    opacity: 0.75; }
}
.idle-text { font-size: 0.83rem; letter-spacing: 0.01em; color: var(--text-dim); text-align: center; }
.idle-sub  { font-size: 0.72rem; color: var(--muted); text-align: center; margin-top: -0.7rem; }

@media (prefers-reduced-motion: reduce) {
  .wv-idle, .gradio-container .gr-button-primary { animation: none !important; transition: none !important; }
}

/* ══════════════ stats panel ══════════════ */
.stats-wrap {
  background: var(--s1);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: 1.3rem 1.3rem 1.4rem;
}
.stats-header {
  display: flex; align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.stats-title-group { display: flex; align-items: center; gap: 0.5rem; }
.status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--teal);
  box-shadow: 0 0 0 3px var(--teal-lo);
}
.stats-title {
  font-family: var(--grotesk);
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text);
}
.enc-pill {
  font-family: var(--mono);
  font-size: 0.63rem; font-weight: 600;
  padding: 0.22rem 0.6rem;
  border-radius: 999px; border: 1px solid;
  letter-spacing: 0.04em;
}
.sgrid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.6rem;
  margin: 1rem 0;
}
.sc {
  background: var(--s2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 0.7rem 0.85rem;
  display: flex; flex-direction: column; gap: 0.25rem;
}
.sc.card-hi  { border-color: rgba(226,163,61,0.4); }
.sc.card-cut { border-color: rgba(255,122,107,0.35); }
.sl {
  font-family: var(--mono);
  font-size: 0.58rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.sv {
  font-family: var(--mono);
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text);
}
.card-hi .sv  { color: var(--accent-hi); }
.card-cut .sv { color: var(--coral); }

/* saved path */
.saved-row {
  display: flex; align-items: flex-start; gap: 0.6rem;
  background: var(--s2);
  border: 1px solid var(--border2);
  border-radius: var(--r-sm);
  padding: 0.65rem 0.85rem;
}
.saved-label {
  font-family: var(--mono);
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  flex-shrink: 0;
  padding-top: 2px;
}
.saved-path {
  font-family: var(--mono);
  font-size: 0.73rem;
  color: var(--teal);
  word-break: break-all;
  line-height: 1.5;
}

/* batch file list */
.file-list {
  display: flex; flex-direction: column; gap: 0.4rem;
  margin-bottom: 1rem;
  max-height: 230px;
  overflow-y: auto;
  padding-right: 2px;
}
.fr {
  display: flex; align-items: center; gap: 0.7rem;
  background: var(--s2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 0.55rem 0.75rem;
}
.fr-name {
  font-family: var(--mono); font-size: 0.72rem; color: var(--text-dim);
  flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fr-meta { font-family: var(--mono); font-size: 0.67rem; color: var(--muted); flex-shrink: 0; }
.fr-pct  { font-family: var(--mono); font-size: 0.7rem; font-weight: 700; flex-shrink: 0; width: 54px; text-align: right; }

/* output file component */
.gradio-container div[data-testid="file-upload"] a,
.gradio-container .file-preview {
  color: var(--teal) !important;
}

/* saved-to textbox (readonly) */
.saved-box textarea {
  color: var(--teal) !important;
  font-size: 0.75rem !important;
}

/* footer credit */
.app-footer {
  text-align: center;
  padding: 0.85rem 1rem;
  font-family: var(--mono);
  font-size: 0.68rem;
  letter-spacing: 0.02em;
  color: var(--muted);
  border-top: 1px solid var(--border);
  background: var(--s1);
}
.app-footer a {
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
}
.app-footer a:hover { color: var(--accent-hi); text-decoration: underline; }

/* block cleanup */
.gradio-container .gr-block,
.gradio-container .gr-box,
.gradio-container .gr-panel {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
}
.gradio-container .gr-form { background: transparent !important; border: none !important; }
"""

# ── Header ─────────────────────────────────────────────────────────────────────

def build_header() -> str:
    pill_color = "#5fd6c4" if IS_GPU else "#626b81"
    icon       = "⚡" if IS_GPU else "💻"
    return f"""
<div class="app-head">
  <div class="head-left">
    <div class="logo-box">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 12h3l2-7 3 14 3-11 2 4h7" stroke="#1a1206" stroke-width="2.1"
              stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div>
      <div class="logo-name">silence<em>.remove</em></div>
      <div class="logo-sub">Local silence trimmer — no upload required, works on your files directly</div>
    </div>
  </div>
  <div class="head-right">
    <a class="github-pill" href="https://github.com/NeuralFalconYT/Remove-Silence-From-Video"
       target="_blank" rel="noopener noreferrer">
      ⧉ Run Locally on GitHub
    </a>
    <span class="gpu-pill" style="color:{pill_color}; border-color:{pill_color}55;">
      {icon} {GPU_LABEL}
    </span>
  </div>
</div>
"""

# ── Gradio UI ──────────────────────────────────────────────────────────────────

with gr.Blocks(css=CSS, title="silence.remove") as demo:

    gr.HTML(build_header())

    with gr.Row(elem_classes=["app-body"]):

        # ── LEFT COLUMN ────────────────────────────────────────────────────────
        with gr.Column(elem_classes=["left-col"]):

            gr.HTML('<div class="mod-eyebrow"><span class="mod-dot"></span><span>01 · Source</span><small>video(s) in</small></div>')

            video_file_input = gr.File(
                label="Upload video(s)",
                file_types=list(SUPPORTED_EXTS),
                file_count="multiple",
                type="filepath",
            )

            gr.HTML('<div class="or-divider"><div class="line"></div><span class="word">or paste a path</span><div class="line"></div></div>')

            with gr.Accordion("Run locally on a file or folder path", open=False):
                with gr.Column(elem_classes=["path-wrap"]):
                    video_path_input = gr.Textbox(
                        label="Video file or folder path",
                        placeholder='D:\\Videos\\example.mp4   or   D:\\Videos\\my_folder\n/content/drive/MyDrive/example.mp4   or   /content/drive/MyDrive/videos',
                        lines=2,
                        max_lines=3,
                    )
                    gr.HTML("""
<div class="path-hint">
  <b>Paste the full path</b> to a video file, or to a <b>folder</b> — every
  supported video inside it will be processed.<br>
  Windows (<b>D:\\folder\\file.mp4</b>) and Linux (<b>/home/user/file.mp4</b>) paths both work.
</div>""")

            gr.HTML('<div class="divider"></div>')
            gr.HTML('<div class="mod-eyebrow"><span class="mod-dot"></span><span>02 · Engine</span><small>silence detector</small></div>')

            backend_radio = gr.Radio(
                choices=[BACKEND_FFMPEG, BACKEND_AUTO_EDITOR],
                value=BACKEND_FFMPEG,
                show_label=False,
            )

            gr.HTML('<div class="divider"></div>')
            gr.HTML('<div class="mod-eyebrow"><span class="mod-dot"></span><span>03 · Threshold</span><small>pause length</small></div>')

            with gr.Column():
                pause_slider = gr.Slider(
                    minimum=0.05, maximum=2.0, step=0.05, value=0.2,
                    label="Minimum pause duration (seconds)",
                    info="Silence kept between speech segments after trimming — also used as --margin for auto-editor"
                )
                gr.HTML("""
<div class="qp-row">
  <span class="qp"><b>0.1s</b> tight</span>
  <span class="qp qp-active"><b>0.2s</b> default</span>
  <span class="qp"><b>0.5s</b> relaxed</span>
  <span class="qp"><b>1.0s</b> natural</span>
</div>""")

            gr.HTML('<div class="divider"></div>')

            process_btn = gr.Button("▶  Remove silence", variant="primary")

        # ── RIGHT COLUMN ───────────────────────────────────────────────────────
        with gr.Column(elem_classes=["right-col"]):
            result_html = gr.HTML(f"""
<div class="idle-box">
  {build_idle_waveform()}
  <div class="idle-text">Your trimmed timeline will appear here</div>
  <div class="idle-sub">Add one or more videos (or a folder) and press Remove silence</div>
</div>
""")
            result_file = gr.File(label="Download processed video", visible=True)
            result_path_box = gr.Textbox(
                label="Saved to",
                interactive=False,
                elem_classes=["saved-box"],
                placeholder="Output path will appear here after processing",
                show_copy_button=True
            )

    gr.HTML(
        '<div class="app-footer">silence.remove — runs 100% locally, nothing leaves your machine · '
        'made by <a href="https://github.com/NeuralFalconYT" target="_blank" rel="noopener noreferrer">@NeuralFalcon</a></div>'
    )

    process_btn.click(
        fn=process_video,
        inputs=[video_path_input, video_file_input, pause_slider, backend_radio],
        outputs=[result_html, result_file, result_path_box],
    )

if __name__ == "__main__":
    _allowed = [str(APP_TEMP_ROOT)]
    for _prefix in COLAB_DRIVE_PREFIXES:
        _root = _prefix.split("MyDrive/")[0] + "MyDrive"
        if os.path.isdir(_root) and _root not in _allowed:
            _allowed.append(_root)
    demo.launch(allowed_paths=_allowed,debug=False,share=False)

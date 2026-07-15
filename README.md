# 🔇 silence.remove

A simple, free, open-source tool that automatically removes silence from your videos — runs entirely on your own computer, no upload, no watermark, no subscription.


<img width="713" height="383" alt="app" src="https://github.com/user-attachments/assets/a934b672-0eab-492a-8986-0652f071b023" />


---

## Why this exists

Most "remove silence from video" tools online are paid, subscription-based, or watermark your export unless you pay. This project exists so small YouTubers, podcasters, and content creators can trim the dead air out of their videos for free, using open-source tools (`ffmpeg` and `auto-editor`) under the hood — nothing premium, nothing locked behind a paywall.

If you're a small creator who just wants a straightforward "cut the silence" button without paying for editing software, this is for you.

---

## What it does

- Detects silent gaps in your video's audio and cuts them out
- Keeps a small configurable pause between speech segments, so cuts don't feel jarring
- Two engines to choose from:
  - **ffmpeg** — built into this app, fast, good for most talking-head/podcast style videos
  - **auto-editor** — a more advanced open-source silence/motion-based editor
- Works on a single video, or a whole folder of videos at once (batch mode)
- Shows you a before/after waveform and stats (original length, final length, % removed, etc.)
- Everything happens locally on your machine — your video is never uploaded anywhere

---

## Requirements

- **Windows, macOS, or Linux**
- **Python 3.10** (this project was built and tested on Python 3.10.0)
- **ffmpeg** (audio/video processing engine)
- Python packages: `gradio==5.50.0`, `auto-editor==29.3.1`, `pydub`

---

## 🪟 Windows — Easy Automatic Install (recommended)

If you're on Windows, you don't need to install anything by hand. Just run the installer script.

### Steps

1. Download/clone this project folder to your computer.
2. Make sure you have **Python 3.10** installed:
   - Get it here: https://www.python.org/downloads/release/python-3100/
   - ⚠️ During installation, tick the box **"Add Python to PATH"** — this matters, don't skip it.
3. Inside the project folder, double-click **`install.bat`**.

That's it. The script will automatically:
- Create a private virtual environment (`venv`) just for this app, so it won't mess with anything else on your system
- Install `gradio`, `auto-editor`, and `pydub` into that environment
- Check if `ffmpeg` is installed — if not, it will try to install it for you (via `winget`, or by downloading it directly if `winget` isn't available)
- Launch the app automatically once setup is done

After the first install, to run the app again later, just double-click **`run.bat`** — it's faster since it skips the setup steps.

> **Note:** If `ffmpeg` gets installed via `winget` and the app still can't find it on the very first run, close the window, open a **new** terminal/command prompt, and run `run.bat` again. Windows sometimes needs a fresh terminal to notice the updated PATH.

---

## 🐧🍎 macOS / Linux — Manual Install

The automatic `.bat` installer is Windows-only. On Mac/Linux, set it up manually — it only takes a few commands.

### 1. Install Python 3.10

- **macOS**: `brew install python@3.10`
- **Ubuntu/Debian**: `sudo apt install python3.10 python3.10-venv`

### 2. Install ffmpeg

- **macOS**: `brew install ffmpeg`
- **Ubuntu/Debian**: `sudo apt install ffmpeg`
- **Other Linux**: use your distro's package manager, or download a static build from https://ffmpeg.org/download.html

Check it worked:
```bash
ffmpeg -version
```

### 3. Set up the project

```bash
# go into the project folder
cd silence-remove

# create a virtual environment
python3.10 -m venv venv

# activate it
source venv/bin/activate

# install the dependencies
pip install -r requirements.txt
```

### 4. Run the app

```bash
python app.py
```

---

## How to install ffmpeg manually (any OS, if the auto-installer can't)

If the automatic install ever fails, here's how to do it by hand:

1. Go to https://ffmpeg.org/download.html
2. Download a build for your OS (on Windows, the [gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/) are a popular choice — grab the "essentials" build)
3. Unzip it somewhere permanent, e.g. `C:\ffmpeg`
4. Add the `bin` folder inside it (e.g. `C:\ffmpeg\bin`) to your system PATH:
   - Windows: Start Menu → search "Edit the system environment variables" → Environment Variables → edit `Path` → add the folder → OK
   - macOS/Linux: add `export PATH="$PATH:/path/to/ffmpeg/bin"` to your `~/.zshrc` or `~/.bashrc`
5. Open a **new** terminal and check it worked: `ffmpeg -version`

---

## How to use the app

1. Start the app (`run.bat` on Windows, or `python app.py` on Mac/Linux). It opens a local web page in your browser (usually `http://127.0.0.1:7860`).
2. Add your video(s):
   - Either **upload** one or more video files directly, or
   - **Paste a file or folder path** (works with both Windows-style `D:\Videos\clip.mp4` and Linux-style `/home/user/clip.mp4` paths). Pasting a folder path processes every supported video inside it in one batch.
3. Pick your **engine**: `ffmpeg` (default, fast) or `auto-editor`.
4. Adjust the **minimum pause duration** slider — this is how much silence is kept between speech segments after trimming. Lower = tighter cuts, higher = more natural breathing room. Default `0.2s` works well for most talking videos.
5. Click **▶ Remove silence**.
6. When it's done, you'll see stats (original length, new length, % removed, time taken) plus a link to download the trimmed video, or the folder it was saved into if you processed a batch.

Supported video formats: `.mp4 .mov .mkv .avi .webm .m4v`

---

## Notes

- All processing happens locally — nothing is uploaded to any server.
- If you have an NVIDIA GPU with NVENC support, the app will automatically detect and use it for faster encoding. Otherwise it falls back to CPU encoding (`libx264`).
- Temporary work files are stored in a `sr_app_temp` folder next to `app.py` and are cleaned up automatically after each run; final outputs stay in `sr_app_temp/outputs`.

---

## Credits

Built by [@NeuralFalcon](https://github.com/NeuralFalconYT) — made as a free, open-source alternative to paid silence-removal tools, for small creators who just need a simple tool that works.

If this saved you some money or time, a ⭐ on the repo is appreciated.

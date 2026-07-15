# 🔇 silence.remove

A free, open-source tool that automatically removes silence from videos.

No subscriptions. No watermarks. No uploads. Your videos never leave your computer.

Supports both:

* 🪟 **Windows Desktop App (Recommended)**
* 🌐 **Gradio Web App**


---

## 🪟 Windows Desktop App

<p align="center">
<img width="595" alt="Windows App" src="https://github.com/user-attachments/assets/edfb2c76-706e-48d3-aa28-71913e603ec1">
</p>

<p align="center">
<i>Native Windows desktop application (Tkinter)</i>
</p>

---

## 🌐 Gradio Web App

<p align="center">
<img width="713" alt="Gradio App" src="https://github.com/user-attachments/assets/a934b672-0eab-492a-8986-0652f071b023">
</p>

<p align="center">
<i>Browser-based interface (Gradio)</i>
</p>

---

# Why I made this

Most "Remove Silence" tools are locked behind subscriptions, limit exports, or add watermarks unless you pay.

I wanted something anyone could use completely free.

This project is built on top of the amazing open-source projects **FFmpeg** and **Auto-Editor** to give creators a simple one-click solution.

Perfect for:

* YouTubers
* Podcasters
* Streamers
* Teachers
* Students
* Anyone editing talking videos

Everything runs **100% locally**.

Your videos are **never uploaded anywhere**.

---

# Features

✅ Remove silence automatically

✅ Desktop application (Windows)

✅ Gradio Web UI

✅ Batch process entire folders

✅ Before / After statistics

✅ Before / After waveform

✅ Adjustable pause between speech

✅ NVIDIA GPU (NVENC) support

✅ CPU fallback

✅ Completely offline

---

# Supported Formats

```
.mp4
.mov
.mkv
.avi
.webm
.m4v
```

---

# Requirements

* Python 3.10
* FFmpeg
* Windows / Linux / macOS

Python packages

```
gradio
pillow
pydub
auto-editor
```

---

# 🪟 Windows Installation (Recommended)

If you're on Windows, this is the easiest method.

You only need to do this once.

---

## Step 1 — Download the project

You have **two options**.

### Option A — Download ZIP (Recommended for beginners)

1. Open this GitHub repository.
2. Click the green **Code** button.
3. Click **Download ZIP**.
4. Wait for the download to finish.
5. Right-click the ZIP file.
6. Click **Extract All...**
7. Open the extracted folder.

That's it.

---

### Option B — Clone with Git

If you already have Git installed:

```bash
git clone https://github.com/NeuralFalconYT/Remove-Silence-From-Video.git
```

Then:

```bash
cd Remove-Silence-From-Video
```

---

## Step 2 — Install Python

Download Python 3.10

https://www.python.org/downloads/release/python-3100/

During installation:

✅ Check

```
Add Python to PATH
```

before clicking **Install**.

This is very important.

---

## Step 3 — Run the installer

Inside the project folder:

Double-click

```
install.bat
```

The installer will automatically:

* Create a private virtual environment
* Install all required Python packages
* Install FFmpeg if needed
* Launch the application

No manual setup required.

---

## Step 4 — Run the app later

After installation is complete,

simply double-click

```
run.bat
```

Choose:

```
1. Windows Desktop App (Recommended)
2. Gradio Web App
```

If you simply press **Enter**, the Desktop App launches automatically.

---

# 🍎 Linux / macOS Installation

## 1. Clone the repository

```bash
git clone https://github.com/NeuralFalconYT/Remove-Silence-From-Video.git

cd Remove-Silence-From-Video
```

Or download the ZIP from GitHub and extract it.

---

## 2. Install Python 3.10

macOS

```bash
brew install python@3.10
```

Ubuntu

```bash
sudo apt install python3.10 python3.10-venv
```

---

## 3. Install FFmpeg

macOS

```bash
brew install ffmpeg
```

Ubuntu

```bash
sudo apt install ffmpeg
```

Verify installation

```bash
ffmpeg -version
```

---

## 4. Create a virtual environment

```bash
python3.10 -m venv venv
```

Activate it

macOS/Linux

```bash
source venv/bin/activate
```

---

## 5. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 6. Run

Desktop version

```bash
python windows.py
```

Gradio version

```bash
python app.py
```

---

# How to Use

## Step 1

Launch the application.

Windows:

```
run.bat
```

Linux/macOS

```
python windows.py
```

or

```
python app.py
```

---

## Step 2

Select one or more videos.

Or choose an entire folder.

---

## Step 3

Choose an engine.

### FFmpeg

* Fast
* Recommended
* Great for most videos

### Auto-Editor

* More advanced
* Better for difficult videos
* Slightly slower

---

## Step 4

Adjust the pause duration.

Default:

```
0.20 seconds
```

Smaller value

```
Faster cuts
```

Larger value

```
More natural pauses
```

---

## Step 5

Click

```
Remove Silence
```

Wait for processing.

---

## Step 6

Done!

You'll see:

* Original duration
* New duration
* Time removed
* Percentage removed
* Processing time
* Output folder

---

# FFmpeg Manual Installation

If automatic installation fails:

Download

https://ffmpeg.org/download.html

Windows users can use

https://www.gyan.dev/ffmpeg/builds/

Download

```
ffmpeg-release-essentials.zip
```

Extract it somewhere permanent

Example

```
C:\ffmpeg
```

Add

```
C:\ffmpeg\bin
```

to your Windows PATH.

Restart Command Prompt.

Verify

```bash
ffmpeg -version
```

---

# NVIDIA GPU Support

If your PC supports NVIDIA NVENC,

the application automatically uses GPU encoding.

Otherwise,

it automatically falls back to CPU encoding.

No configuration required.

---

# Temporary Files

Temporary processing files are stored in

```
sr_app_temp
```

They are automatically deleted after processing.

Finished videos remain inside

```
sr_app_temp/outputs
```

(or your chosen output folder).

---

# Built With

* FFmpeg
* Auto-Editor<img width="595" height="407" alt="windows" src="https://github.com/user-attachments/assets/67912548-1a2b-42de-bd8a-b298200fbe3c" />

* Gradio
* Tkinter
* Pillow
* Pydub

---

# License

This project is open source.

Feel free to use it, improve it, and contribute.

---

# Credits

Created by

**NeuralFalcon**

GitHub:

https://github.com/NeuralFalconYT

If this project helped you save time, consider giving the repository a ⭐.

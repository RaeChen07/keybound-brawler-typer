# Keybound Brawler Auto Typer · FFXIV × FFVII Typing Event Bot

**English** | [中文](README.zh-CN.md)

An auto typer for **Keybound Brawler**, the typing minigame from the Final Fantasy XIV × Final Fantasy VII Remake collaboration. It takes screenshots, reads the words above the enemies with OCR, then types each word and presses Enter.

> ⚠️ **Disclaimer**: Using third-party tools to automate gameplay violates the Square Enix User Agreement and may get your account penalized. This project is for learning about OCR and screen automation. Use it at your own risk.

## About the event

| | |
|---|---|
| Name | Keybound Brawler (typing minigame; its first collaboration is with the FINAL FANTASY VII REMAKE series) |
| Start | October 28, 2026 |
| Duration | Until the *Evercold* expansion launches (planned for January 2027), then returns at irregular intervals |
| Location | Keybound Square, a new area of the Manderville Gold Saucer |
| Gameplay | Four-player party. Type the word above an enemy to attack it, clear wave after wave, then fight a boss (e.g. Airbuster) |
| Requirements | Level 15+, Gold Saucer unlocked, the limited-time quest "Keyward Bound". **A keyboard is required** |
| Rewards | Spend MGC on Tifa / Barret (Avalanche) outfits, the Avalanche Gatling Gun fashion accessory, a Magitek Scorpion mount, a Wind-up Barret minion, the /magitype emote, orchestrion rolls, a portrait framer's kit and more |

The bigger part of the crossover is *Beyond the Lifestream*, an 8-player raid series in *Evercold* that both development teams made together.

Sources: [FFXIV Console Games Wiki](https://ffxiv.consolegameswiki.com/wiki/Keybound_Brawler), [Nova Crystallis](https://novacrystallis.com/2026/10/keybound-brawler-event-arrives-in-final-fantasy-xiv-on-october-28-featuring-the-final-fantasy-vii-remake-series/), [MMOHuts](https://mmohuts.com/news/final-fantasy-xiv-adds-a-typing-event-with-final-fantasy-vii-remake-rewards-on-october-28)

## Features

- **Order by label color**: red, gold and green labels first, then blue. Within a color, it types the closest (lowest on screen) word first. It skips gray labels and text drawn straight on the background (boss skill names, the red warning banner, etc.)
- **No-typing sign**: when the red prohibition sign appears, it stops typing after 3 seconds and resumes 3 seconds after the sign is gone. If this happens mid-word, it pauses and then finishes the word
- **I / l confusion**: these look identical in the game font. The first letter of a line is tried as `i`, any other position as `l`. If the word doesn't clear, the next spelling is tried. These words are typed after the others
- **Focus safety**: keyboard input is sent only while the foreground process is `ffxiv_dx11.exe` or `ffxiv.exe`. Switching to another application suspends typing until FFXIV is focused again
- Types spaces and punctuation. Case doesn't matter, so everything is typed in lowercase
- Reads only the middle of the screen and ignores HP, score, chat icons, player names and the input box

## Usage

### Option 1: exe (no Python needed)

Download `typer_bot.exe` from [Releases](../../releases), double-click it, then switch back to the game within 3 seconds.

### Option 2: run with Python

Requires Windows and Python 3.9–3.12.

```bash
python -m pip install -r requirements.txt
python typer_bot.py
```

### Console language / 控制台语言

Console output is available in English and Simplified Chinese. By default, `--lang auto` selects Chinese for Chinese system locales and English otherwise. You can override it when running the Python script **or the packaged exe**:

```bash
python typer_bot.py --lang en
python typer_bot.py --lang zh
python typer_bot.py --lang auto
```

For the executable, use `typer_bot.exe --lang en` (or `zh`). The screenshot test mode also respects `--lang`.

### Hotkeys

- **F8**: pause / resume
- **F9**: quit

### Notes

- The game must be **fullscreen** on the **primary monitor** (the detection area is set as a fraction of the screen)
- If the game runs as administrator, run the script / exe as administrator too, or the keys won't reach the game
- Antivirus software may flag the packaged exe as a false positive

## Debugging

Take a full-screen screenshot, then run:

```bash
python typer_bot.py --test screenshot.png
```

It prints the words it found, their colors and whether a no-typing sign is present, and saves `debug.png` (green box = detection area, red box = ignored input box).

The main settings are at the top of `typer_bot.py`:

| Setting | What it does |
|---|---|
| `REGION` | Detection area (left, top, right, bottom as fractions of the screen) |
| `IGNORE_BANDS` | Horizontal bands cut out of the detection area (the input box) |
| `BEFORE_TYPE` / `KEY_DELAY` / `SHIFT_DELAY` | Typing speed. Increase them if the game drops keys |
| `SIGN_DELAY` / `SIGN_WAIT` | How long after the sign appears to stop / after it disappears to resume |
| `MONITOR` | Which monitor to capture |

## Building the exe

```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --console --name typer_bot --collect-all rapidocr_onnxruntime --collect-binaries onnxruntime typer_bot.py
```

Build in a clean virtual environment with only `requirements.txt` installed. Otherwise the exe will bundle every other large library on your machine.

## How it works

1. [mss](https://github.com/BoboTiG/python-mss) captures the screen
2. [RapidOCR](https://github.com/RapidAI/RapidOCR) (ONNX Runtime) reads the text
3. The color of a thin ring around each word decides the label color. OpenCV contour detection finds the no-typing sign
4. Windows `SendInput` sends keys as scan codes, so DirectX games receive them

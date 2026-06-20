# SM2 Map Overlay

A lightweight Windows overlay that displays community-made minimaps for
**Warhammer 40,000: Space Marine 2**. The overlay reads the current mission
name from the screen with OCR and shows the matching map on top of the game.

Maps are created by **[KimberPrime](https://www.kimberprime.com/)** — visit the
site for interactive versions.

---

## Features

- Automatic mission detection via on-screen OCR (Tesseract).
- Per-map scale and position, saved automatically.
- Three display modes: hold-to-show, always-on, or toggle.
- Keyboard **and** gamepad shortcut, configurable.
- Multi-monitor aware scan-area detection.
- Auto-downloads new maps from this repository when they are released.
- Dark, tabbed settings UI with a built-in debug panel.

---

## Installation

1. Download `detector.exe` from the [Releases](../../releases) page.
2. Run it. That's it — Tesseract OCR and everything else is bundled inside.

On first launch a setup window asks for your language, game resolution,
shortcut, and display mode. The app then creates a `Data/` folder next to the
exe for its config, log, and downloaded maps:

```
detector.exe
└── Data/                   ← created automatically on first run
    ├── config.json
    ├── sm2_detector.log
    └── maps/               ← maps download here automatically
```

> The app lives in the system tray. Right-click the tray icon → **Settings**
> to open the configuration window, or **Quit** to exit.

---

## Usage

| Mode | Behaviour |
|------|-----------|
| **Hold** | Map is visible only while the assigned key/button is held. |
| **Always** | Map is shown whenever the game is the active window. |
| **Toggle** | The assigned key/button switches the map on and off. |

Open the in-game mission/loadout screen so the mission name is visible, then
trigger your shortcut. The overlay scans the name and shows the map.

The default scan area (top-left, `1001×145` at 2560×1440) matches the mission
title position. If your HUD differs, open **Settings → Detection → Capture
Area** to draw a new region, or **Auto Detect** to recompute it from your
monitor resolution.

---

## Configuration files

Everything the app writes lives in the `Data/` folder beside the exe:

- `config.json` — all settings. Delete it to reset the app to first-run state.
- `sm2_detector.log` — rolling diagnostic log.
- `maps/` — downloaded map images.

---

## Adding / updating maps (maintainers)

The app reads `maps_list.json` from the repository root to learn which mission
names map to which image files:

```json
{
    "inferno": "map_inferno.jpg",
    "decapitation": "map_decapitation.jpg"
}
```

To add a new map:

1. Add the image (`map_<name>.jpg`, under 5000×5000 px, ideally < 5 MB) to the
   `maps/` folder of this repository.
2. Add a `"mission name": "filename.jpg"` entry to `maps_list.json`.
3. Commit and push.

The next time any user launches the app with an internet connection, the new
entry and image are downloaded automatically — no app update required.

---

## Building from source

Requires Python 3.10+ on Windows.

```powershell
pip install pytesseract pillow opencv-python-headless keyboard pystray ^
            pygetwindow pyautogui XInput-Python psutil mss pyinstaller

pyinstaller --noconfirm build.spec
```

Before building, place a **trimmed** `Tesseract-OCR/` folder next to
`build.spec`. Keep only `tesseract.exe`, its DLLs, and
`tessdata/eng.traineddata` — deleting the other ~100 language files is what
keeps the final exe under 100 MB. Use `opencv-python-headless` (not
`opencv-python`) for the same reason.

The build produces a single self-contained `dist/detector.exe` with Tesseract
and all assets bundled inside — users download nothing else.

---

## Credits

- Maps by **[KimberPrime](https://www.kimberprime.com/)**.
- OCR by **[Tesseract](https://github.com/tesseract-ocr/tesseract)**.

## License

Released as open source. See [LICENSE](LICENSE) for details.

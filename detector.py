"""SM2 Map Overlay — detector.py"""
import tkinter as tk
from tkinter import ttk, simpledialog
from PIL import Image, ImageTk, ImageDraw, ImageFont
import keyboard, pystray, webbrowser
from pystray import MenuItem as item
import pygetwindow as gw, pyautogui, cv2, numpy as np
import threading, traceback, os, sys, json, time, difflib, urllib.request, re
from collections import deque
from datetime import datetime

try: import pytesseract;  OCR_AVAILABLE   = True
except: OCR_AVAILABLE   = False
try: import XInput;       XINPUT_AVAILABLE = True
except: XINPUT_AVAILABLE = False
try: import psutil;       PSUTIL_AVAILABLE = True
except: PSUTIL_AVAILABLE = False
try: import mss;          MSS_AVAILABLE   = True
except: MSS_AVAILABLE   = False

MAX_IMAGE_PX = 5000

# ── GitHub update config ───────────────────────────────────────────────────────
GITHUB_RAW    = "https://raw.githubusercontent.com/MentorDW/SM2MapOverlay/main"
MAPS_LIST_URL = f"{GITHUB_RAW}/maps_list.json"

# ── Palette ────────────────────────────────────────────────────────────────────
C = dict(
    bg="#1a1b26", sidebar="#13141c", card="#24253a",
    accent="#4a9eff", accent_dim="#2d5fa0",
    text="#c8cce8", text_dim="#5a6080",
    hover="#2a2b3d", border="#2d2e45", inp="#2d2e45",
    tab_act="#1e1f30", red="#c0392b", green="#7ece8a",
)

def _font(size=10, bold=False):
    return ("Segoe UI", size, "bold" if bold else "normal")

# ── Folder structure ────────────────────────────────────────────────────────────
def _app_dir():
    return os.path.dirname(sys.executable) if getattr(sys,"frozen",False) else os.path.abspath(".")

def _data_dir():
    d = os.path.join(_app_dir(), "Data"); os.makedirs(d, exist_ok=True); return d

def _maps_dir():
    d = os.path.join(_data_dir(), "maps"); os.makedirs(d, exist_ok=True); return d

def resource_path(rel):  # map images
    return os.path.join(_maps_dir(), rel)

def user_data_path(rel):  # config, logs
    return os.path.join(_data_dir(), rel)

CONFIG_FILE     = user_data_path("config.json")
LOG_FILE        = user_data_path("sm2_detector.log")
KIMBERPRIME_URL = "https://www.kimberprime.com/"
GAME_EXE        = "Warhammer 40000 Space Marine 2 - Retail.exe"
GAME_WORDS      = ["Space Marine 2", "Warhammer 40000"]

# Messages logged before LOGGER exists are buffered here and flushed later.
LOGGER_DELAYED = []

def _configure_tesseract():
    """Locate the Tesseract-OCR engine and configure pytesseract.

    Tesseract is bundled INSIDE the one-file exe, so when frozen it is
    unpacked into the temporary _MEIPASS directory. When running the .py
    directly it sits next to the script. Both cases are handled here.
    """
    if not OCR_AVAILABLE:
        return False
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "Tesseract-OCR"))
    candidates.append(os.path.join(_app_dir(), "Tesseract-OCR"))
    candidates.append(os.path.join(os.path.abspath("."), "Tesseract-OCR"))
    for base in candidates:
        exe = os.path.join(base, "tesseract.exe")
        if os.path.exists(exe):
            pytesseract.pytesseract.tesseract_cmd = exe
            tessdata = os.path.join(base, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata
            LOGGER_DELAYED.append(f"Tesseract found: {exe}")
            return True
    LOGGER_DELAYED.append("Tesseract NOT found in any candidate path")
    return False

_configure_tesseract()

# ── Reference geometry ─────────────────────────────────────────────────────────
_REF_W, _REF_H     = 2560, 1440
_RIGHT_ZONE_REF    = dict(x=1707, y=108, w=823, h=997)
_LEFT_ZONE_REF     = dict(x=111,  y=856, w=689, h=532)
_BFIELD_CHECK_REF  = dict(x=900,  y=85,  w=550, h=80)
_SCAN_W, _SCAN_H   = 1001, 145

def _sz(z, gw, gh):
    sx,sy=gw/_REF_W,gh/_REF_H
    return {k:int(v*(sx if k in("x","w") else sy)) for k,v in z.items()}

def default_scan(gw, gh):
    return dict(reg_x=0,reg_y=0,reg_w=int(_SCAN_W*gw/_REF_W),reg_h=int(_SCAN_H*gh/_REF_H))

def calc_map_pos(iw, ih, gw, gh, use_left=False):
    z=_sz(_LEFT_ZONE_REF if use_left else _RIGHT_ZONE_REF,gw,gh)
    sf=min(z["w"]/max(iw,1),z["h"]/max(ih,1))
    return round(sf*100,2), int(z["x"]+(z["w"]-iw*sf)/2), int(z["y"]+(z["h"]-ih*sf)/2)

# ══════════════════════════════════════════════════════════════════════════════
# LOGGER
# ══════════════════════════════════════════════════════════════════════════════
class AppLogger:
    def __init__(self):
        self._lines=deque(maxlen=600); self._listeners=[]; self._lock=threading.Lock()
        try:
            import logging
            fh=logging.FileHandler(LOG_FILE,encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            fl=logging.getLogger("SM2"); fl.setLevel(logging.DEBUG); fl.addHandler(fh)
            self._fl=fl
        except: self._fl=None
    def log(self,msg,level="INFO"):
        ts=datetime.now().strftime("%H:%M:%S"); line=f"[{ts}] [{level}] {msg}"
        with self._lock: self._lines.append(line)
        if self._fl:
            try: getattr(self._fl,level.lower(),self._fl.info)(msg)
            except: pass
        for cb in list(self._listeners):
            try: cb(line)
            except: pass
    def get_lines(self):
        with self._lock: return list(self._lines)
    def add_listener(self,cb):
        if cb not in self._listeners: self._listeners.append(cb)
    def remove_listener(self,cb):
        try: self._listeners.remove(cb)
        except ValueError: pass

LOGGER = AppLogger()
for _m in LOGGER_DELAYED:
    LOGGER.log(_m)
LOGGER_DELAYED.clear()

# ══════════════════════════════════════════════════════════════════════════════
# KNOWN MAPS  (loaded from maps folder + GitHub update)
# ══════════════════════════════════════════════════════════════════════════════
KNOWN_MAPS = {
    "ballistic engine":"map_ballistic_engine.jpg","vox liberatis":"map_vox_liberatis.jpg",
    "fall of atreus":"map_fall_of_atreus.jpg","decapitation":"map_decapitation.jpg",
    "exfiltration":"map_exfiltration.jpg","termination":"map_termination.jpg",
    "reclamation":"map_reclamation.jpg","reliquary":"map_reliquary.jpg",
    "disruption":"map_disruption.jpg","purgation":"map_purgation.jpg",
    "obelisk":"map_obelisk.jpg","inferno":"map_inferno.jpg","vortex":"map_vortex.jpg",
}
_KEYS = sorted(KNOWN_MAPS.keys(), key=len, reverse=True)

# Only filenames matching this pattern are accepted from the remote map list.
# This prevents path traversal (e.g. "..\\..\\evil.exe") from the network input.
_SAFE_MAP_NAME = re.compile(r"^map_[A-Za-z0-9_\-]+\.(jpg|jpeg|png)$", re.IGNORECASE)
_MAX_MAP_BYTES = 10 * 1024 * 1024   # reject any single map download over 10 MB

def _download_map(remote_name):
    """Validate a remote map filename and download it into the maps folder.

    Returns True if a new file was written, False otherwise. The name is
    sanitised (basename only, strict pattern) before being used as a path or
    URL so that a malicious or malformed maps_list.json cannot escape the
    maps directory or pull an unexpected file type.
    """
    name = os.path.basename(remote_name)          # strip any directory part
    if not _SAFE_MAP_NAME.match(name):
        LOGGER.log(f"Rejected unsafe map name: {remote_name!r}", "WARNING")
        return False
    dest = resource_path(name)
    if os.path.exists(dest):
        return False
    url = f"{GITHUB_RAW}/maps/{name}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            length = resp.headers.get("Content-Length")
            if length and int(length) > _MAX_MAP_BYTES:
                LOGGER.log(f"Map {name} too large ({length} bytes), skipped", "WARNING")
                return False
            data = resp.read(_MAX_MAP_BYTES + 1)
        if len(data) > _MAX_MAP_BYTES:
            LOGGER.log(f"Map {name} exceeded size limit, skipped", "WARNING")
            return False
        with open(dest, "wb") as f:
            f.write(data)
        LOGGER.log(f"Downloaded: {name}")
        return True
    except Exception as e:
        LOGGER.log(f"Could not download {name}: {e}", "WARNING")
        return False

def check_for_updates():
    """Download the map list from GitHub and fetch any new, valid maps."""
    try:
        LOGGER.log("Checking for map updates from GitHub...")
        with urllib.request.urlopen(MAPS_LIST_URL, timeout=6) as r:
            remote = json.loads(r.read().decode())
    except Exception as e:
        LOGGER.log(f"GitHub update skipped: {e}", "WARNING")
        return

    new_count = 0
    # Build the updated mapping locally, then swap it in atomically so the OCR
    # worker thread never iterates a dict/list mid-mutation.
    merged = dict(KNOWN_MAPS)
    for key, raw_name in remote.items():
        name = os.path.basename(str(raw_name))
        if not _SAFE_MAP_NAME.match(name):
            LOGGER.log(f"Rejected unsafe map name: {raw_name!r}", "WARNING")
            continue
        merged.setdefault(key, name)
        if _download_map(name):
            new_count += 1

    KNOWN_MAPS.clear()
    KNOWN_MAPS.update(merged)
    _KEYS[:] = sorted(KNOWN_MAPS.keys(), key=len, reverse=True)
    LOGGER.log(f"Update complete. {new_count} new maps downloaded.")

# ══════════════════════════════════════════════════════════════════════════════
# TRANSLATIONS
# ══════════════════════════════════════════════════════════════════════════════
TR = {
    "en": dict(
        title="Settings", tab_map="Map", tab_det="Detection", tab_adv="Advanced",
        map_img="Map Image", configuring="Configuring:", no_map="No map active",
        auto_save="Scale & position auto-saved per map",
        scale="Scale (%)", opacity="Opacity (%)", pos_x="Position X", pos_y="Position Y",
        auto_adj="⚡ Auto Adjust", auto_adj_tip="Fits map to the target zone based on resolution",
        map_mode_lbl="Map Behavior — choose one:",
        mode_press="Show map while holding assigned key (release to hide)",
        mode_always="Always show map when game is active",
        mode_toggle="Toggle map ON/OFF with assigned key",
        mission_scan="Mission Name Scan Area",
        shortcut_lbl="Assigned Key / Button",
        assign_key="🎮 Assign Key or Gamepad Button",
        press_any="Press any keyboard key or gamepad button...",
        current_key="Current:", capture_area="Capture Area",
        auto_detect="Auto Detect (monitor res.)", monitor_lbl="Monitor:",
        ocr_title="OCR Tuning", ocr_thresh1="Threshold 1 — golden/amber text (30–220)",
        ocr_thresh2="Threshold 2 — mid-range text (80–240)",
        ocr_thresh3="Threshold 3 — bright white text (100–255)",
        ocr_upscale="Upscale factor before OCR (1–4×)",
        ocr_fuzzy="Match sensitivity (0.5 = loose, 1.0 = exact)",
        ocr_psm="Text layout mode", scan_delay="OCR start delay (s)",
        lang_lbl="Language", close_game="Close app when game exits",
        launch_game="Open app on Windows startup (experimental)",
        add_start="Add to startup", rem_start="Remove from startup",
        tray_settings="Settings", tray_quit="Quit",
        debug_show="🐛 Debug ▼", debug_hide="🐛 Debug ▲",
        last_det="Last detected:", not_det="Nothing detected yet", at_t="at",
        scan_now="📷 Scan Now", ocr_res="OCR result:", ocr_none="Nothing found",
        log="Live Log", game_on="✅ Game active", game_off="❌ Game not detected",
        credits="Maps by KimberPrime ↗",
        wiz_title="SM2 Map Overlay", wiz_sub="Initial Setup",
        wiz_lang="Language", wiz_res="Game resolution (W × H):",
        wiz_auto="auto-detected", wiz_key="Map Key / Gamepad Button",
        wiz_assign="Assign Key or Button", wiz_mode="Display Mode",
        wiz_hold="Hold key to show (release = hide)",
        wiz_toggle="Toggle map on/off with key",
        wiz_always="Always show map when game is active",
        wiz_start="START APP",
    ),
    "es": dict(
        title="Ajustes", tab_map="Mapa", tab_det="Detección", tab_adv="Avanzado",
        map_img="Imagen del mapa", configuring="Configurando:", no_map="Sin mapa activo",
        auto_save="Escala y posición guardadas automáticamente por mapa",
        scale="Escala (%)", opacity="Opacidad (%)", pos_x="Posición X", pos_y="Posición Y",
        auto_adj="⚡ Ajuste automático", auto_adj_tip="Ajusta el mapa a la zona según resolución",
        map_mode_lbl="Comportamiento del mapa — elige uno:",
        mode_press="Mostrar mapa al mantener tecla asignada (soltar = ocultar)",
        mode_always="Mostrar siempre el mapa cuando el juego está activo",
        mode_toggle="Alternar mapa ON/OFF con la tecla asignada",
        mission_scan="Área de escaneo del nombre de misión",
        shortcut_lbl="Tecla / Botón asignado",
        assign_key="🎮 Asignar Tecla o Botón del Mando",
        press_any="Presiona cualquier tecla del teclado o botón del mando...",
        current_key="Actual:", capture_area="Capturar área",
        auto_detect="Auto detectar (res. monitor)", monitor_lbl="Monitor:",
        ocr_title="Ajuste de OCR", ocr_thresh1="Umbral 1 — texto dorado/ámbar (30–220)",
        ocr_thresh2="Umbral 2 — texto rango medio (80–240)",
        ocr_thresh3="Umbral 3 — texto blanco brillante (100–255)",
        ocr_upscale="Factor de escalado antes del OCR (1–4×)",
        ocr_fuzzy="Sensibilidad de coincidencia (0.5 = permisivo, 1.0 = exacto)",
        ocr_psm="Modo de análisis de texto", scan_delay="Retraso de inicio OCR (s)",
        lang_lbl="Idioma", close_game="Cerrar app cuando se cierre el juego",
        launch_game="Abrir app al iniciar Windows (experimental)",
        add_start="Agregar al inicio", rem_start="Quitar del inicio",
        tray_settings="Ajustes", tray_quit="Salir",
        debug_show="🐛 Debug ▼", debug_hide="🐛 Debug ▲",
        last_det="Último detectado:", not_det="Nada detectado aún", at_t="a las",
        scan_now="📷 Escanear ahora", ocr_res="Resultado OCR:", ocr_none="Nada encontrado",
        log="Log en vivo", game_on="✅ Juego activo", game_off="❌ Juego no detectado",
        credits="Mapas por KimberPrime ↗",
        wiz_title="SM2 Map Overlay", wiz_sub="Configuración inicial",
        wiz_lang="Idioma", wiz_res="Resolución del juego (A × H):",
        wiz_auto="detectado automáticamente", wiz_key="Tecla / Botón del mando",
        wiz_assign="Asignar Tecla o Botón", wiz_mode="Modo de visualización",
        wiz_hold="Mantener tecla para ver (soltar = ocultar)",
        wiz_toggle="Alternar mapa ON/OFF con tecla",
        wiz_always="Mostrar mapa siempre cuando el juego esté activo",
        wiz_start="INICIAR APP",
    ),
    "ja": dict(
        title="設定", tab_map="マップ", tab_det="検出", tab_adv="詳細",
        map_img="マップ画像", configuring="設定中:", no_map="マップ未アクティブ",
        auto_save="スケールと位置はマップごとに自動保存",
        scale="スケール (%)", opacity="不透明度 (%)", pos_x="X位置", pos_y="Y位置",
        auto_adj="⚡ 自動調整", auto_adj_tip="解像度に基づきマップを自動配置",
        map_mode_lbl="マップの動作 — 1つ選択:",
        mode_press="割り当てキーを押している間マップ表示（離すと非表示）",
        mode_always="ゲームがアクティブな間は常にマップ表示",
        mode_toggle="割り当てキーでマップON/OFF切替",
        mission_scan="ミッション名スキャンエリア",
        shortcut_lbl="割り当てキー / ボタン",
        assign_key="🎮 キーまたはゲームパッドボタンを割り当て",
        press_any="任意のキーボードキーまたはゲームパッドボタンを押してください...",
        current_key="現在:", capture_area="エリアをキャプチャ",
        auto_detect="自動検出（モニター解像度）", monitor_lbl="モニター:",
        ocr_title="OCR調整", ocr_thresh1="閾値1 — 金色/琥珀色テキスト (30–220)",
        ocr_thresh2="閾値2 — 中間テキスト (80–240)",
        ocr_thresh3="閾値3 — 明るい白テキスト (100–255)",
        ocr_upscale="OCR前のアップスケール倍率 (1–4×)",
        ocr_fuzzy="一致感度 (0.5=緩い, 1.0=厳密)",
        ocr_psm="テキストレイアウトモード", scan_delay="OCR開始遅延 (秒)",
        lang_lbl="言語", close_game="ゲーム終了時にアプリを閉じる",
        launch_game="Windowsスタートアップ時にアプリを開く（実験的）",
        add_start="スタートアップに追加", rem_start="スタートアップから削除",
        tray_settings="設定", tray_quit="終了",
        debug_show="🐛 Debug ▼", debug_hide="🐛 Debug ▲",
        last_det="最後に検出:", not_det="まだ検出なし", at_t="時刻",
        scan_now="📷 今すぐスキャン", ocr_res="OCR結果:", ocr_none="何も見つかりません",
        log="ライブログ", game_on="✅ ゲームアクティブ", game_off="❌ ゲーム未検出",
        credits="KimberPrime製マップ ↗",
        wiz_title="SM2 Map Overlay", wiz_sub="初期設定",
        wiz_lang="言語", wiz_res="ゲーム解像度 (W × H):",
        wiz_auto="自動検出", wiz_key="キー / ゲームパッドボタン",
        wiz_assign="キーまたはボタンを割り当て", wiz_mode="表示モード",
        wiz_hold="キーを押している間表示（離すと非表示）",
        wiz_toggle="キーでマップON/OFF切替",
        wiz_always="ゲームがアクティブな間は常にマップ表示",
        wiz_start="アプリを開始",
    ),
    "fr": dict(
        title="Paramètres", tab_map="Carte", tab_det="Détection", tab_adv="Avancé",
        map_img="Image de carte", configuring="Configuration:", no_map="Aucune carte active",
        auto_save="Échelle et position sauvegardées automatiquement par carte",
        scale="Échelle (%)", opacity="Opacité (%)", pos_x="Position X", pos_y="Position Y",
        auto_adj="⚡ Ajustement auto", auto_adj_tip="Ajuste la carte selon la résolution",
        map_mode_lbl="Comportement de la carte — choisir un:",
        mode_press="Afficher la carte en maintenant la touche (relâcher = masquer)",
        mode_always="Toujours afficher la carte quand le jeu est actif",
        mode_toggle="Basculer la carte ON/OFF avec la touche assignée",
        mission_scan="Zone de scan du nom de mission",
        shortcut_lbl="Touche / Bouton assigné(e)",
        assign_key="🎮 Assigner une touche ou un bouton de manette",
        press_any="Appuyez sur n'importe quelle touche clavier ou bouton de manette...",
        current_key="Actuel:", capture_area="Capturer la zone",
        auto_detect="Détection auto (rés. moniteur)", monitor_lbl="Moniteur:",
        ocr_title="Réglages OCR", ocr_thresh1="Seuil 1 — texte doré/ambre (30–220)",
        ocr_thresh2="Seuil 2 — texte moyen (80–240)",
        ocr_thresh3="Seuil 3 — texte blanc brillant (100–255)",
        ocr_upscale="Facteur d'agrandissement avant OCR (1–4×)",
        ocr_fuzzy="Sensibilité de correspondance (0.5=permissif, 1.0=exact)",
        ocr_psm="Mode d'analyse de texte", scan_delay="Délai de démarrage OCR (s)",
        lang_lbl="Langue", close_game="Fermer l'appli quand le jeu se ferme",
        launch_game="Ouvrir l'appli au démarrage Windows (expérimental)",
        add_start="Ajouter au démarrage", rem_start="Retirer du démarrage",
        tray_settings="Paramètres", tray_quit="Quitter",
        debug_show="🐛 Debug ▼", debug_hide="🐛 Debug ▲",
        last_det="Dernière détection:", not_det="Rien détecté encore", at_t="à",
        scan_now="📷 Scanner", ocr_res="Résultat OCR:", ocr_none="Rien trouvé",
        log="Journal en direct", game_on="✅ Jeu actif", game_off="❌ Jeu non détecté",
        credits="Cartes par KimberPrime ↗",
        wiz_title="SM2 Map Overlay", wiz_sub="Configuration initiale",
        wiz_lang="Langue", wiz_res="Résolution du jeu (L × H):",
        wiz_auto="détecté automatiquement", wiz_key="Touche / Bouton de manette",
        wiz_assign="Assigner une touche ou un bouton", wiz_mode="Mode d'affichage",
        wiz_hold="Maintenir la touche pour afficher (relâcher = masquer)",
        wiz_toggle="Basculer la carte ON/OFF avec la touche",
        wiz_always="Toujours afficher la carte quand le jeu est actif",
        wiz_start="DÉMARRER L'APP",
    ),
}
LANG_NAMES = {"en":"English","es":"Español","ja":"日本語","fr":"Français"}

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_CFG = dict(
    language="en", settings_x=None, settings_y=None,
    first_run_done=False, game_res_w=None, game_res_h=None,
    close_on_exit=False, open_on_start=False,
    map_mode="press",   # "press" | "always" | "toggle"
    hotkey="tab", gamepad_btn="BACK",
    reg_x=0, reg_y=0, reg_w=0, reg_h=0,
    scan_delay=0.2, opacity=100,
    scale=20, pos_x=0, pos_y=0,
    ocr_thresh1=80, ocr_thresh2=130, ocr_thresh3=160,
    ocr_upscale=2, ocr_fuzzy=0.82, ocr_psm=7,
    map_settings={},
)

def load_cfg():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE,"r",encoding="utf-8") as f: d=json.load(f)
            return {**DEFAULT_CFG,**d}, False
        except: pass
    return DEFAULT_CFG.copy(), True

def save_cfg(cfg):
    # Write to a temp file then atomically replace, so a crash mid-write can
    # never leave a truncated config.json (which would trigger a false
    # first-run wizard and wipe the user's settings).
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        LOGGER.log(f"Config save error: {e}", "ERROR")

# ══════════════════════════════════════════════════════════════════════════════
# DARK WIDGET HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _apply_dark(root):
    s=ttk.Style(root); s.theme_use("clam")
    s.configure("TFrame",       background=C["bg"])
    s.configure("TLabel",       background=C["bg"],   foreground=C["text"],    font=_font(10))
    s.configure("TCheckbutton", background=C["bg"],   foreground=C["text"],    font=_font(10))
    s.map("TCheckbutton",       background=[("active",C["hover"])])
    s.configure("TCombobox",    fieldbackground=C["inp"],background=C["card"],
                foreground=C["text"],arrowcolor=C["accent"],borderwidth=0)
    s.map("TCombobox",          fieldbackground=[("readonly",C["inp"])])
    s.configure("TScrollbar",   background=C["border"],troughcolor=C["bg"],
                borderwidth=0,arrowcolor=C["text_dim"])
    s.configure("Vertical.TScrollbar", background=C["border"],troughcolor=C["bg"],arrowcolor=C["text_dim"])

class FlatSlider(tk.Canvas):
    """Canvas-based flat slider — fixed accent blue, no color change on hover."""
    def __init__(self, parent, var, lo, hi, on_release=None, **kw):
        super().__init__(parent, height=24, bg=C["bg"], highlightthickness=0, bd=0, **kw)
        self.var=var; self.lo=lo; self.hi=hi; self._on_rel=on_release; self._drag=False
        self.bind("<Configure>",    self._draw)
        self.bind("<Button-1>",     self._click)
        self.bind("<B1-Motion>",    self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        var.trace_add("write", lambda *_: self.after(0, self._draw))

    def _val2x(self, v):
        w=self.winfo_width()-20
        return 10+max(0,min(1,(v-self.lo)/max(self.hi-self.lo,1e-9)))*w

    def _x2val(self, x):
        w=self.winfo_width()-20
        r=max(0,min(1,(x-10)/max(w,1)))
        return self.lo+r*(self.hi-self.lo)

    def _rrect(self, x1,y1,x2,y2,r,**kw):
        pts=[x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1]
        return self.create_polygon(pts,smooth=True,**kw)

    def _draw(self, _=None):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        if w<=1: return
        try: v=self.var.get()
        except: return
        cy=h//2; x=self._val2x(v)
        self._rrect(10,cy-3,w-10,cy+3,3,fill=C["inp"],outline="")
        if x>10: self._rrect(10,cy-3,x,cy+3,3,fill=C["accent"],outline="")
        self.create_oval(x-8,cy-8,x+8,cy+8,fill=C["accent"],outline=C["bg"],width=2)

    def _set(self, x):
        v=self._x2val(x)
        rng=self.hi-self.lo
        if rng>1: v=round(v)
        elif rng>0.1: v=round(v,1)
        else: v=round(v,2)
        try: self.var.set(v)
        except: pass

    def _click(self,e): self._drag=True; self._set(e.x)
    def _motion(self,e):
        if self._drag: self._set(e.x)
    def _release(self,e):
        self._drag=False; self._set(e.x)
        if self._on_rel: self._on_rel()

def DEntry(parent, var, width=8, vcmd=None):
    return tk.Entry(parent,textvariable=var,width=width,
                    bg=C["inp"],fg=C["text"],insertbackground=C["text"],
                    relief="flat",highlightthickness=1,
                    highlightbackground=C["border"],highlightcolor=C["accent"],
                    font=_font(10),bd=0,validate="key" if vcmd else "none",
                    **({"validatecommand":vcmd} if vcmd else {}))

def DButton(parent, text, command, accent=False, small=False, danger=False):
    if danger: bg,hbg,fg=(C["red"],"#8b0000","#ffffff")
    elif accent: bg,hbg,fg=(C["accent"],C["accent_dim"],"#ffffff")
    else: bg,hbg,fg=(C["card"],C["hover"],C["text"])
    sz=9 if small else 10
    btn=tk.Button(parent,text=text,command=command,bg=bg,fg=fg,
                  activebackground=hbg,activeforeground="#ffffff",
                  relief="flat",cursor="hand2",font=_font(sz),padx=12,pady=6,bd=0,highlightthickness=0)
    btn.bind("<Enter>",lambda e: btn.config(bg=hbg))
    btn.bind("<Leave>",lambda e: btn.config(bg=bg))
    return btn

class RadioCard(tk.Frame):
    """Card-style radio button — blue border + bold text when selected, dim card when not."""
    def __init__(self, parent, text, var, value, command=None):
        super().__init__(parent, bg=C["bg"], cursor="hand2")
        self.var=var; self.value=value; self._cmd=command
        self.card=tk.Frame(self, bg=C["card"], padx=12, pady=10,
                           highlightthickness=2, highlightbackground=C["card"])
        self.card.pack(fill="x")
        self.dot=tk.Label(self.card, text="◯", bg=C["card"], fg=C["text_dim"], font=_font(14))
        self.dot.pack(side="left")
        self.lbl=tk.Label(self.card, text=text, bg=C["card"], fg=C["text_dim"],
                          font=_font(10), anchor="w", wraplength=400, justify="left")
        self.lbl.pack(side="left", padx=10, fill="x", expand=True)
        var.trace_add("write", lambda *_: self._refresh())
        self._refresh()
        for w in (self, self.card, self.dot, self.lbl):
            w.bind("<Button-1>", self._click)

    def _click(self, _=None):
        self.var.set(self.value)
        if self._cmd: self._cmd()

    def _refresh(self):
        sel      = self.var.get() == self.value
        card_bg  = "#252640" if sel else C["card"]
        lbl_fg   = "#ffffff" if sel else C["text_dim"]
        dot_txt  = "●"       if sel else "◯"
        dot_fg   = C["accent"] if sel else C["text_dim"]
        border   = C["accent"] if sel else C["border"]
        lbl_font = _font(10, "bold") if sel else _font(10)
        self.card.config(bg=card_bg, highlightbackground=border)
        self.dot.config(bg=card_bg, fg=dot_fg, text=dot_txt)
        self.lbl.config(bg=card_bg, fg=lbl_fg, font=lbl_font)

def DRadio(parent, text, var, value, command=None):
    rc = RadioCard(parent, text, var, value, command)
    rc.pack(fill="x", pady=3)
    return rc

def scrollable_page(parent):
    """Returns inner tk.Frame that scrolls vertically."""
    c=tk.Canvas(parent,bg=C["bg"],highlightthickness=0,bd=0)
    sb=tk.Scrollbar(parent,orient="vertical",command=c.yview,bg=C["border"],
                    troughcolor=C["bg"],relief="flat",bd=0,highlightthickness=0,width=8)
    sb.pack(side="right",fill="y"); c.pack(side="left",fill="both",expand=True)
    c.configure(yscrollcommand=sb.set)
    inner=tk.Frame(c,bg=C["bg"])
    win_id=c.create_window(0,0,window=inner,anchor="nw")
    def _on_inner(e): c.configure(scrollregion=c.bbox("all")); c.itemconfig(win_id,width=c.winfo_width())
    def _on_canvas(e): c.itemconfig(win_id,width=e.width)
    inner.bind("<Configure>",_on_inner); c.bind("<Configure>",_on_canvas)
    c.bind("<MouseWheel>",lambda e: c.yview_scroll(-1*(e.delta//120),"units"))
    inner.bind("<MouseWheel>",lambda e: c.yview_scroll(-1*(e.delta//120),"units"))
    return inner

def DSep(parent): tk.Frame(parent,height=1,bg=C["border"]).pack(fill="x",pady=8)

def DHead(parent, text): tk.Label(parent,text=text,bg=C["bg"],fg=C["text"],font=_font(12,"bold"),anchor="w").pack(fill="x",pady=(0,8))

def DLabel(parent, text, dim=False, **kw):
    return tk.Label(parent,text=text,bg=C["bg"],fg=C["text_dim"] if dim else C["text"],font=_font(9 if dim else 10),**kw)

def slider_block(parent, label, var, lo, hi, on_rel, vcmd, w=6):
    """Row: label + FlatSlider + entry."""
    f=tk.Frame(parent,bg=C["bg"]); f.pack(fill="x",pady=5)
    tk.Label(f,text=label,bg=C["bg"],fg=C["text_dim"],font=_font(9),anchor="w",width=32).pack(side="left")
    s=FlatSlider(f,var,lo,hi,on_release=on_rel); s.pack(side="left",fill="x",expand=True,padx=8)
    e=DEntry(f,var,w,vcmd); e.pack(side="left")
    e.bind("<FocusOut>",lambda _:on_rel()); e.bind("<Return>",lambda _:on_rel())

# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════
class SnippingTool:
    def __init__(self, parent, cb):
        self.top=tk.Toplevel(parent)
        self.top.attributes("-fullscreen",True,"-alpha",0.3,"-topmost",True)
        self.top.config(cursor="cross")
        c=tk.Canvas(self.top,bg="black"); c.pack(fill="both",expand=True)
        self.c=c; self.cb=cb; self.sx=self.sy=self.r=None
        c.bind("<ButtonPress-1>",   lambda e: self._p(e))
        c.bind("<B1-Motion>",       lambda e: self.c.coords(self.r,self.sx,self.sy,e.x,e.y))
        c.bind("<ButtonRelease-1>", lambda e: self._r(e))
    def _p(self,e): self.sx,self.sy=e.x,e.y; self.r=self.c.create_rectangle(e.x,e.y,e.x,e.y,outline=C["accent"],width=2)
    def _r(self,e):
        x1,y1=min(self.sx,e.x),min(self.sy,e.y); x2,y2=max(self.sx,e.x),max(self.sy,e.y)
        self.top.destroy(); self.cb(x1,y1,x2-x1,y2-y1)

def fuzzy_in(needle,hay,th=0.82):
    if needle in hay: return True
    nl,hl=len(needle),len(hay)
    if hl<nl: return difflib.SequenceMatcher(None,needle,hay).ratio()>=th
    for i in range(hl-nl+1):
        if difflib.SequenceMatcher(None,needle,hay[i:i+nl]).ratio()>=th: return True
    return False

def _assign_dual(done_cb):
    done=threading.Event(); res=[None]
    def kb():
        time.sleep(0.5)
        while not done.is_set():
            ev=keyboard.read_event(suppress=True)
            if ev.event_type==keyboard.KEY_DOWN and not done.is_set():
                res[0]=("kb",ev.name); done.set()
    def gp():
        time.sleep(0.5)
        while not done.is_set():
            if XINPUT_AVAILABLE:
                try:
                    conn=XInput.get_connected()
                    for i in range(4):
                        if conn[i]:
                            bt=XInput.get_button_values(XInput.get_state(i))
                            pr=[b for b,v in bt.items() if v]
                            if pr and not done.is_set(): res[0]=("gp",pr[0]); done.set(); return
                except: pass
            time.sleep(0.05)
    threading.Thread(target=kb,daemon=True).start()
    threading.Thread(target=gp,daemon=True).start()
    def chk():
        if done.is_set() and res[0]: done_cb(*res[0])
        else: threading.Timer(0.1,chk).start()
    threading.Timer(0.1,chk).start()

def get_monitors():
    mons=[]
    try:
        import ctypes
        PROC=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_ulong,ctypes.c_ulong,ctypes.POINTER(ctypes.c_long),ctypes.c_double)
        rects=[]
        def cb(h,hdc,lpr,d): r=lpr.contents; rects.append((r[0],r[1],r[2]-r[0],r[3]-r[1])); return True
        ctypes.windll.user32.EnumDisplayMonitors(None,None,PROC(cb),0)
        for i,(x,y,w,h) in enumerate(rects): mons.append((f"Monitor {i+1} ({w}×{h})",x,y,w,h))
    except: pass
    if not mons: mons=[("Primary",0,0,2560,1440)]
    return mons

# ══════════════════════════════════════════════════════════════════════════════
# WIZARD
# ══════════════════════════════════════════════════════════════════════════════
def run_wizard(cfg, root):
    wiz=tk.Toplevel(root); wiz.title("SM2 Map Overlay")
    wiz.resizable(False,False); wiz.attributes("-topmost",True)
    wiz.configure(bg=C["bg"]); wiz.grab_set()
    wiz.protocol("WM_DELETE_WINDOW",lambda: None)
    _apply_dark(wiz)
    lc=list(LANG_NAMES.keys()); ln=list(LANG_NAMES.values())
    cur=[cfg.get("language","en")]
    def T(k): return TR.get(cur[0],TR["en"]).get(k,k)

    pad=tk.Frame(wiz,bg=C["bg"],padx=30,pady=24); pad.pack(fill="both",expand=True)
    tk.Label(pad,text="SM2 Map Overlay",bg=C["bg"],fg=C["text"],font=_font(15,"bold")).pack()
    sub=tk.Label(pad,text=T("wiz_sub"),bg=C["bg"],fg=C["text_dim"],font=_font(10)); sub.pack(pady=(2,14))
    tk.Frame(pad,height=1,bg=C["border"]).pack(fill="x")

    def row(): return tk.Frame(pad,bg=C["bg"])

    lf=row(); lf.pack(fill="x",pady=10)
    tk.Label(lf,text=T("wiz_lang"),bg=C["bg"],fg=C["text"],font=_font(10),width=26,anchor="w").pack(side="left")
    lv=tk.StringVar(value=LANG_NAMES.get(cur[0],"English"))
    lcb=ttk.Combobox(lf,values=ln,textvariable=lv,state="readonly",width=18,font=_font(10)); lcb.pack(side="left")
    def on_lang(_=None):
        s=lv.get()
        if s in ln: cur[0]=lc[ln.index(s)]; sub.config(text=T("wiz_sub")); start_btn.config(text=T("wiz_start"))
    lcb.bind("<<ComboboxSelected>>",on_lang)

    tk.Frame(pad,height=1,bg=C["border"]).pack(fill="x",pady=4)
    tk.Label(pad,text=T("wiz_res"),bg=C["bg"],fg=C["text"],font=_font(10),anchor="w").pack(fill="x")
    rf=row(); rf.pack(fill="x",pady=4)
    rw=tk.IntVar(value=root.winfo_screenwidth()); rh=tk.IntVar(value=root.winfo_screenheight())
    DEntry(rf,rw,7).pack(side="left")
    tk.Label(rf,text=" × ",bg=C["bg"],fg=C["text_dim"],font=_font(11)).pack(side="left")
    DEntry(rf,rh,7).pack(side="left")
    tk.Label(rf,text=f"  ({T('wiz_auto')})",bg=C["bg"],fg=C["text_dim"],font=_font(8)).pack(side="left")

    tk.Frame(pad,height=1,bg=C["border"]).pack(fill="x",pady=4)
    tk.Label(pad,text=T("wiz_key"),bg=C["bg"],fg=C["text"],font=_font(10,"bold"),anchor="w").pack(fill="x")
    ks={"hotkey":"tab","gamepad_btn":"BACK"}
    klv=tk.StringVar(value="TAB / Gamepad: BACK")
    kf=row(); kf.pack(fill="x",pady=4)
    tk.Label(kf,textvariable=klv,bg=C["bg"],fg=C["accent"],font=_font(10,"bold")).pack(side="left")
    def on_done(src,val):
        if src=="kb": ks["hotkey"]=val
        else: ks["gamepad_btn"]=val
        klv.set(f"{ks['hotkey'].upper()} / Gamepad: {ks['gamepad_btn']}")
    assign_btn=DButton(kf,T("wiz_assign"),lambda: _assign_dual(on_done),accent=True)
    assign_btn.pack(side="right")

    tk.Frame(pad,height=1,bg=C["border"]).pack(fill="x",pady=4)
    tk.Label(pad,text=T("wiz_mode"),bg=C["bg"],fg=C["text"],font=_font(10,"bold"),anchor="w").pack(fill="x")
    mv=tk.StringVar(value="press")
    for val,key in [("press","wiz_hold"),("toggle","wiz_toggle"),("always","wiz_always")]:
        DRadio(pad,T(key),mv,val)

    tk.Frame(pad,height=1,bg=C["border"]).pack(fill="x",pady=8)
    def on_start():
        gw_w=rw.get(); gw_h=rh.get()
        cfg["language"]=cur[0]; cfg["game_res_w"]=gw_w; cfg["game_res_h"]=gw_h
        cfg.update(default_scan(gw_w,gw_h))
        cfg["hotkey"]=ks["hotkey"]; cfg["gamepad_btn"]=ks["gamepad_btn"]
        cfg["map_mode"]=mv.get(); cfg["first_run_done"]=True; save_cfg(cfg)
        wiz.grab_release(); wiz.destroy()
    start_btn=DButton(pad,T("wiz_start"),on_start,accent=True)
    start_btn.pack(fill="x",ipady=4)
    wiz.update_idletasks()
    wiz.geometry(f"+{(wiz.winfo_screenwidth()-wiz.winfo_width())//2}+{(wiz.winfo_screenheight()-wiz.winfo_height())//2}")
    root.wait_window(wiz)
    return cfg

# ══════════════════════════════════════════════════════════════════════════════
# OVERLAY APP
# ══════════════════════════════════════════════════════════════════════════════
class OverlayApp:
    def __init__(self, cfg, root):
        self.cfg=cfg; self.root=root; self.root.withdraw()
        self.screen_w=root.winfo_screenwidth(); self.screen_h=root.winfo_screenheight()
        self.overlay=tk.Toplevel(root)
        self.overlay.overrideredirect(True); self.overlay.attributes("-topmost",True)
        self.overlay.config(bg="black"); self.overlay.wm_attributes("-transparentcolor","black")
        self.overlay.geometry(f"{self.screen_w}x{self.screen_h}+0+0"); self.overlay.withdraw()
        gw_w=cfg.get("game_res_w") or self.screen_w; gw_h=cfg.get("game_res_h") or self.screen_h
        if not cfg.get("reg_w"): cfg.update(default_scan(gw_w,gw_h)); save_cfg(cfg)
        self.label=tk.Label(self.overlay,bg="black"); self.label.place(x=0,y=0)
        self._origs={}; self._missing=set(); self._tk_img=None; self._c_map=None; self._c_scale=None
        self.current_map=None; self.is_visible=False; self.was_pressed=False
        self.running=True; self.last_toggle=0.0; self._det_active=False; self._det_lock=threading.Lock()
        self._last_name=None; self._last_time=None; self._last_raw=""; self._last_img=None
        self._proc_cache=(False,0.0); self.show_settings_flag=False; self.settings_win=None
        self.prev_box=None; self.is_prev=False; self.listen_key=False
        self.debug_visible=False; self._dbg_ocr_var=None; self._dbg_prev_lbl=None
        self._bulk=False; self._s_map=None; self._resize_job=[None]
        LOGGER.log(f"OverlayApp ready | {self.screen_w}x{self.screen_h}")
        threading.Thread(target=self._monitor_proc,daemon=True).start()
        self.check_input()

    def _t(self,k): return TR.get(self.cfg.get("language","en"),TR["en"]).get(k,k)

    def _game_proc(self):
        ok,ts=self._proc_cache
        if time.time()-ts<3: return ok
        res=False
        if PSUTIL_AVAILABLE:
            try:
                for p in psutil.process_iter(["name"]):
                    if p.info.get("name")==GAME_EXE: res=True; break
            except: pass
        self._proc_cache=(res,time.time()); return res

    def _game_win(self):
        """Return game window (pygetwindow) or None."""
        try:
            wins=[w for w in gw.getAllWindows() if any(kw in (w.title or "") for kw in GAME_WORDS)]
            return wins[0] if wins else None
        except: return None

    def _is_game_active(self):
        try:
            aw=gw.getActiveWindow()
            if aw and any(kw in (aw.title or "") for kw in GAME_WORDS): return True
        except: pass
        return self._game_proc()

    def _game_offset(self):
        """(ox, oy) of the game window's top-left, or (0, 0) if not found.

        For borderless-fullscreen the window often sits at (0, 0) or a slightly
        negative origin; we clamp negatives to 0 so the capture never starts
        off-screen.
        """
        gwin = self._game_win()
        if not gwin:
            return 0, 0
        try:
            return max(0, gwin.left), max(0, gwin.top)
        except Exception:
            return 0, 0

    def _get_scan_region(self):
        """Absolute (x, y, w, h) for OCR capture, offset by the game window."""
        ox, oy = self._game_offset()
        return (ox + self.cfg["reg_x"], oy + self.cfg["reg_y"],
                self.cfg["reg_w"], self.cfg["reg_h"])

    def _key_held(self):
        hk=self.cfg.get("hotkey","tab")
        try:
            if hk and hk.upper() not in("NONE","") and keyboard.is_pressed(hk): return True
        except: pass
        if XINPUT_AVAILABLE:
            try:
                conn=XInput.get_connected()
                for i in range(4):
                    if conn[i]:
                        gb=self.cfg.get("gamepad_btn","BACK")
                        if gb and gb.upper() not in("NONE","") and XInput.get_button_values(XInput.get_state(i)).get(gb,False): return True
            except: pass
        return False

    def _monitor_proc(self):
        was=False
        while self.running:
            is_r=self._game_proc()
            if was and not is_r:
                LOGGER.log("Game ended")
                if self.cfg.get("close_on_exit"): self.running=False; break
            if not was and is_r: LOGGER.log("Game started")
            was=is_r; time.sleep(5)

    def _battlefield(self):
        if not OCR_AVAILABLE: return False
        gw_w=self.cfg.get("game_res_w") or self.screen_w
        gw_h=self.cfg.get("game_res_h") or self.screen_h
        ox,oy=self._game_offset()
        z=_sz(_BFIELD_CHECK_REF,gw_w,gw_h)
        try:
            sc=pyautogui.screenshot(region=(ox+z["x"],oy+z["y"],z["w"],z["h"]))
            if "battlefield" in pytesseract.image_to_string(sc,config="--psm 7").lower():
                LOGGER.log("Battlefield conditions detected"); return True
        except: pass
        return False

    def _get_ms(self,mf): ms=self.cfg.get("map_settings",{}).get(mf); return ms if(ms and ms.get("initialized")) else None
    def _set_ms(self,mf,s,px,py):
        self.cfg.setdefault("map_settings",{})[mf]={"scale":round(s,2),"pos_x":px,"pos_y":py,"initialized":True}
        self.cfg["scale"]=round(s,2); self.cfg["pos_x"]=px; self.cfg["pos_y"]=py; save_cfg(self.cfg)
    def _load_ms(self,mf):
        ms=self._get_ms(mf)
        if ms: self.cfg["scale"]=ms["scale"]; self.cfg["pos_x"]=ms["pos_x"]; self.cfg["pos_y"]=ms["pos_y"]; return True
        return False

    def _auto_pos(self,mf,iw,ih):
        gw_w=self.cfg.get("game_res_w") or self.screen_w; gw_h=self.cfg.get("game_res_h") or self.screen_h
        s,px,py=calc_map_pos(iw,ih,gw_w,gw_h,self._battlefield())
        LOGGER.log(f"Auto-pos '{mf}': scale={s}% ({px},{py})"); return s,px,py

    def _ensure_pos(self,mf):
        if not self._load_ms(mf):
            orig=self._get_orig(mf)
            if orig: s,px,py=self._auto_pos(mf,orig.width,orig.height); self._set_ms(mf,s,px,py)

    def _ocr_scan(self):
        """Capture the scan region and try to recognise a known mission name.

        Returns the map filename on a successful fuzzy match, else None.
        Several binarisation strategies are tried in order of likelihood and the
        search exits as soon as any known map name is found.
        """
        self._last_raw = ""
        if not OCR_AVAILABLE:
            return None
        reg = self._get_scan_region()
        if reg[2] <= 0 or reg[3] <= 0:
            LOGGER.log(f"Scan region invalid: {reg}", "WARNING")
            return None
        LOGGER.log(f"Scanning region x:{reg[0]} y:{reg[1]} w:{reg[2]} h:{reg[3]}")

        try:
            if MSS_AVAILABLE:
                with mss.mss() as sct:
                    shot = sct.grab({"top": reg[1], "left": reg[0],
                                     "width": reg[2], "height": reg[3]})
                    screen = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            else:
                screen = pyautogui.screenshot(region=reg)
        except Exception as e:
            LOGGER.log(f"Screenshot error: {e}", "ERROR")
            return None
        self._last_img = screen.copy()

        gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)
        factor = max(1, min(4, int(self.cfg.get("ocr_upscale", 2))))
        up = cv2.resize(gray, (gray.shape[1] * factor, gray.shape[0] * factor),
                        interpolation=cv2.INTER_CUBIC)
        up_inv = cv2.bitwise_not(up)

        t1 = int(self.cfg.get("ocr_thresh1", 80))
        t2 = int(self.cfg.get("ocr_thresh2", 130))
        t3 = int(self.cfg.get("ocr_thresh3", 160))
        fuzzy = float(self.cfg.get("ocr_fuzzy", 0.82))
        psm = int(self.cfg.get("ocr_psm", 7))
        tess_cfg = f"--psm {psm} --oem 3"

        # Ordered list of (name, image) candidates, most-likely first.
        candidates = [("otsu_inv",
                       cv2.threshold(up, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1])]
        for thr in (t1, t2, t3):
            candidates.append((f"inv_thr{thr}",
                               cv2.threshold(up_inv, 255 - thr, 255, cv2.THRESH_BINARY)[1]))
        for thr in (t1, t2, t3):
            candidates.append((f"dir_thr{thr}",
                               cv2.threshold(up, thr, 255, cv2.THRESH_BINARY_INV)[1]))
        candidates.append(("raw_inv", up_inv))

        seen = []
        for name, img in candidates:
            try:
                txt = pytesseract.image_to_string(
                    Image.fromarray(img), config=tess_cfg).lower().strip()
            except pytesseract.TesseractNotFoundError:
                LOGGER.log("Tesseract executable not found — OCR disabled this run", "ERROR")
                self._last_raw = "(tesseract not found)"
                return None
            except Exception as e:
                LOGGER.log(f"OCR attempt [{name}] error: {e}", "WARNING")
                continue
            if not txt:
                continue
            seen.append(txt)
            for key in _KEYS:
                if fuzzy_in(key, txt, fuzzy):
                    mf = KNOWN_MAPS[key]
                    if os.path.exists(resource_path(mf)):
                        LOGGER.log(f"OCR matched '{key}' via [{name}] → {mf}")
                        self._last_raw = txt
                        return mf

        combined = " | ".join(dict.fromkeys(seen))[:200]
        self._last_raw = combined
        LOGGER.log(f"OCR: no match. raw: {repr(combined[:120])}")
        return None

    def _start_det(self,hide_fail=True):
        delay=float(self.cfg.get("scan_delay",0.2)); cfg=self.cfg
        if self.current_map:
            self._load_ms(self.current_map); self.root.after(0,self.show_map)
            def _rescan():
                time.sleep(delay)
                if not self.running: return
                found=self._ocr_scan()
                if self.debug_visible: self._upd_debug(found,self._last_raw,self._last_img)
                if found and found!=self.current_map:
                    self.current_map=found
                    for k,v in KNOWN_MAPS.items():
                        if v==found: self._last_name=k.title(); break
                    self._last_time=datetime.now(); self._ensure_pos(found); self.root.after(0,self.show_map)
                elif not found: self.current_map=None
                if not found and hide_fail: self.root.after(0,self.hide_map)
            threading.Thread(target=_rescan,daemon=True).start(); return
        with self._det_lock:
            if self._det_active: return
            self._det_active=True
        LOGGER.log(f"Detection started, delay={delay}s | x:{cfg['reg_x']} y:{cfg['reg_y']} w:{cfg['reg_w']} h:{cfg['reg_h']}")
        def worker():
            time.sleep(delay)
            if not self.running: self._det_active=False; return
            deadline=time.time()+1.5; found=None
            while time.time()<deadline:
                found=self._ocr_scan()
                if self.debug_visible: self._upd_debug(found,self._last_raw,self._last_img)
                if found: break
                if not self._key_held() and cfg.get("map_mode")!="always": break
                time.sleep(0.3)
            if found and (self._key_held() or cfg.get("map_mode") in("toggle","always")):
                self.current_map=found
                for k,v in KNOWN_MAPS.items():
                    if v==found: self._last_name=k.title(); break
                self._last_time=datetime.now(); self._ensure_pos(found); self.root.after(0,self.show_map)
            elif not found and hide_fail: self.root.after(0,self.hide_map)
            with self._det_lock: self._det_active=False
        threading.Thread(target=worker,daemon=True).start()

    def _upd_debug(self,result,raw,img):
        if not self.settings_win or not self.settings_win.winfo_exists() or not self.debug_visible: return
        def _do():
            if self._dbg_ocr_var: self._dbg_ocr_var.set(f"✅ {result}  |  raw: {raw[:90]}" if result else f"{self._t('ocr_none')}  |  raw: {raw[:90]}")
            if self._dbg_prev_lbl and img:
                try:
                    th=img.copy(); th.thumbnail((420,160)); ti=ImageTk.PhotoImage(th)
                    self._dbg_prev_lbl.config(image=ti,text=""); self._dbg_prev_lbl._r=ti
                except: pass
        if self.settings_win.winfo_exists(): self.settings_win.after(0,_do)

    def _get_orig(self,name):
        if name in self._missing: return None
        if name not in self._origs:
            path=resource_path(name)
            if os.path.exists(path):
                try:
                    img=Image.open(path)
                    if img.width>MAX_IMAGE_PX or img.height>MAX_IMAGE_PX:
                        # An oversized image (e.g. an accidentally large upload from
                        # the auto-update pipeline) must NOT crash the app for every
                        # user. Downscale it to the limit and carry on.
                        LOGGER.log(f"Image '{name}' is {img.width}×{img.height}px — "
                                   f"downscaling to fit {MAX_IMAGE_PX}px", "WARNING")
                        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)
                    img=img.convert("RGBA"); arr=np.array(img,dtype=np.int32)
                    r,g,b=arr[:,:,0],arr[:,:,1],arr[:,:,2]
                    mask=((r<=5)&(g<=5)&(b<=5))|((np.abs(r-30)<=12)&(np.abs(g-30)<=12)&(np.abs(b-30)<=12))
                    arr[mask]=[0,0,0,255]; self._origs[name]=Image.fromarray(arr.astype(np.uint8))
                    LOGGER.log(f"Loaded: {name} ({img.width}×{img.height})")
                except Exception as e: self._missing.add(name); LOGGER.log(f"Load error {name}: {e}","ERROR"); return None
            else: self._missing.add(name); LOGGER.log(f"Missing: {path}","WARNING"); return None
        return self._origs[name]

    def check_input(self):
        if not self.running: self.root.quit(); return
        try:
            if self.show_settings_flag: self.show_settings_flag=False; self.open_settings()
        except Exception as e: LOGGER.log(f"open_settings error: {e}","ERROR")
        try:
            if not self.listen_key:
                ga=self._is_game_active(); mode=self.cfg.get("map_mode","press")
                if mode=="always":
                    if ga and not self._det_active and not self.is_visible: self._start_det(False)
                    if self.is_visible and not ga and not self.is_prev: self.hide_map()
                else:
                    held=self._key_held()
                    if ga and held:
                        if not self.was_pressed:
                            if time.time()-self.last_toggle>0.3:
                                if mode=="toggle":
                                    if self.is_visible: self.hide_map()
                                    else: self._start_det()
                                else: self._start_det()
                                self.last_toggle=time.time()
                        self.was_pressed=True
                    else:
                        if self.was_pressed and mode=="press": self.hide_map()
                        self.was_pressed=False
                    if self.is_visible and not ga and not self.is_prev: self.hide_map()
        except Exception as e: LOGGER.log(f"check_input error: {e}","ERROR")
        self.root.after(20,self.check_input)

    def show_map(self,fast=False):
        if not self.current_map: return
        orig=self._get_orig(self.current_map)
        if orig is None: return
        scale=self.cfg.get("scale",20)/100.0
        rs=getattr(Image,"Resampling",Image)
        if self.current_map!=self._c_map or abs(scale-(self._c_scale or -1))>0.0001:
            nw,nh=max(1,int(orig.width*scale)),max(1,int(orig.height*scale))
            self._tk_img=ImageTk.PhotoImage(orig.resize((nw,nh),rs.NEAREST if fast else rs.LANCZOS))
            self.label.config(image=self._tk_img); self._c_map,self._c_scale=self.current_map,scale
        self.label.place(x=self.cfg.get("pos_x",0),y=self.cfg.get("pos_y",0))
        self.overlay.attributes("-alpha",self.cfg.get("opacity",100)/100.0)
        self.overlay.deiconify(); self.is_visible=True

    def _upd_pos_op(self):
        self.label.place(x=self.cfg.get("pos_x",0),y=self.cfg.get("pos_y",0))
        self.overlay.attributes("-alpha",self.cfg.get("opacity",100)/100.0)

    def hide_map(self): self.overlay.withdraw(); self.is_visible=False

    def _draw_box(self):
        if not self.prev_box:
            self.prev_box=tk.Toplevel(self.root); self.prev_box.overrideredirect(True)
            self.prev_box.attributes("-topmost",True); self.prev_box.wm_attributes("-transparentcolor","black")
            self.prev_box.config(bg="black")
            c=tk.Canvas(self.prev_box,bg="black",highlightthickness=2,highlightbackground=C["accent"])
            c.pack(fill="both",expand=True)
        ox,oy=self._game_offset()
        x,y=ox+self.cfg["reg_x"],oy+self.cfg["reg_y"]; w,h=max(self.cfg["reg_w"],1),max(self.cfg["reg_h"],1)
        self.prev_box.geometry(f"{w}x{h}+{x}+{y}"); self.prev_box.deiconify()

    def _hide_box(self):
        if self.prev_box: self.prev_box.withdraw()

    def _startup_add(self):
        try:
            import winreg
            k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",0,winreg.KEY_SET_VALUE)
            winreg.SetValueEx(k,"SM2MapOverlay",0,winreg.REG_SZ,f'"{sys.executable}"')
            winreg.CloseKey(k); LOGGER.log("Added to startup")
        except Exception as e: LOGGER.log(f"Startup add: {e}","ERROR")

    def _startup_rem(self):
        try:
            import winreg
            k=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Microsoft\Windows\CurrentVersion\Run",0,winreg.KEY_SET_VALUE)
            winreg.DeleteValue(k,"SM2MapOverlay"); winreg.CloseKey(k); LOGGER.log("Removed from startup")
        except Exception as e: LOGGER.log(f"Startup rem: {e}","ERROR")

    # ── SETTINGS WINDOW ────────────────────────────────────────────────────────
    def _shortcut_text(self):
        return (f"{self.cfg.get('hotkey','tab').upper()} / "
                f"Gamepad: {self.cfg.get('gamepad_btn','BACK')}")

    def _build_assign_widget(self, parent, win, label_vars):
        """Create a 'Current: KEY / Gamepad: BTN  [Assign]' row.

        Assigning a keyboard key updates only the keyboard binding; assigning a
        gamepad button updates only the gamepad binding. The other is preserved.
        label_vars is a shared list of StringVars kept in sync across every tab
        that shows the current shortcut.
        """
        frame = tk.Frame(parent, bg=C["card"], padx=14, pady=10)
        frame.pack(fill="x", pady=(0, 10))
        tk.Label(frame, text=self._t("current_key"), bg=C["card"],
                 fg=C["text_dim"], font=_font(9)).pack(side="left")
        var = tk.StringVar(value=self._shortcut_text())
        label_vars.append(var)
        lbl = tk.Label(frame, textvariable=var, bg=C["card"],
                       fg=C["accent"], font=_font(11, "bold"))
        lbl.pack(side="left", padx=8)

        def on_done(src, val):
            if src == "kb":
                self.cfg["hotkey"] = val
            else:
                self.cfg["gamepad_btn"] = val
            save_cfg(self.cfg)
            self.listen_key = False
            txt = self._shortcut_text()
            for v in label_vars:
                v.set(txt)
            LOGGER.log(f"Shortcut: {self.cfg['hotkey']} / {self.cfg['gamepad_btn']}")

        def assign():
            self.listen_key = True
            lbl.config(text=self._t("press_any"))
            win.update()
            def _cb(src, val):
                if win.winfo_exists():
                    win.after(0, lambda: on_done(src, val))
            _assign_dual(_cb)

        DButton(frame, self._t("assign_key"), assign, accent=True).pack(side="right")
        return frame

    def open_settings(self):
        try: self._settings_impl()
        except Exception as e:
            tb=traceback.format_exc(); LOGGER.log(f"open_settings crash:\n{tb}","ERROR")
            try:
                import tkinter.messagebox as mb; mb.showerror("Error",f"Settings failed:\n{e}")
            except: pass

    def _settings_impl(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.attributes("-topmost",True); self.settings_win.lift(); self.settings_win.focus_force(); return
        LOGGER.log("Settings opened"); self.is_prev=True
        show_mf=self.current_map
        if not show_mf:
            for mf in KNOWN_MAPS.values():
                if os.path.exists(resource_path(mf)): show_mf=mf; break
        if show_mf:
            try: self._ensure_pos(show_mf); self.current_map=show_mf; self.show_map()
            except Exception as e: LOGGER.log(f"Preview err: {e}","WARNING")
        try: self._draw_box()
        except: pass

        win=tk.Toplevel(self.root); self.settings_win=win
        win.title(self._t("title")); win.configure(bg=C["bg"])
        win.resizable(True,True); win.attributes("-topmost",True); _apply_dark(win)
        sx,sy=self.cfg.get("settings_x"),self.cfg.get("settings_y")
        win.geometry(f"720x700+{sx}+{sy}" if sx else "720x700")

        # Sidebar + content layout
        sidebar=tk.Frame(win,bg=C["sidebar"],width=190); sidebar.pack(side="left",fill="y"); sidebar.pack_propagate(False)
        content=tk.Frame(win,bg=C["bg"]); content.pack(side="left",fill="both",expand=True)

        tk.Label(sidebar,text="🗡️",bg=C["sidebar"],fg=C["accent"],font=_font(20)).pack(pady=(18,2))
        tk.Label(sidebar,text="SM2 Overlay",bg=C["sidebar"],fg=C["text_dim"],font=_font(8)).pack(pady=(0,18))
        tk.Frame(sidebar,height=1,bg=C["border"]).pack(fill="x",padx=10)

        pages={}
        for nm in("map","det","adv"): pages[nm]=tk.Frame(content,bg=C["bg"])
        cur_page=[None]; sidebar_btns=[]

        def show_page(nm):
            if cur_page[0]: cur_page[0].pack_forget()
            pages[nm].pack(fill="both",expand=True); cur_page[0]=pages[nm]
            for info in sidebar_btns:
                act=info["name"]==nm
                info["ind"].config(bg=C["accent"] if act else C["sidebar"])
                info["lbl"].config(bg=C["tab_act"] if act else C["sidebar"],
                                   fg=C["text"] if act else C["text_dim"],
                                   font=_font(11,"bold") if act else _font(11))
                info["row"].config(bg=C["tab_act"] if act else C["sidebar"])

        for nm,icon,key in[("map","🗺️","tab_map"),("det","🔍","tab_det"),("adv","⚙️","tab_adv")]:
            row=tk.Frame(sidebar,bg=C["sidebar"],cursor="hand2"); row.pack(fill="x")
            ind=tk.Frame(row,width=3,bg=C["sidebar"]); ind.pack(side="left",fill="y")
            lbl=tk.Label(row,text=f"  {icon}  {self._t(key)}",bg=C["sidebar"],fg=C["text_dim"],
                         font=_font(11),anchor="w",padx=8,pady=12); lbl.pack(side="left",fill="both",expand=True)
            info={"name":nm,"row":row,"ind":ind,"lbl":lbl}; sidebar_btns.append(info)
            row.bind("<Button-1>",lambda e,n=nm:show_page(n)); lbl.bind("<Button-1>",lambda e,n=nm:show_page(n))

        # Credits (red tint, white text, slightly bigger)
        tk.Frame(sidebar,height=1,bg=C["border"]).pack(fill="x",padx=10,side="bottom",pady=4)
        cred=tk.Label(sidebar,text=self._t("credits"),bg="#7b0a0a",fg="#ffffff",
                      font=_font(9,"bold"),cursor="hand2",wraplength=175,justify="center",
                      padx=10,pady=8,relief="flat")
        cred.pack(side="bottom",fill="x",padx=6,pady=4)
        cred.bind("<Button-1>",lambda e: webbrowser.open(KIMBERPRIME_URL))
        cred.bind("<Enter>",lambda e: cred.config(bg="#9e1010"))
        cred.bind("<Leave>",lambda e: cred.config(bg="#7b0a0a"))

        # Shared vars + validators
        shortcut_vars = []   # StringVars showing the current shortcut, synced across tabs
        scale_var  =tk.DoubleVar(value=round(self.cfg.get("scale",20),2))
        opacity_var=tk.DoubleVar(value=round(self.cfg.get("opacity",100),2))
        pos_x_var  =tk.IntVar(value=self.cfg.get("pos_x",0))
        pos_y_var  =tk.IntVar(value=self.cfg.get("pos_y",0))
        mode_var   =tk.StringVar(value=self.cfg.get("map_mode","press"))
        reg_vars   =[tk.IntVar(value=int(self.cfg.get(k,0))) for k in("reg_x","reg_y","reg_w","reg_h")]
        ocr_t1=tk.IntVar(value=int(self.cfg.get("ocr_thresh1",80)))
        ocr_t2=tk.IntVar(value=int(self.cfg.get("ocr_thresh2",130)))
        ocr_t3=tk.IntVar(value=int(self.cfg.get("ocr_thresh3",160)))
        ocr_up=tk.IntVar(value=int(self.cfg.get("ocr_upscale",2)))
        ocr_fz=tk.DoubleVar(value=round(float(self.cfg.get("ocr_fuzzy",0.82)),2))
        ocr_ps=tk.IntVar(value=int(self.cfg.get("ocr_psm",7)))
        delay_var=tk.DoubleVar(value=round(float(self.cfg.get("scan_delay",0.2)),2))

        def _vf(a,v):
            if a=="0": return True
            if v in("","-",".","-."): return True
            try: float(v)
            except: return False
            return not("." in v and len(v.split(".")[1])>2)
        def _vi(a,v):
            if a=="0": return True
            if v in("","-"): return True
            try: int(v); return True
            except: return False
        vcf=(win.register(_vf),"%d","%P"); vci=(win.register(_vi),"%d","%P")

        _prev_s=[self.cfg.get("scale",20)]

        def _schedule_resize():
            if self._resize_job[0]: win.after_cancel(self._resize_job[0])
            self._resize_job[0]=win.after(200,lambda:self.show_map(fast=False))

        def update_vis(*_):
            if self._bulk: return
            ns=round(scale_var.get(),2); sc=abs(ns-_prev_s[0])>0.001; _prev_s[0]=ns
            self.cfg["scale"]=ns; self.cfg["pos_x"]=pos_x_var.get(); self.cfg["pos_y"]=pos_y_var.get()
            self.cfg["opacity"]=round(opacity_var.get(),2)
            if self.is_visible:
                self._upd_pos_op()
                if sc: _schedule_resize()

        def save_all(*_):
            if self._bulk: return
            sc=round(scale_var.get(),2); px=pos_x_var.get(); py=pos_y_var.get()
            self.cfg["scale"]=sc; self.cfg["pos_x"]=px; self.cfg["pos_y"]=py
            self.cfg["opacity"]=round(opacity_var.get(),2); self.cfg["map_mode"]=mode_var.get()
            for i,k in enumerate(("reg_x","reg_y","reg_w","reg_h")): self.cfg[k]=reg_vars[i].get()
            if self.current_map: self._set_ms(self.current_map,sc,px,py)
            else: save_cfg(self.cfg)
            self._c_scale=None
            if self.is_visible: self.show_map(fast=False)
            save_cfg(self.cfg); self._draw_box()

        def save_ocr(*_):
            self.cfg["ocr_thresh1"]=ocr_t1.get(); self.cfg["ocr_thresh2"]=ocr_t2.get()
            self.cfg["ocr_thresh3"]=ocr_t3.get(); self.cfg["ocr_upscale"]=ocr_up.get()
            try: self.cfg["ocr_fuzzy"]=round(float(ocr_fz.get()),2)
            except: pass
            self.cfg["ocr_psm"]=ocr_ps.get()
            try: self.cfg["scan_delay"]=round(float(delay_var.get()),2)
            except: pass
            save_cfg(self.cfg)

        scale_var.trace_add("write",update_vis); opacity_var.trace_add("write",update_vis)
        pos_x_var.trace_add("write",update_vis); pos_y_var.trace_add("write",update_vis)
        for rv in reg_vars: rv.trace_add("write",lambda *_:self.root.after(150,save_all))

        # ── PAGE: MAP ─────────────────────────────────────────────────────────
        inner_mp=scrollable_page(pages["map"]); inner_mp.config(padx=24,pady=20)

        DHead(inner_mp,self._t("map_img"))
        cur_lbl=tk.StringVar(value=self._t("no_map"))
        tk.Label(inner_mp,textvariable=cur_lbl,bg=C["bg"],fg=C["accent"],font=_font(9,"bold"),anchor="w").pack(fill="x",pady=(0,10))

        def _load_map_ui(mf):
            self._bulk=True; ms=self._get_ms(mf)
            if ms: scale_var.set(round(ms["scale"],2)); pos_x_var.set(ms["pos_x"]); pos_y_var.set(ms["pos_y"])
            _prev_s[0]=scale_var.get(); self._bulk=False

        self._s_map=self.current_map
        if self.current_map: cur_lbl.set(f"{self._t('configuring')} {self.current_map}"); _load_map_ui(self.current_map)

        slider_block(inner_mp,self._t("scale"),   scale_var, 10,200,save_all,vcf)
        slider_block(inner_mp,self._t("pos_x"),   pos_x_var,  0,self.screen_w,save_all,vci,7)
        slider_block(inner_mp,self._t("pos_y"),   pos_y_var,  0,self.screen_h,save_all,vci,7)
        tk.Label(inner_mp,text=self._t("auto_save"),bg=C["bg"],fg=C["text_dim"],font=_font(8),anchor="w").pack(fill="x",pady=(0,6))

        def auto_adj():
            if not self.current_map: return
            orig=self._get_orig(self.current_map)
            if not orig: return
            s,px,py=calc_map_pos(orig.width,orig.height,self.cfg.get("game_res_w") or self.screen_w,self.cfg.get("game_res_h") or self.screen_h)
            self._bulk=True; scale_var.set(round(s,2)); pos_x_var.set(px); pos_y_var.set(py); self._bulk=False
            save_all(); LOGGER.log(f"Auto adjust → scale={s}% ({px},{py})")

        DButton(inner_mp,self._t("auto_adj"),auto_adj,accent=True).pack(fill="x",pady=(0,4))
        tk.Label(inner_mp,text=self._t("auto_adj_tip"),bg=C["bg"],fg=C["text_dim"],font=_font(8),anchor="w").pack(fill="x")

        DSep(inner_mp)
        slider_block(inner_mp,self._t("opacity"),opacity_var,10,100,save_all,vcf)
        DSep(inner_mp)

        DHead(inner_mp,self._t("map_mode_lbl"))
        for val,key in[("press","mode_press"),("always","mode_always"),("toggle","mode_toggle")]:
            DRadio(inner_mp,self._t(key),mode_var,val,save_all)

        DSep(inner_mp)
        DHead(inner_mp,self._t("shortcut_lbl"))
        self._build_assign_widget(inner_mp, win, shortcut_vars)

        def _poll():
            if win.winfo_exists():
                if self.current_map!=self._s_map:
                    self._s_map=self.current_map
                    if self.current_map: cur_lbl.set(f"{self._t('configuring')} {self.current_map}"); _load_map_ui(self.current_map)
                    else: cur_lbl.set(self._t("no_map"))
                win.after(500,_poll)
        _poll()

        # ── PAGE: DETECTION ───────────────────────────────────────────────────
        inner_dp=scrollable_page(pages["det"]); inner_dp.config(padx=24,pady=20)

        # Assign key button — shared widget (keeps both kb + gamepad bindings)
        DHead(inner_dp,self._t("shortcut_lbl"))
        self._build_assign_widget(inner_dp, win, shortcut_vars)

        DSep(inner_dp)
        DHead(inner_dp,self._t("mission_scan"))

        # Multi-monitor + scan area
        monitors=get_monitors(); mon_var_idx=tk.IntVar(value=0)
        def start_snip():
            win.withdraw(); self._hide_box()
            def done(x,y,w,h):
                try:
                    if w>5 and h>5:
                        ox,oy=self._game_offset()
                        reg_vars[0].set(x-ox); reg_vars[1].set(y-oy); reg_vars[2].set(w); reg_vars[3].set(h)
                        save_all(); self._draw_box()
                except Exception as e: LOGGER.log(f"Snip err: {e}","ERROR")
                finally:
                    try: win.deiconify(); win.attributes("-topmost",True); win.lift(); win.focus_force()
                    except: pass
            SnippingTool(self.root,done)

        def auto_det():
            idx=mon_var_idx.get()
            _,mx,my,mw,mh=monitors[idx] if idx<len(monitors) else("",0,0,self.screen_w,self.screen_h)
            s=default_scan(mw,mh)
            reg_vars[0].set(s["reg_x"]); reg_vars[1].set(s["reg_y"]); reg_vars[2].set(s["reg_w"]); reg_vars[3].set(s["reg_h"])
            self.cfg["game_res_w"]=mw; self.cfg["game_res_h"]=mh; save_all()
            LOGGER.log(f"Auto detect: {mw}x{mh} → {s}")

        br=tk.Frame(inner_dp,bg=C["bg"]); br.pack(fill="x",pady=(0,6))
        DButton(br,self._t("capture_area"),start_snip).pack(side="left",fill="x",expand=True,padx=(0,6))
        DButton(br,self._t("auto_detect"),auto_det).pack(side="left",fill="x",expand=True)

        if len(monitors)>1:
            mrow=tk.Frame(inner_dp,bg=C["bg"]); mrow.pack(fill="x",pady=(0,6))
            tk.Label(mrow,text=self._t("monitor_lbl"),bg=C["bg"],fg=C["text_dim"],font=_font(9)).pack(side="left")
            mcb=ttk.Combobox(mrow,values=[m[0] for m in monitors],state="readonly",width=28,font=_font(9))
            mcb.pack(side="left",padx=6); mcb.current(0)
            mcb.bind("<<ComboboxSelected>>",lambda _:mon_var_idx.set(mcb.current()))

        xywh=tk.Frame(inner_dp,bg=C["bg"]); xywh.pack(fill="x",pady=(0,12))
        for i,lbl in enumerate(["X:","Y:","W:","H:"]):
            tk.Label(xywh,text=lbl,bg=C["bg"],fg=C["text_dim"],font=_font(9)).pack(side="left",padx=(8 if i>0 else 0,3))
            e=DEntry(xywh,reg_vars[i],6,vcmd=vci); e.pack(side="left")
            e.bind("<FocusOut>",save_all); e.bind("<Return>",save_all)

        DSep(inner_dp)
        DHead(inner_dp,self._t("ocr_title"))

        slider_block(inner_dp,self._t("ocr_thresh1"),ocr_t1,30,220,save_ocr,vci)
        slider_block(inner_dp,self._t("ocr_thresh2"),ocr_t2,80,240,save_ocr,vci)
        slider_block(inner_dp,self._t("ocr_thresh3"),ocr_t3,100,255,save_ocr,vci)
        slider_block(inner_dp,self._t("ocr_upscale"),ocr_up,1,4,save_ocr,vci,3)
        slider_block(inner_dp,self._t("ocr_fuzzy"),  ocr_fz,0.5,1.0,save_ocr,vcf)

        psm_row=tk.Frame(inner_dp,bg=C["bg"]); psm_row.pack(fill="x",pady=5)
        tk.Label(psm_row,text=self._t("ocr_psm"),bg=C["bg"],fg=C["text_dim"],font=_font(9),anchor="w",width=32).pack(side="left")
        psm_vals=[(7,"Line (PSM 7)"),(6,"Block (PSM 6)"),(11,"Sparse (PSM 11)")]
        psm_cb=ttk.Combobox(psm_row,values=[v[1] for v in psm_vals],state="readonly",width=16,font=_font(9))
        psm_cb.pack(side="left",padx=8); psm_cb.current({v[0]:i for i,v in enumerate(psm_vals)}.get(ocr_ps.get(),0))
        psm_cb.bind("<<ComboboxSelected>>",lambda _:(ocr_ps.set(psm_vals[psm_cb.current()][0]),save_ocr()))

        DSep(inner_dp)
        slider_block(inner_dp,self._t("scan_delay"),delay_var,0.0,12.0,save_ocr,vcf)

        # ── PAGE: ADVANCED ────────────────────────────────────────────────────
        inner_ap=scrollable_page(pages["adv"]); inner_ap.config(padx=24,pady=20)

        DHead(inner_ap,self._t("lang_lbl"))
        lc=list(LANG_NAMES.keys()); ln=list(LANG_NAMES.values())
        lcb=ttk.Combobox(inner_ap,values=ln,state="readonly",width=22,font=_font(10))
        lcb.set(LANG_NAMES.get(self.cfg.get("language","en"),"English")); lcb.pack(anchor="w",pady=(0,8))
        def on_lang(_e):
            sel=lcb.get()
            if sel in ln: self.cfg["language"]=lc[ln.index(sel)]; save_cfg(self.cfg); win.destroy(); self.show_settings_flag=True
        lcb.bind("<<ComboboxSelected>>",on_lang)

        DSep(inner_ap)
        DHead(inner_ap,"Game")
        cex_v=tk.BooleanVar(value=self.cfg.get("close_on_exit",False))
        ost_v=tk.BooleanVar(value=self.cfg.get("open_on_start",False))
        def sg(*_): self.cfg["close_on_exit"]=cex_v.get(); self.cfg["open_on_start"]=ost_v.get(); save_cfg(self.cfg)
        tk.Checkbutton(inner_ap,text=self._t("close_game"),variable=cex_v,command=sg,
                       bg=C["bg"],fg=C["text"],selectcolor=C["inp"],activebackground=C["bg"],font=_font(10)).pack(anchor="w",pady=3)
        tk.Checkbutton(inner_ap,text=self._t("launch_game"),variable=ost_v,command=sg,
                       bg=C["bg"],fg=C["text"],selectcolor=C["inp"],activebackground=C["bg"],font=_font(10)).pack(anchor="w",pady=3)
        su_row=tk.Frame(inner_ap,bg=C["bg"]); su_row.pack(fill="x",pady=8)
        DButton(su_row,self._t("add_start"),self._startup_add,small=True).pack(side="left",padx=(0,6))
        DButton(su_row,self._t("rem_start"),self._startup_rem,small=True).pack(side="left")

        DSep(inner_ap)
        DHead(inner_ap,"Debug")
        dbg_hdr=tk.Frame(inner_ap,bg=C["bg"]); dbg_hdr.pack(fill="x")
        dbg_btn=DButton(dbg_hdr,self._t("debug_show"),None,small=True); dbg_btn.pack(side="left")
        dbg_body=tk.Frame(inner_ap,bg=C["bg"])
        self._dbg_prev_lbl=tk.Label(dbg_body,text="[No scan yet]",bg="#0d0e16",fg="#555577",
                                    anchor="center",font=_font(9),height=4)
        self._dbg_prev_lbl.pack(fill="x",pady=(6,4))
        self._dbg_ocr_var=tk.StringVar(value="—")
        tk.Label(dbg_body,textvariable=self._dbg_ocr_var,bg=C["bg"],fg=C["green"],font=_font(9),wraplength=400,anchor="w").pack(fill="x")
        def _dt():
            if self._last_name and self._last_time: return f"{self._t('last_det')} {self._last_name}  {self._t('at_t')} {self._last_time.strftime('%H:%M:%S')}"
            return self._t("not_det")
        det_lbl=tk.Label(dbg_body,text=_dt(),bg=C["bg"],fg="#4488cc",font=_font(9)); det_lbl.pack(anchor="w",pady=(2,2))
        glbl=tk.Label(dbg_body,text="",bg=C["bg"],font=_font(9,"bold")); glbl.pack(anchor="w",pady=(0,6))
        def _do_scan():
            r=self._ocr_scan(); self._upd_debug(r,self._last_raw,self._last_img)
        DButton(dbg_body,self._t("scan_now"),lambda:threading.Thread(target=_do_scan,daemon=True).start()).pack(fill="x",pady=(0,6))
        log_c=tk.Frame(dbg_body,bg=C["bg"]); log_c.pack(fill="both",expand=True)
        log_vsb=tk.Scrollbar(log_c,orient="vertical",bg=C["border"],troughcolor=C["bg"],relief="flat",bd=0,width=8)
        log_vsb.pack(side="right",fill="y")
        log_txt=tk.Text(log_c,height=12,state="disabled",font=("Consolas",9),wrap="word",
                        yscrollcommand=log_vsb.set,bg="#0d0e16",fg=C["green"],relief="flat",bd=0)
        log_txt.pack(side="left",fill="both",expand=True); log_vsb.config(command=log_txt.yview)
        def _append(line):
            if win.winfo_exists() and self.debug_visible:
                log_txt.config(state="normal"); log_txt.insert("end",line+"\n")
                n=int(log_txt.index("end-1c").split(".")[0])
                if n>400: log_txt.delete("1.0",f"{n-400}.0")
                log_txt.see("end"); log_txt.config(state="disabled")
        def _dbg_ref():
            if win.winfo_exists() and self.debug_visible:
                det_lbl.config(text=_dt())
                glbl.config(text=self._t("game_on") if self._is_game_active() else self._t("game_off"),
                            fg=C["green"] if self._is_game_active() else C["red"])
                win.after(1000,_dbg_ref)
        def toggle_dbg():
            if self.debug_visible:
                dbg_body.pack_forget(); dbg_btn.config(text=self._t("debug_show")); self.debug_visible=False; LOGGER.remove_listener(_append)
            else:
                dbg_body.pack(fill="both",expand=True,pady=(4,0)); dbg_btn.config(text=self._t("debug_hide"))
                self.debug_visible=True
                log_txt.config(state="normal"); log_txt.delete("1.0","end")
                for l in LOGGER.get_lines(): log_txt.insert("end",l+"\n")
                log_txt.see("end"); log_txt.config(state="disabled")
                LOGGER.add_listener(_append); _dbg_ref()
        dbg_btn.config(command=toggle_dbg)

        if not OCR_AVAILABLE: tk.Label(inner_ap,text="⚠ pytesseract not installed",bg=C["bg"],fg=C["red"],font=_font(9)).pack(anchor="w",pady=4)

        show_page("map")

        def on_close():
            self.cfg["settings_x"]=win.winfo_x(); self.cfg["settings_y"]=win.winfo_y()
            save_cfg(self.cfg); self.is_prev=False; self.listen_key=False
            self.debug_visible=False; self._bulk=False; self._dbg_ocr_var=None; self._dbg_prev_lbl=None; self._s_map=None
            LOGGER.remove_listener(_append)
            self.hide_map(); self._hide_box(); LOGGER.log("Settings closed"); win.destroy()
        win.protocol("WM_DELETE_WINDOW",on_close)
        win.lift(); win.focus_force()


# ══════════════════════════════════════════════════════════════════════════════
# TRAY
# ══════════════════════════════════════════════════════════════════════════════
root=None; app=None

def _load_app_icon():
    """Load the application icon for the system tray.

    The icon is bundled inside the exe, so when frozen it lives in _MEIPASS.
    Falls back to a solid-colour image only if no icon file is found.
    """
    bases = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(meipass)
    bases.append(_app_dir())
    bases.append(os.path.abspath("."))
    for base in bases:
        for name in ("app_icon.png", "app_icon.ico", "icon.png"):
            path = os.path.join(base, name)
            if os.path.exists(path):
                try:
                    return Image.open(path).convert("RGBA")
                except Exception:
                    pass
    return Image.new("RGB", (64, 64), (30, 90, 200))

def setup_tray():
    img = _load_app_icon()
    def _sl(_): return app._t("tray_settings")
    def _ql(_): return app._t("tray_quit")
    def _open(i, _):
        # Always use the flag — never call tkinter from the tray thread directly.
        app.show_settings_flag = True
    def _quit(i, _):
        app.running = False
        i.stop()
    pystray.Icon("SM2Map", img, "SM2 Map Overlay",
                 pystray.Menu(item(_sl, _open), item(_ql, _quit))).run()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__=="__main__":
    LOGGER.log("="*60)
    LOGGER.log(f"SM2 Map Overlay | OCR:{OCR_AVAILABLE} XInput:{XINPUT_AVAILABLE} psutil:{PSUTIL_AVAILABLE} mss:{MSS_AVAILABLE}")
    try:
        root=tk.Tk(); root.withdraw()
        sw,sh=root.winfo_screenwidth(),root.winfo_screenheight()
        LOGGER.log(f"Screen: {sw}x{sh}")
        cfg,first=load_cfg()
        if not cfg.get("reg_w"): cfg.update(default_scan(cfg.get("game_res_w") or sw,cfg.get("game_res_h") or sh))
        if first or not cfg.get("first_run_done"): cfg=run_wizard(cfg,root)
        threading.Thread(target=check_for_updates,daemon=True).start()
        app=OverlayApp(cfg,root)
        threading.Thread(target=setup_tray,daemon=True).start()
        LOGGER.log("Entering mainloop"); root.mainloop()
    except Exception:
        tb=traceback.format_exc(); LOGGER.log(f"FATAL:\n{tb}","ERROR")
        try:
            with open(user_data_path("sm2_crash.log"),"w",encoding="utf-8") as f:
                f.write(f"Crash at {datetime.now()}\n\n{tb}")
        except: pass
        raise

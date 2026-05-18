import os
import sys
import time
import ctypes
import subprocess
import requests
import json
import base64
import pyautogui
import pyperclip
from PIL import ImageGrab, Image
import speech_recognition as sr
from gtts import gTTS
import pygame
import random
import re

# =====================================================================
# ⚙️ CONFIGURATION
# =====================================================================

os.environ['SDL_AUDIODRIVER'] = 'directsound'
pyautogui.FAILSAFE = False

OLLAMA_API_URL      = "http://localhost:11434/api/generate"
OLLAMA_CHAT_API_URL = "http://localhost:11434/api/chat"
GEMMA_MODEL         = "gemma4:e2b"

SYSTEM_PROMPT = (
    "You are a warm, helpful voice assistant for a person who is completely blind. "
    "You have access to live screenshots of their screen. "
    "Always keep responses brief — 1 to 3 sentences unless reading content. "
    "Never mention errors, coordinates, or technical details. "
    "Speak naturally as if talking to a friend. "
    "Remember what the user said earlier in the conversation and use that context."
)

APP_NAME_MAP = {
    "calculator":     "calc.exe",
    "notepad":        "notepad.exe",
    "paint":          "mspaint.exe",
    "wordpad":        "wordpad.exe",
    "chrome":         "start chrome",
    "browser":        "start chrome",
    "google chrome":  "start chrome",
    "firefox":        "start firefox",
    "edge":           "start msedge",
    "explorer":       "explorer.exe",
    "file explorer":  "explorer.exe",
    "task manager":   "taskmgr.exe",
    "settings":       "start ms-settings:",
    "word":           "winword.exe",
    "excel":          "excel.exe",
    "powerpoint":     "powerpnt.exe",
    "cmd":            "cmd.exe",
    "command prompt": "cmd.exe",
    "snipping tool":  "snippingtool.exe",
    "spotify":        "spotify.exe",
    "vlc":            "vlc.exe",
}

LANGUAGE_MAP = {
    "hindi":      "hi",
    "spanish":    "es",
    "french":     "fr",
    "arabic":     "ar",
    "portuguese": "pt",
    "bengali":    "bn",
    "urdu":       "ur",
    "english":    "en",
}

# =====================================================================
# 🌍 SESSION STATE
# =====================================================================

session = {
    "last_spoken":  "",
    "tts_lang":     "en",
    "session_log":  [],
    "conversation": [],
}


def log_event(command, action, result=""):
    entry = {
        "time":    time.strftime("%H:%M:%S"),
        "command": command,
        "action":  action,
        "result":  result,
    }
    session["session_log"].append(entry)
    print(f"📋 Log → {entry}")


def save_session_log(path="session_log.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session["session_log"], f, indent=2, ensure_ascii=False)
    print(f"💾 Session log saved to {path}")


# =====================================================================
# 🖥️ DPI-Aware Screen Size
# =====================================================================

def get_actual_screen_size():
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return w, h
    except Exception:
        return pyautogui.size()


# =====================================================================
# 🗣️ AUDIO & SPEECH SYSTEM
# =====================================================================

try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
    AUDIO_ENABLED = True
    print("✅ Audio initialized successfully.")
except Exception:
    AUDIO_ENABLED = False
    print("⚠️ pygame audio init failed — speech will be text-only.")


def speak(text, lang=None):
    if not text:
        return
    session["last_spoken"] = text
    active_lang = lang or session["tts_lang"]
    print(f"🗣️ Assistant [{active_lang}]: {text}")
    if not AUDIO_ENABLED:
        return
    temp_audio = f"speech_{random.randint(10000, 99999)}.mp3"
    try:
        tts = gTTS(text=text, lang=active_lang, tld='com')
        tts.save(temp_audio)
        pygame.mixer.music.load(temp_audio)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.unload()
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception:
                pass
    except Exception as e:
        print(f"🤫 (Audio output skipped: {e})")


# =====================================================================
# 📸 SCREEN CAPTURE
# =====================================================================

def capture_screen(image_path="live_screen.png", max_size=800):
    with ImageGrab.grab() as screenshot:
        screenshot = screenshot.convert("RGB")
        screenshot.thumbnail((max_size, max_size))
        screenshot.save(image_path, "JPEG", quality=80)
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return screenshot, b64


# =====================================================================
# 🧠 OLLAMA / GEMMA 4 CORE CALLERS
# =====================================================================

def call_ollama(prompt, b64_image=None, temperature=0.2, stop_tokens=None):
    payload = {
        "model":  GEMMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if stop_tokens:
        payload["options"]["stop"] = stop_tokens
    if b64_image:
        payload["images"] = [b64_image]
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=None)
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"⚠️ Ollama call failed: {e}")
        return ""


def call_ollama_chat(user_text, b64_image=None, temperature=0.3):
    """Multi-turn chat with full conversation memory."""
    content = []
    if b64_image:
        content.append({"type": "image", "data": b64_image})
    content.append({"type": "text", "text": user_text})

    session["conversation"].append({
        "role":    "user",
        "content": content if b64_image else user_text,
    })

    if len(session["conversation"]) > 19:
        session["conversation"] = session["conversation"][-19:]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ] + session["conversation"]

    payload = {
        "model":    GEMMA_MODEL,
        "messages": messages,
        "stream":   False,
        "options":  {"temperature": temperature},
    }

    try:
        response = requests.post(OLLAMA_CHAT_API_URL, json=payload, timeout=None)
        result   = response.json()
        answer   = result.get("message", {}).get("content", "").strip()

        if answer:
            session["conversation"].append({
                "role":    "assistant",
                "content": answer,
            })

        print(f"[CHAT] Gemma: {answer[:80]}...")
        return answer

    except Exception as e:
        print(f"⚠️ Chat call failed: {e}")
        return ""


# =====================================================================
# 👁️ VISION FUNCTIONS
# =====================================================================

def describe_screen():
    _, b64 = capture_screen()
    prompt = (
        "You are a screen reader for a blind user. "
        "Look at the ENTIRE screen. "
        "Give a 2-3 sentence summary of what is visible and what the user can do. "
        "Be descriptive but concise."
    )
    result = call_ollama(prompt, b64_image=b64)
    print(f"👁️ Screen summary: {result}")
    return result


def read_screen_content():
    """
    Reads the screen content intelligently.
    If WhatsApp chat is open — reads last 4 messages naturally.
    Otherwise reads the main text/content on screen.
    """
    _, b64 = capture_screen()
    prompt = (
        "You are a caring voice assistant reading the screen for a blind person. "
        "Look at the screen carefully.\n\n"

        "IF you can see a WhatsApp or messaging chat open with someone:\n"
        "Read the last 4 messages in a warm, natural way like this:\n"
        "Start with who the chat is with, then read each message saying who said it.\n"
        "Example: 'Your chat with Rahul — He said: are you coming tomorrow? "
        "You replied: yes I will be there at 6. He said: perfect, see you then. "
        "You said: looking forward to it.'\n"
        "Always go from oldest to newest. Use 'He said' or 'She said' or their name.\n\n"

        "IF this is a webpage or any other screen:\n"
        "Read the most important visible text clearly and naturally. "
        "Stop at 80 words. No bullet points — speak in flowing sentences.\n\n"

        "Just read — no preamble, no 'I can see', no technical descriptions."
    )
    result = call_ollama(prompt, b64_image=b64, temperature=0.0)
    print(f"📖 Full content: {result}")
    return result


def get_browser_tabs():
    _, b64 = capture_screen(max_size=1920)
    prompt = (
        "Look at the very top strip of the browser window where the tabs are. "
        "List EVERY tab title you can read, from left to right, one per line. "
        "Output only the tab titles, nothing else."
    )
    result = call_ollama(prompt, b64_image=b64, temperature=0.0)
    lines_out = [
        l.strip() for l in result.splitlines()
        if l.strip() and not l.lower().startswith(
            ("based on", "here are", "the tabs", "i can see"))
    ]
    clean = "\n".join(lines_out) if lines_out else result
    print(f"Tabs: {clean}")
    return clean


def get_chrome_toolbar_height():
    """Measure actual Chrome toolbar height dynamically via CDP."""
    try:
        import urllib.request, websocket
        with urllib.request.urlopen("http://localhost:9222/json", timeout=3) as r:
            pages = json.loads(r.read().decode())
        page = next((p for p in pages if p.get("type") == "page"), None)
        if not page:
            return 110
        ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=5,
            header={"Origin": "http://localhost:9222"}
        )
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
            "params": {"expression": "window.outerHeight - window.innerHeight",
                       "returnByValue": True}}))
        resp = json.loads(ws.recv())
        ws.close()
        h = resp.get("result", {}).get("result", {}).get("value", 110)
        print(f"[TOOLBAR] Actual height: {h}px")
        return int(h)
    except Exception:
        return 110


# =====================================================================
# 🖱️ SMART CLICK SYSTEM — 4-layer fallback
# =====================================================================

def find_element_via_uia(target_name):
    try:
        import uiautomation as auto
        import difflib

        root = auto.GetForegroundControl()
        all_controls = []

        def collect(ctrl, depth=0):
            if depth > 8:
                return
            try:
                name = ctrl.Name or ""
                if name:
                    all_controls.append((name, ctrl))
                for child in ctrl.GetChildren():
                    collect(child, depth + 1)
            except Exception:
                pass

        collect(root)
        names = [c[0] for c in all_controls]
        matches = difflib.get_close_matches(
            target_name.lower(),
            [n.lower() for n in names],
            n=1, cutoff=0.8
        )
        if matches:
            matched_name = names[[n.lower() for n in names].index(matches[0])]
            ctrl = next(c[1] for c in all_controls if c[0] == matched_name)
            rect = ctrl.BoundingRectangle
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            if cx <= 0 or cy <= 0:
                print(f"[UIA] Skipping '{matched_name}' — bad coords ({cx}, {cy})")
                return None
            print(f"[UIA] Found '{matched_name}' at ({cx}, {cy})")
            return cx, cy
    except ImportError:
        print("[UIA] uiautomation not installed — skipping")
    except Exception as e:
        print(f"[UIA] Error: {e}")
    return None


def find_element_via_cdp(target_name):
    try:
        import urllib.request

        with urllib.request.urlopen("http://localhost:9222/json", timeout=3) as r:
            pages = json.loads(r.read().decode())

        SKIP_URLS         = ["localhost:8888", "localhost:9222"]
        SKIP_TYPES        = {"service_worker", "worker", "background_page"}
        SKIP_URL_PATTERNS = ["embed", "enablejsapi", "blob:", "chrome-extension://"]

        def is_valid(p):
            if p.get("type") in SKIP_TYPES:
                return False
            url = p.get("url", "")
            if any(s in url for s in SKIP_URLS):
                return False
            if any(s in url for s in SKIP_URL_PATTERNS):
                return False
            return True

        valid_tabs = [p for p in pages if is_valid(p)]
        if not valid_tabs:
            print("[CDP] No usable tabs found.")
            return None

        # Get foreground window title
        try:
            hwnd   = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf    = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            fg_title = buf.value.lower()
        except Exception:
            fg_title = ""

        print(f"[CDP] Foreground window: '{fg_title}'")

        page = None

        # 1st: Chrome active tab flag
        active_tabs = [p for p in valid_tabs if p.get("active") == True]
        if active_tabs:
            page = active_tabs[0]
            print(f"[CDP] Active tab: {page.get('title','')[:50]}")

        # 2nd: match tab URL/title against foreground window title words
        if not page:
            fg_words = [w for w in fg_title.replace("-", " ").split() if len(w) > 4]
            for p in valid_tabs:
                tab_url   = p.get("url", "").lower()
                tab_title = p.get("title", "").lower()
                if any(word in tab_url or word in tab_title for word in fg_words):
                    page = p
                    print(f"[CDP] Word match: {page.get('title','')[:50]}")
                    break

        # 3rd: longest real title (not blank/embed)
        if not page:
            real_tabs = [p for p in valid_tabs if len(p.get("title", "")) > 5]
            if real_tabs:
                page = max(real_tabs, key=lambda p: len(p.get("title", "")))
                print(f"[CDP] Longest real tab: {page.get('title','')[:50]}")
            else:
                page = valid_tabs[0]

        ws_url = page.get("webSocketDebuggerUrl") or page.get("webSocketUrl")
        if not ws_url:
            print(f"[CDP] No WebSocket URL for: {page.get('title')}")
            return None

        print(f"[CDP] Targeting: '{page.get('title','')}' | {page.get('url','')[:60]}")

        import websocket
        ws = websocket.create_connection(
            ws_url, timeout=10,
            header={"Origin": "http://localhost:9222"}
        )
        msg_id = [1]

        def cdp_send(method, params=None):
            payload = json.dumps({
                "id": msg_id[0], "method": method, "params": params or {}})
            msg_id[0] += 1
            ws.send(payload)
            for _ in range(20):
                try:
                    resp = json.loads(ws.recv())
                    if resp.get("id") == msg_id[0] - 1:
                        return resp
                except Exception:
                    break
            return {}

        cdp_send("Runtime.enable")

        safe_target = target_name.lower().replace("\\", "").replace("'", "\\'")

        js = r"""
        (function() {
            function collectAll(root, seen, out) {
                const iter = document.createTreeWalker(
                    root, NodeFilter.SHOW_ELEMENT, null, false);
                let node;
                while ((node = iter.nextNode())) {
                    if (!seen.has(node)) { seen.add(node); out.push(node); }
                    if (node.shadowRoot) collectAll(node.shadowRoot, seen, out);
                }
            }

            const seen = new Set();
            const elements = [];
            collectAll(document.body, seen, elements);

            const target = '__SAFE_TARGET__';
            let best = null, bestScore = 0;

            function tokenScore(text, tgt) {
                const tgtTokens = tgt.split(/[\s]+/);
                const txtTokens = text.split(/[\s]+/);
                let matched = 0;
                for (const tt of tgtTokens) {
                    if (tt.length < 2) continue;
                    for (const tx of txtTokens) {
                        if (tx === tt)          { matched += 2; break; }
                        if (tx.startsWith(tt))  { matched += 1.5; break; }
                        if (tx.includes(tt))    { matched += 1; break; }
                    }
                }
                return matched / Math.max(tgtTokens.length, 1);
            }

            function charOverlap(a, b) {
                const shorter = a.length < b.length ? a : b;
                const longer  = a.length < b.length ? b : a;
                let matches = 0;
                for (let i = 0; i < shorter.length; i++) {
                    if (longer.includes(shorter[i])) matches++;
                }
                return matches / longer.length;
            }

            for (const el of elements) {
                let rect;
                try { rect = el.getBoundingClientRect(); } catch(e) { continue; }
                if (!rect || rect.width === 0 || rect.height === 0) continue;
                if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
                if (rect.right  < 0 || rect.left > window.innerWidth)  continue;
                if (rect.width < 20 || rect.height < 20) continue;
                if (rect.top < 60 && rect.height < 50) continue;

                const texts = [
                    el.innerText,
                    el.getAttribute('aria-label'),
                    el.getAttribute('title'),
                    el.getAttribute('placeholder'),
                    el.getAttribute('alt')
                ].filter(Boolean).map(t => t.toLowerCase().trim().split('\n')[0]);

                let score = 0;
                for (const text of texts) {
                    if (!text || text.length === 0) continue;
                    if (text === target)                              { score = Math.max(score, 10); continue; }
                    if (text.startsWith(target))                      { score = Math.max(score, 8);  continue; }
                    if (text.includes(target))                        { score = Math.max(score, 6);  continue; }
                    if (target.startsWith(text) && text.length > 3)  { score = Math.max(score, 5);  continue; }

                    const ts = tokenScore(text, target);
                    if (ts >= 1.5) { score = Math.max(score, 4); continue; }
                    if (ts >= 1.0) { score = Math.max(score, 3); continue; }
                    if (ts >= 0.5) { score = Math.max(score, 2); continue; }

                    if (target.length >= 3) {
                        const co = charOverlap(text, target);
                        if (co >= 0.85)      { score = Math.max(score, 2); }
                        else if (co >= 0.7)  { score = Math.max(score, 1); }
                    }
                }

                if (score > bestScore) {
                    bestScore = score;
                    best = {
                        x: rect.left + rect.width  / 2,
                        y: rect.top  + rect.height / 2,
                        text: texts[0] || '',
                        score: score
                    };
                }
            }
            return (best && bestScore >= 4) ? JSON.stringify(best) : null;
        })()
        """

        js = js.replace("__SAFE_TARGET__", safe_target)
        result = cdp_send("Runtime.evaluate", {"expression": js, "returnByValue": True})
        ws.close()

        val = result.get("result", {}).get("result", {}).get("value")
        if not val:
            print("[CDP] Element not found in DOM.")
            return None

        elem = json.loads(val)
        print(f"[CDP] Found '{elem['text'][:40]}' score={elem['score']} "
              f"viewport=({elem['x']:.0f}, {elem['y']:.0f})")

        hwnd     = ctypes.windll.user32.GetForegroundWindow()
        win_rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(win_rect))

        toolbar_h = get_chrome_toolbar_height()
        screen_x  = win_rect.left + int(elem["x"]) - 10
        screen_y  = win_rect.top  + toolbar_h + int(elem["y"])
        print(f"[CDP] Screen coords: ({screen_x}, {screen_y})")
        return screen_x, screen_y

    except ConnectionRefusedError:
        print("[CDP] Chrome not running with --remote-debugging-port=9222")
    except ImportError:
        print("[CDP] Run: pip install websocket-client")
    except Exception as e:
        print(f"[CDP] Error: {e}")
    return None


def click_tab_by_name(tab_name):
    _, b64 = capture_screen(max_size=1920)
    prompt = (
        f"Look ONLY at the horizontal tab bar at the very top of the window.\n"
        f"Find the tab labelled \"{tab_name}\" (or the closest match).\n"
        "Output ONLY JSON: {\"x_pct\": <0-100>, \"y_pct\": 0}\n"
        "If not found: {\"x_pct\": -1, \"y_pct\": 0}"
    )
    res_text = call_ollama(prompt, b64_image=b64, temperature=0.0)
    print(f"[TAB COORD RAW] {res_text}")
    json_match = re.search(r'\{[^{}]*\}', res_text, re.DOTALL)
    if json_match:
        try:
            coords = json.loads(json_match.group(0))
            x = float(coords.get("x_pct", -1))
            if x < 0:
                return False
            logical_w, _ = pyautogui.size()
            click_x = int(logical_w * (x / 100))
            click_y = 22
            print(f"[TAB CLICK] ({click_x}, {click_y})")
            pyautogui.moveTo(click_x, click_y, duration=0.3)
            time.sleep(0.2)
            pyautogui.click(click_x, click_y)
            return True
        except (json.JSONDecodeError, ValueError):
            pass
    return False


def get_vision_click_coordinates_zoomed(target_element):
    _, b64_full = capture_screen(max_size=1920)
    rough_prompt = (
        f"Find '{target_element}' in this screenshot. "
        "Output ONLY: {\"x_pct\": <0-100>, \"y_pct\": <0-100>}. "
        "If not found: {\"x_pct\": -1, \"y_pct\": -1}"
    )
    rough_text = call_ollama(rough_prompt, b64_image=b64_full, temperature=0.0)
    print(f"[ZOOM ROUGH] {rough_text}")

    m = re.search(r'\{[^{}]*\}', rough_text, re.DOTALL)
    if not m:
        return None
    try:
        rough = json.loads(m.group(0))
        rx = float(rough.get("x_pct", -1))
        ry = float(rough.get("y_pct", -1))
        if rx < 0 or ry < 0 or rx > 100 or ry > 100:
            return None
    except (json.JSONDecodeError, ValueError):
        return None

    logical_w, logical_h = pyautogui.size()
    cx = int(logical_w * rx / 100)
    cy = int(logical_h * ry / 100)
    pad = 200
    left   = max(0, cx - pad)
    top    = max(0, cy - pad)
    right  = min(logical_w, cx + pad)
    bottom = min(logical_h, cy + pad)

    if right <= left or bottom <= top:
        return None

    with ImageGrab.grab(bbox=(left, top, right, bottom)) as crop:
        crop_rgb = crop.convert("RGB")
        import io, base64 as b64lib
        buf = io.BytesIO()
        crop_rgb.save(buf, format="JPEG", quality=92)
        b64_crop = b64lib.b64encode(buf.getvalue()).decode("utf-8")

    precise_prompt = (
        f"This is a zoomed crop of a UI. Find '{target_element}'. "
        "Output ONLY: {\"x_pct\": <0-100>, \"y_pct\": <0-100>}. "
        "If not found: {\"x_pct\": -1, \"y_pct\": -1}"
    )
    precise_text = call_ollama(precise_prompt, b64_image=b64_crop, temperature=0.0)
    print(f"[ZOOM PRECISE] {precise_text}")

    m2 = re.search(r'\{[^{}]*\}', precise_text, re.DOTALL)
    if not m2:
        return None
    try:
        precise = json.loads(m2.group(0))
        px = float(precise.get("x_pct", -1))
        py = float(precise.get("y_pct", -1))
        if px < 0 or py < 0 or px > 100 or py > 100:
            return None

        crop_w = right - left
        crop_h = bottom - top
        final_x = left + int(crop_w * px / 100)
        final_y = top  + int(crop_h * py / 100)
        final_x_pct = (final_x / logical_w) * 100
        final_y_pct = (final_y / logical_h) * 100
        print(f"[ZOOM FINAL] ({final_x}, {final_y}) = {final_x_pct:.1f}%, {final_y_pct:.1f}%")
        return {"x_pct": final_x_pct, "y_pct": final_y_pct}
    except (json.JSONDecodeError, ValueError):
        return None


def smart_click(target):
    # Layer 1a: Windows UI Automation
    result = find_element_via_uia(target)
    if result:
        cx, cy = result
        print(f"[L1a-UIA] clicking ({cx}, {cy})")
        pyautogui.moveTo(cx, cy, duration=0.3)
        time.sleep(0.2)
        pyautogui.click(cx, cy)
        return True

    # Layer 1b: Chrome DevTools Protocol
    result = find_element_via_cdp(target)
    if result:
        cx, cy = result
        print(f"[L1b-CDP] clicking ({cx}, {cy})")
        pyautogui.moveTo(cx, cy, duration=0.3)
        time.sleep(0.2)
        pyautogui.click(cx, cy)
        return True

    # Layer 2: Tab strip
    TAB_KEYWORDS = ["tab", "untitled", "jupyter", ".ipynb", ".py",
                    ".js", ".html", ".css", ".txt", ".md", "home"]
    if any(kw in target.lower() for kw in TAB_KEYWORDS):
        print("[L2-TAB] using tab strip click")
        return click_tab_by_name(target)

    # Layer 3: Gemma zoomed vision
    print("[L3-VISION] falling back to zoomed Gemma vision")
    coords = get_vision_click_coordinates_zoomed(target)
    if coords:
        logical_w, logical_h = pyautogui.size()
        click_x = int(logical_w * (coords["x_pct"] / 100))
        click_y = int(logical_h * (coords["y_pct"] / 100))
        print(f"[L3] clicking ({click_x}, {click_y})")
        pyautogui.moveTo(click_x, click_y, duration=0.4)
        time.sleep(0.2)
        pyautogui.click(click_x, click_y)
        return True

    return False


# =====================================================================
# 🌐 NAVIGATION
# =====================================================================

def navigate_to_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.4)
    pyperclip.copy(url)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(3)
    print(f"[NAV] Navigated to {url}")


def resolve_app_name(app_name):
    return APP_NAME_MAP.get(app_name.lower().strip(), app_name.lower().strip())


# =====================================================================
# 📊 SESSION SUMMARY
# =====================================================================

def summarize_my_session():
    logs = session["session_log"]
    if not logs:
        return "You haven't done anything in this session yet."

    SKIP_ACTIONS  = {"unknown", "startup"}
    SKIP_RESULTS  = {"not found", "failed", "error", "could not", "bad coords"}
    SKIP_COMMANDS = {"what would", "startup"}

    clean_events = []
    for entry in logs:
        action  = entry.get("action", "").lower()
        result  = entry.get("result", "").lower()
        command = entry.get("command", "").lower()

        if action in SKIP_ACTIONS:
            continue
        if any(bad in result for bad in SKIP_RESULTS):
            continue
        if any(bad in command for bad in SKIP_COMMANDS):
            continue

        if action == "open_app":
            clean_events.append(f"opened {entry.get('result','').replace('launched','').strip()}")
        elif action == "click_element":
            target = entry.get("result", "").replace("clicked:", "").strip()
            if target:
                clean_events.append(f"clicked on {target}")
        elif action == "navigate":
            clean_events.append(f"visited {entry.get('result', '')}")
        elif action == "search":
            clean_events.append(f"searched for {entry.get('result', '')}")
        elif action == "type":
            clean_events.append("typed something")
        elif action == "send_message":
            clean_events.append("sent a message")
        elif action == "read_content":
            clean_events.append("read the screen content")
        elif action == "describe_current":
            clean_events.append("asked what was on screen")
        elif action == "scroll":
            clean_events.append(f"scrolled {entry.get('result', '')}")
        elif action == "new_tab":
            clean_events.append("opened a new tab")
        elif action == "get_tabs":
            clean_events.append("checked open tabs")
        elif action == "set_language":
            clean_events.append(f"switched language to {entry.get('result', '')}")
        elif action == "chat":
            clean_events.append("asked a question")

    if not clean_events:
        return "You just started the session — nothing to summarize yet."

    try:
        first_time = logs[0]["time"]
        last_time  = logs[-1]["time"]
        duration   = f"from {first_time} to {last_time}"
    except Exception:
        duration = "today"

    activity_text = "\n".join(f"- {e}" for e in clean_events)

    prompt = (
        f"A blind person used a voice assistant {duration}. "
        f"Here is what they did:\n{activity_text}\n\n"
        f"Write a short friendly 2-3 sentence summary of their session. "
        f"Say what apps or websites they used and what they accomplished. "
        f"Do NOT mention any errors, failures, or technical details. "
        f"Sound warm and natural like a helpful friend. "
        f"Start with 'Today you...' or 'In this session you...'"
    )
    summary = call_ollama(prompt, temperature=0.3)
    print(f"📊 Session summary: {summary}")
    return summary


# =====================================================================
# 📧 GMAIL FUNCTIONS
# =====================================================================

def fetch_emails_via_cdp():
    try:
        import urllib.request, websocket

        with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
            pages = json.loads(r.read().decode())

        page = next(
            (p for p in pages if p.get("type") == "page"
             and "mail.google.com" in p.get("url", "")), None)

        if not page:
            speak("Opening Gmail for you.")
            navigate_to_url("https://mail.google.com")
            time.sleep(5)
            with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
                pages = json.loads(r.read().decode())
            page = next(
                (p for p in pages if p.get("type") == "page"
                 and "mail.google.com" in p.get("url", "")), None)

        if not page:
            return None

        ws_url = page.get("webSocketDebuggerUrl")
        ws = websocket.create_connection(
            ws_url, timeout=15,
            header={"Origin": "http://localhost:9222"}
        )
        msg_id = [1]

        def cdp_send(method, params=None):
            payload = json.dumps({
                "id": msg_id[0], "method": method, "params": params or {}})
            msg_id[0] += 1
            ws.send(payload)
            for _ in range(20):
                try:
                    resp = json.loads(ws.recv())
                    if resp.get("id") == msg_id[0] - 1:
                        return resp
                except Exception:
                    break
            return {}

        cdp_send("Runtime.enable")

        js = """
        (function() {
            const rows = Array.from(document.querySelectorAll('tr.zA'));
            const emails = rows.slice(0, 5).map(row => {
                const sender  = row.querySelector('.yP, .zF')?.innerText || 'Unknown';
                const subject = row.querySelector('.bog span, .y6 span')?.innerText ||
                                row.querySelector('.bog')?.innerText || 'No subject';
                const preview = row.querySelector('.y2')?.innerText || '';
                const unread  = row.classList.contains('zE');
                const time    = row.querySelector('.xW span, .ye')?.innerText || '';
                return { sender, subject, preview, unread, time };
            });
            return JSON.stringify(emails);
        })()
        """

        result = cdp_send("Runtime.evaluate", {"expression": js, "returnByValue": True})
        ws.close()

        val = result.get("result", {}).get("result", {}).get("value")
        if val:
            emails = json.loads(val)
            print(f"[GMAIL] Fetched {len(emails)} emails")
            return emails

    except Exception as e:
        print(f"[GMAIL] Error: {e}")
    return None


def read_emails():
    emails = fetch_emails_via_cdp()
    if not emails:
        return "I could not access your Gmail. Make sure you are logged in to Gmail in Chrome."

    session["last_emails"] = emails

    email_text = ""
    for i, em in enumerate(emails, 1):
        status = "unread" if em.get("unread") else "read"
        email_text += (
            f"Email {i} ({status}): From {em['sender']} — "
            f"Subject: {em['subject']} — Preview: {em['preview']}\n"
        )

    prompt = (
        f"A blind person wants to hear their latest emails. "
        f"Here are their inbox emails:\n{email_text}\n\n"
        f"Read them out naturally as if talking to a friend. "
        f"Mention who each is from and what it is about. "
        f"Keep it under 5 sentences total. "
        f"Do not use bullet points — speak in flowing sentences."
    )
    return call_ollama(prompt, temperature=0.3)


def check_urgent_emails():
    emails = session.get("last_emails") or fetch_emails_via_cdp()
    if not emails:
        return "Could not access Gmail."

    session["last_emails"] = emails
    email_text = "\n".join(
        f"From {e['sender']}: {e['subject']} — {e['preview']}"
        for e in emails
    )

    prompt = (
        f"Look at these emails and identify ONLY the urgent ones. "
        f"Urgent means: deadlines, payments, emergencies, meeting reminders, "
        f"or anything time-sensitive.\n{email_text}\n\n"
        f"If there are urgent emails say which ones and why briefly. "
        f"If nothing is urgent say: Nothing urgent in your inbox. "
        f"2 sentences maximum."
    )
    return call_ollama(prompt, temperature=0.2)


def reply_to_last_email(reply_text, recognizer, mic):
    emails = session.get("last_emails", [])
    if not emails:
        return "Please read your emails first so I know which one to reply to."

    last = emails[0]
    speak(f"Opening email from {last['sender']}.")

    try:
        import urllib.request, websocket

        with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
            pages = json.loads(r.read().decode())

        gmail_page = next(
            (p for p in pages if p.get("type") == "page"
             and "mail.google.com" in p.get("url", "")), None)

        if not gmail_page:
            speak("Gmail is not open. Opening it now.")
            navigate_to_url("https://mail.google.com")
            time.sleep(4)
            with urllib.request.urlopen("http://localhost:9222/json", timeout=5) as r:
                pages = json.loads(r.read().decode())
            gmail_page = next(
                (p for p in pages if p.get("type") == "page"
                 and "mail.google.com" in p.get("url", "")), None)

        if not gmail_page:
            return "Could not open Gmail."

        ws_url = gmail_page.get("webSocketDebuggerUrl")
        ws = websocket.create_connection(
            ws_url, timeout=15,
            header={"Origin": "http://localhost:9222"}
        )
        msg_id = [1]

        def cdp_send(method, params=None):
            payload = json.dumps({
                "id": msg_id[0], "method": method, "params": params or {}})
            msg_id[0] += 1
            ws.send(payload)
            for _ in range(20):
                try:
                    resp = json.loads(ws.recv())
                    if resp.get("id") == msg_id[0] - 1:
                        return resp
                except Exception:
                    break
            return {}

        cdp_send("Runtime.enable")

        js_click_email = """
        (function() {
            const row = document.querySelector('tr.zA');
            if (row) { row.click(); return true; }
            return false;
        })()
        """
        result = cdp_send("Runtime.evaluate", {"expression": js_click_email, "returnByValue": True})
        clicked = result.get("result", {}).get("result", {}).get("value")

        if not clicked:
            ws.close()
            return "Could not open the email."

        time.sleep(2.5)

        js_click_reply = """
        (function() {
            const btn = document.querySelector(
                '[aria-label="Reply"], [data-tooltip="Reply"], button[aria-label*="eply"]');
            if (btn) { btn.click(); return 'button'; }
            const all = Array.from(document.querySelectorAll('div[role=button], button'));
            const replyBtn = all.find(el => el.innerText?.trim().toLowerCase() === 'reply');
            if (replyBtn) { replyBtn.click(); return 'text'; }
            return null;
        })()
        """
        result2 = cdp_send("Runtime.evaluate", {"expression": js_click_reply, "returnByValue": True})
        reply_found = result2.get("result", {}).get("result", {}).get("value")
        ws.close()

        if not reply_found:
            pyautogui.press("r")

        time.sleep(1.5)
        pyperclip.copy(reply_text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "enter")
        return "Reply sent successfully."

    except Exception as e:
        print(f"[GMAIL REPLY] Error: {e}")
        return "Something went wrong while replying."


# =====================================================================
# 🔌 CHROME AUTO-LAUNCH
# =====================================================================

CHROME_PATH  = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_FLAGS = [
    "--remote-debugging-port=9222",
    "--user-data-dir=C:\\chrome-debug",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
]


def ensure_chrome_running():
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:9222/json", timeout=2) as r:
            print("[CHROME] Already running with debug port.")
            return True
    except Exception:
        pass

    print("[CHROME] Launching Chrome with debug port...")
    speak("Launching Chrome with accessibility mode.")
    try:
        subprocess.Popen([CHROME_PATH] + CHROME_FLAGS)
        for _ in range(15):
            time.sleep(1)
            try:
                with urllib.request.urlopen("http://localhost:9222/json", timeout=1) as r:
                    print("[CHROME] Debug port ready.")
                    return True
            except Exception:
                pass
        print("[CHROME] Warning: debug port did not open in time.")
        return False
    except FileNotFoundError:
        print(f"[CHROME] Not found at {CHROME_PATH}.")
        return False
    except Exception as e:
        print(f"[CHROME] Launch error: {e}")
        return False


# =====================================================================
# 🧩 INTENT PARSER
# =====================================================================

KEYWORD_RULES = [
    (["read the content", "read content", "read the screen", "read screen",
      "read the text", "read text", "read the code", "read code",
      "read that", "what does it say", "read the page", "read the chat",
      "read the messages", "read the conversation"],
     lambda c: {"action": "read_content"}),

    (["describe the screen", "describe screen", "what do i see",
      "what's on screen", "what is on screen", "look at the screen",
      "what's on the screen"],
     lambda c: {"action": "describe_current"}),

    (["repeat that", "say again", "repeat", "say that again", "what did you say"],
     lambda c: {"action": "repeat"}),

    (["summarize my session", "what did i do today", "what have i done",
      "session summary", "summarize today", "what did i do",
      "give me a summary", "what have i been doing"],
     lambda c: {"action": "summarize_session"}),

    (["what are the tabs", "list the tabs", "show tabs",
      "what tabs are open", "name the tabs"],
     lambda c: {"action": "get_tabs"}),

    (["new tab", "open new tab", "open a new tab"],
     lambda c: {"action": "new_tab"}),

    (["click search bar", "click address bar", "click url bar",
      "focus address bar", "focus search bar"],
     lambda c: {"action": "address_bar"}),

    (["scroll down", "scroll up", "page down", "page up", "go down", "go up"],
     lambda c: {"action": "scroll",
                "direction": "up" if any(w in c for w in ["up", "page up"]) else "down"}),

    (["switch to hindi", "switch to spanish", "switch to french",
      "switch to arabic", "switch to urdu", "switch to bengali",
      "switch to portuguese", "switch to english",
      "speak hindi", "speak spanish", "speak french"],
     lambda c: {"action": "set_language",
                "language": next((w for w in LANGUAGE_MAP if w in c), "english")}),

    (["open ", "launch ", "start "],
     lambda c: {"action": "open_app",
                "app_name": re.sub(r'^(open|launch|start)\s+', '', c).strip()}),

    (["go to ", "navigate to ", "open website ", "visit "],
     lambda c: {"action": "navigate",
                "url": re.sub(r'^(go to|navigate to|open website|visit)\s+', '', c).strip()}),

    (["search for ", "search ", "google ", "look up ", "find "],
     lambda c: {"action": "search",
                "query": re.sub(r'^(search for|search|google|look up|find)\s+', '', c).strip()}),

    (["click ", "press ", "tap ", "focus on ", "select ", "enter "],
     lambda c: {"action": "click_element",
                "target": re.sub(r'^(click|press|tap|focus on|select|enter)\s+(on\s+|the\s+|a\s+)?', '', c).strip()}),

    (["type ", "write "],
     lambda c: {"action": "type",
                "text": re.sub(r'^(type|write)\s+', '', c).strip()}),

    (["send message ", "message ", "send ", "text "],
     lambda c: {"action": "send_message",
                "text": re.sub(r'^(send message|message|send|text)\s+', '', c).strip()}),

    (["read my emails", "check my emails", "check my inbox",
      "any new emails", "what emails do i have",
      "read my inbox", "open my emails", "check email"],
     lambda c: {"action": "read_emails"}),

    (["is there anything urgent", "any urgent emails",
      "anything important in my inbox", "check for urgent",
      "urgent emails", "any important emails"],
     lambda c: {"action": "urgent_emails"}),

    (["reply to the last email", "reply to last email",
      "reply to the email", "send a reply",
      "reply saying ", "reply with "],
     lambda c: {"action": "reply_email",
                "text": re.sub(
                    r'^(reply to the last email|reply to last email|'
                    r'reply to the email|send a reply|reply saying|reply with)\s*',
                    '', c).strip()}),

    # General questions and screen questions — all handled by chat
    (["what is", "what are", "how do", "how does", "how to", "why is", "why does",
      "who is", "who are", "when is", "when was", "tell me", "can you tell",
      "tell me about", "explain", "do you see", "is there", "can you see",
      "are there", "how many", "what buttons", "what options", "do i see",
      "what can i", "name the buttons", "list the buttons"],
     lambda c: {"action": "chat"}),
]


def keyword_parse(command):
    c = command.lower().strip()
    for triggers, builder in KEYWORD_RULES:
        if any(c == t.strip() or c.startswith(t) for t in triggers):
            try:
                return builder(c)
            except Exception:
                pass
    return None


def parse_intent_with_gemma(voice_command):
    local = keyword_parse(voice_command)
    if local:
        print(f"⚡ Keyword match: {local}")
        return local

    print("🤔 Sending to Gemma for intent parsing...")
    system_prompt = (
        "You are an accessibility logic engine. "
        "Output ONLY a single JSON object, nothing else — no explanation, no markdown.\n\n"
        "Allowed actions: open_app, click_element, describe_current, read_content, "
        "scroll, type, search, navigate, new_tab, address_bar, get_tabs, repeat, "
        "set_language, read_emails, urgent_emails, reply_email, summarize_session, chat\n\n"
        "Examples:\n"
        "Command: 'open notepad' → {\"action\": \"open_app\", \"app_name\": \"notepad\"}\n"
        "Command: 'click the run button' → {\"action\": \"click_element\", \"target\": \"run button\"}\n"
        "Command: 'go to whatsapp.com' → {\"action\": \"navigate\", \"url\": \"whatsapp.com\"}\n"
        "Command: 'open new tab' → {\"action\": \"new_tab\"}\n"
        "Command: 'read the content' → {\"action\": \"read_content\"}\n"
        "Command: 'scroll down' → {\"action\": \"scroll\", \"direction\": \"down\"}\n"
        "Command: 'what did i do today' → {\"action\": \"summarize_session\"}\n"
        "Command: 'read my emails' → {\"action\": \"read_emails\"}\n"
        "Command: 'what is whatsapp' → {\"action\": \"chat\"}\n"
        "Command: 'do you see a register button' → {\"action\": \"chat\"}\n"
        "Command: 'reply' → {\"action\": \"reply_email\", \"text\": \"\"}\n"
        "Command: 'reply with hello okay I will be there' → {\"action\": \"reply_email\", \"text\": \"hello okay I will be there\"}\n"
        "Command: 'reply my last email' → {\"action\": \"reply_email\", \"text\": \"\"}\n"
        f"Command: '{voice_command}' → "
    )

    res_text = call_ollama(system_prompt, temperature=0)
    print(f"🔍 Raw Gemma response: '{res_text}'")

    json_match = re.search(r'\{[^{}]*\}', res_text, re.DOTALL)
    if json_match:
        try:
            intent = json.loads(json_match.group(0))
            action = intent.get("action", "")
            if action in ["focus", "go_to", "select", "press", "tap"]:
                intent["action"] = "click_element"
            if action in ["read_text", "read_screen", "read"]:
                intent["action"] = "read_content"
            if action in ["describe_tabs", "list_tabs", "tabs"]:
                intent["action"] = "get_tabs"
            if action in ["describe", "look"]:
                intent["action"] = "describe_current"
            if action in ["open_url", "go_to_url", "visit"]:
                intent["action"] = "navigate"
            if action in ["question", "screen_question", "general_question", "ask"]:
                intent["action"] = "chat"
            return intent
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON decode failed: {e}")

    # Always fallback to chat — never unknown
    return {"action": "chat"}


# =====================================================================
# ⏳ WINDOW POLL HELPER
# =====================================================================

def wait_for_window_change(old_title, timeout=8):
    def get_window_title():
        try:
            hwnd   = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf    = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:
            return ""

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        if get_window_title() != old_title:
            return True
    return False


# =====================================================================
# 🎙️ LISTEN HELPER
# =====================================================================

def listen_for_command(recognizer, mic, timeout=7, phrase_limit=10):
    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            try:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
                return recognizer.recognize_google(audio).lower().strip()
            except (sr.WaitTimeoutError, sr.UnknownValueError):
                return ""
    except Exception as e:
        print(f"⚠️ Listen error: {e}")
        return ""

def normalize_command(command):
    """
    Uses Gemma 4 to translate any language to English.
    This is Gemma 4's native multilingual capability being used directly.
    """
    if session["tts_lang"] == "en":
        return command

    print(f"[GEMMA TRANSLATE] Translating: '{command}'")
    translated = call_ollama(
        f"You are a multilingual translator. "
        f"The user spoke this command in their language: '{command}' "
        f"Translate it to English. "
        f"Return ONLY the English translation, nothing else. "
        f"No explanation, no punctuation, just the translated command.",
        temperature=0.0
    )
    if translated:
        print(f"[GEMMA TRANSLATE] Result: '{translated}'")
        return translated.lower().strip()
    return command
# =====================================================================
# 🔁 MAIN RUNTIME LOOP
# =====================================================================

WEBSITE_NAMES = [
    "whatsapp", "youtube", "google", "github",
    "gmail", "twitter", "instagram", "facebook", "kaggle"
]


def start_accessibility_loop():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = False
    mic = sr.Microphone()

    ensure_chrome_running()

    print("=" * 56)
    print("♿  Vision-Grounded Gemma 4 Accessibility Agent")
    print("    Running fully offline via Ollama")
    print("=" * 56)

    initial_desc = describe_screen()
    speak(f"Accessibility assistant ready. {initial_desc}")
    log_event("STARTUP", "describe_current", initial_desc)

    while True:
        speak("What would you like me to do?")
        command = listen_for_command(recognizer, mic)

        if not command:
            time.sleep(1.5)
            continue

        print(f"\n🎙️  Heard: '{command}'")

        if any(w in command for w in ["stop", "exit", "quit", "goodbye"]):
            speak("Exiting the accessibility assistant. Goodbye!")
            save_session_log()
            break

        command_en = normalize_command(command)
        parsed = parse_intent_with_gemma(command_en)
        action = parsed.get("action", "unknown")
        print(f"🧩 Intent: {parsed}")

        # ── Execute ──────────────────────────────────────────────────

        if action == "open_app":
            raw_name = parsed.get("app_name", "")
            resolved = resolve_app_name(raw_name)
            speak(f"Opening {raw_name}.")

            def _get_title():
                try:
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    l    = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    b    = ctypes.create_unicode_buffer(l + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, b, l + 1)
                    return b.value
                except Exception:
                    return ""

            old_title = _get_title()
            subprocess.Popen(resolved, shell=True)
            changed = wait_for_window_change(old_title, timeout=8)
            if not changed:
                time.sleep(3)
            log_event(command, action, f"launched {resolved}")

        elif action == "new_tab":
            pyautogui.hotkey("ctrl", "t")
            time.sleep(1)
            speak("Opened new tab.")
            log_event(command, action, "new tab opened")

        elif action == "address_bar":
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.3)
            speak("Address bar focused.")
            log_event(command, action, "address bar focused")

        elif action == "navigate":
            url = parsed.get("url", "")
            if url:
                speak(f"Navigating to {url}.")
                navigate_to_url(url)
                time.sleep(2)
                desc = describe_screen()
                speak(f"Page loaded. {desc}")
                log_event(command, action, url)
            else:
                speak("I did not catch the website address.")

        elif action == "click_element":
            target = parsed.get("target", "")

            # Alias map — handles mishearing and shorthand
            ALIAS_MAP = {
                "good helper":        "gemma 4 good hackathon",
                
            }
            target_lower = target.lower().strip()
            if target_lower in ALIAS_MAP:
                target = ALIAS_MAP[target_lower]
            else:
                for alias, replacement in ALIAS_MAP.items():
                    if alias in target_lower:
                        target = replacement
                        break
            print(f"[ALIAS] Resolved target: '{target}'")

            # Website name → switch browser tab
            if target.lower().strip() in WEBSITE_NAMES:
                speak(f"Switching to {target}.")
                try:
                    import urllib.request
                    with urllib.request.urlopen("http://localhost:9222/json", timeout=3) as r:
                        pages = json.loads(r.read().decode())
                    match = next(
                        (p for p in pages
                         if target.lower() in p.get("url", "").lower()
                         or target.lower() in p.get("title", "").lower()),
                        None
                    )
                    if match:
                        pyautogui.hotkey("alt", "tab")
                        time.sleep(0.5)
                        navigate_to_url(match.get("url", ""))
                        time.sleep(2)
                        desc = describe_screen()
                        speak(f"Switched to {target}. {desc}")
                        log_event(command, action, f"switched to tab: {target}")
                    else:
                        speak(f"No {target} tab found. Opening it now.")
                        url = f"https://web.{target}.com" if target == "whatsapp" else f"https://www.{target}.com"
                        navigate_to_url(url)
                        time.sleep(2)
                        speak(describe_screen())
                except Exception as e:
                    print(f"[TAB SWITCH] Error: {e}")
                    speak(f"Could not switch to {target}.")

            else:
                speak(f"Looking for {target}.")
                success = smart_click(target)
                if success:
                    time.sleep(1.5)
                    _, b64 = capture_screen()
                    context = call_ollama(
                        "You are helping a blind user understand what just happened on screen. "
                        "If a WhatsApp or messaging chat is now open with someone, "
                        "read the last 4 messages warmly like this: "
                        "'Your chat with [name] — [name] said: [message]. "
                        "You replied: [message]. [name] said: [message]. You said: [message].' "
                        "Go oldest to newest. "
                        "If no chat is open, describe what changed in one sentence.",
                        b64_image=b64,
                        temperature=0.0
                    )
                    speak(context)
                    log_event(command, action, f"clicked: {target}")
                else:
                    speak(f"I could not find {target} on the screen.")
                    log_event(command, action, f"not found: {target}")

        elif action == "search":
            query = parsed.get("query", "")
            speak(f"Searching for {query}.")
            if any(query.endswith(tld) for tld in [".com", ".org", ".net", ".io", ".in"]):
                navigate_to_url(query)
                time.sleep(2)
                desc = describe_screen()
                speak(f"Opened {query}. {desc}")
            else:
                pyautogui.hotkey("ctrl", "l")
                time.sleep(0.3)
                search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
                pyperclip.copy(search_url)
                pyautogui.hotkey("ctrl", "v")
                pyautogui.press("enter")
                time.sleep(3)
                speak("Reading the top results.")
                results = call_ollama(
                    "List the titles of the top 3 search results visible on screen. "
                    "One sentence only.",
                    b64_image=capture_screen()[1],
                )
                speak(f"Top results: {results}. Which one should I open?")
            log_event(command, action, query)

        elif action == "scroll":
            direction = parsed.get("direction", "down")
            speak(f"Scrolling {direction}.")
            screen_w, screen_h = get_actual_screen_size()
            pyautogui.moveTo(screen_w // 2, screen_h // 2)
            scroll_amount = -700 if direction == "down" else 700
            pyautogui.scroll(scroll_amount)
            time.sleep(1.0)
            log_event(command, action, direction)

        elif action == "type":
            text_to_type = parsed.get("text", parsed.get("query", ""))
            if text_to_type:
                speak(f"Typing: {text_to_type}.")
                pyperclip.copy(text_to_type)
                pyautogui.hotkey("ctrl", "v")
                speak("Done.")
                log_event(command, action, text_to_type)
            else:
                speak("I did not catch what to type.")

        elif action == "send_message":
            text_to_send = parsed.get("text", parsed.get("message", ""))
            if text_to_send:
                speak(f"Sending: {text_to_send}.")
                try:
                    import urllib.request, websocket as ws_lib
                    with urllib.request.urlopen("http://localhost:9222/json", timeout=3) as r:
                        pages = json.loads(r.read().decode())
                    page = next(
                        (p for p in pages if p.get("type") == "page"
                         and "web.whatsapp.com" in p.get("url", "")), None)
                    if page:
                        ws_url = page.get("webSocketDebuggerUrl")
                        ws = ws_lib.create_connection(ws_url, timeout=10,
                            header={"Origin": "http://localhost:9222"})
                        msg_id = [1]
                        def cdp_s(method, params=None):
                            payload = json.dumps({"id": msg_id[0], "method": method, "params": params or {}})
                            msg_id[0] += 1
                            ws.send(payload)
                            for _ in range(15):
                                resp = json.loads(ws.recv())
                                if resp.get("id") == msg_id[0] - 1:
                                    return resp
                            return {}
                        cdp_s("Runtime.enable")
                        js = """(function(){const box=document.querySelector('[aria-label="Type a message"],div[contenteditable="true"][role="textbox"]');if(box){box.focus();return true;}return false;})()"""
                        cdp_s("Runtime.evaluate", {"expression": js, "returnByValue": True})
                        ws.close()
                        time.sleep(0.3)
                except Exception:
                    pass
                pyperclip.copy(text_to_send)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("enter")
                speak("Message sent.")
                log_event(command, action, text_to_send)
            else:
                speak("I did not catch what to send.")

        elif action == "describe_current":
            _, b64 = capture_screen(max_size=1920)
            desc = call_ollama_chat(
                "Describe what is on my screen right now in 2-3 sentences.",
                b64_image=b64
            )
            speak(desc)
            log_event(command, action, desc)

        elif action == "read_content":
            speak("Reading for you.")
            content = read_screen_content()
            speak(content)
            log_event(command, action, content)

        elif action == "get_tabs":
            speak("Identifying open browser tabs.")
            tabs = get_browser_tabs()
            session["conversation"].append({
                "role": "assistant",
                "content": f"The open browser tabs are: {tabs}",
            })
            speak(f"I can see these tabs: {tabs}. Which one should I click?")
            log_event(command, action, tabs)

        elif action == "read_emails":
            speak("Checking your inbox.")
            result = read_emails()
            speak(result)
            session["conversation"].append({
                "role": "assistant",
                "content": f"I read the user's emails: {result}",
            })
            log_event(command, action, result)

        elif action == "urgent_emails":
            speak("Scanning for urgent emails.")
            result = check_urgent_emails()
            speak(result)
            log_event(command, action, result)

        elif action == "reply_email":
            reply_text = parsed.get("text", "").strip()
            if not reply_text:
                speak("What would you like to say in the reply?")
                reply_text = listen_for_command(recognizer, mic, timeout=10)
            if reply_text:
                result = reply_to_last_email(reply_text, recognizer, mic)
                speak(result)
                log_event(command, action, reply_text)
            else:
                speak("I did not catch what to reply.")

        elif action == "summarize_session":
            speak("Let me summarize what you did today.")
            summary = summarize_my_session()
            speak(summary)
            log_event(command, action, summary)

        elif action == "repeat":
            last = session["last_spoken"]
            if last:
                speak(last)
            else:
                speak("There is nothing to repeat yet.")
            log_event(command, action, "")

        elif action == "set_language":
            lang_name = parsed.get("language", "english").lower()
            lang_code  = LANGUAGE_MAP.get(lang_name, "en")
            session["tts_lang"] = lang_code
            speak(f"Language switched to {lang_name}.", lang=lang_code)
            log_event(command, action, lang_name)

        elif action == "chat":
            _, b64 = capture_screen(max_size=1920)
            answer = call_ollama(
                f"You are a voice assistant for a completely blind user. "
                f"They said: '{command}' "
                f"If this is about the screen, look at the screenshot and describe it fully. "
                f"If this is a general question, answer it clearly and helpfully. "
                f"Respond in natural spoken sentences, 3-4 sentences. "
                f"Never say you cannot see the screen.",
                b64_image=b64,
                temperature=0.3
            )
            if not answer:
                answer = parsed.get("answer", "I am not sure about that.")
            speak(answer)
            log_event(command, action, answer)

        else:
            _, b64 = capture_screen(max_size=1920)
            answer = call_ollama(
                   f"You are a voice assistant for a completely blind user. "
                   f"They said: '{command}' "
                   f"If this is about the screen, look at the screenshot and describe it fully. "
                   f"If this is a general question, answer it clearly and helpfully. "
                   f"Respond in natural spoken sentences, 3-4 sentences. "
                   f"Never say you cannot see the screen.",
                   b64_image=b64,
                   temperature=0.3
                  )
            speak(answer)
            log_event(command, "chat", answer)

        # After screen-changing actions — update context in conversation memory
        if action in ("open_app", "navigate", "click_element"):
            time.sleep(1.2)
            _, b64 = capture_screen(max_size=1920)
            ctx = call_ollama(
                "In one sentence, what is now open or visible on screen?",
                b64_image=b64, temperature=0.0
            )
            if ctx:
                session["conversation"].append({
                    "role": "assistant",
                    "content": f"[Screen update] {ctx}",
                })
            session["last_screen_desc"] = ctx

        elif action in ("scroll", "type"):
            time.sleep(1.0)
            new_desc = describe_screen()
            session["last_screen_desc"] = new_desc


# =====================================================================
# ▶️ ENTRY POINT
# =====================================================================

if __name__ == "__main__":
    start_accessibility_loop()
"""
selftest — ตรวจว่าจาร์วิสใช้ได้ครบทุกส่วนบนเครื่องนี้หรือยัง
(ไม่แตะงานของคุณ — ทดสอบในกรอบของตัวเอง)

วิธีใช้:  python selftest.py            ทดสอบทุกข้อ
          python selftest.py --no-mic   ข้ามข้อที่ต้องใช้ไมค์/เสียง
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        def run(*args, **kwargs):
            try:
                detail = fn(*args, **kwargs)
                RESULTS.append((name, True, detail or "โอเค"))
                print(f"  ✓ {name} — {detail or 'โอเค'}")
            except Exception as e:
                RESULTS.append((name, False, str(e)))
                print(f"  ✗ {name} — {e}")
                if os.getenv("SELFTEST_VERBOSE"):
                    traceback.print_exc()
        return run
    return deco


@check("Python 3.10-3.12")
def _py():
    v = sys.version_info
    assert (3, 10) <= v[:2] <= (3, 13), f"ได้ {v.major}.{v.minor} — แนะนำ 3.10-3.12"
    return f"{v.major}.{v.minor}.{v.micro}"


@check("แพ็กเกจที่จำเป็น")
def _pkgs():
    import importlib
    missing = []
    for mod in ("dotenv", "requests", "numpy", "sounddevice", "edge_tts", "miniaudio",
                "pyautogui", "pygetwindow", "pyperclip", "pycaw", "pyttsx3", "mss", "PIL",
                "faster_whisper", "typesafe_sdk"):
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    assert not missing, f"ยังไม่ได้ติดตั้ง: {', '.join(missing)} — รัน pip install -r requirements.txt"
    return "ครบทุกตัว"


@check("ไฟล์ .env / คีย์ TypeSafe")
def _env():
    key = (os.getenv("TYPESAFE_API_KEY") or "").strip()
    if not key and not (ROOT / ".env").exists():
        print("\n     💡 คัดลอก .env.example เป็น .env แล้วใส่คีย์:  copy .env.example .env\n")
    assert key, "ยังไม่ใส่ TYPESAFE_API_KEY ใน .env (จาร์วิสจะใช้กฎพื้นฐานแทน Jev ชั่วคราว)"
    return f"ใส่คีย์แล้ว ({key[:6]}...)"


@check("เสียงพูด (Edge TTS)")
def _tts():
    from speaker import Speaker
    s = Speaker(os.getenv("TTS_VOICE", "th-TH-NiwatNeural"), cache_dir=ROOT / ".tts-cache")
    s.speak("ทดสอบเสียง จาร์วิสพร้อมแล้วครับ", wait=True)
    assert not s.speaking
    return "ได้ยินเสียงตอบไหม ถ้าไม่ได้ยิน ลองระบุ SPK_DEVICE ใน .env"


@check("คุมเสียงเครื่อง (pycaw)")
def _vol():
    from actions import get_volume
    v = get_volume()
    return f"เสียงปัจจุบัน {v}%"


@check("คุมเมาส์/คีย์บอร์ด (pyautogui)")
def _pag():
    import pyautogui
    x, y = pyautogui.position()
    pyautogui.moveTo(x + 3, y, duration=0.1)
    pyautogui.moveTo(x, y, duration=0.1)
    return f"ขยับเมาส์ที่ ({x},{y}) ได้"


@check("แคปหน้าจอ")
def _shot():
    import mss
    with mss.mss() as sct:
        img = sct.grab(sct.monitors[1])
    assert img.size[0] > 0
    return f"จอ {img.size[0]}x{img.size[1]}"


@check("โมเดลถอดเสียง (faster-whisper)")
def _stt():
    import numpy as np
    from stt import Transcriber
    t = Transcriber(os.getenv("WHISPER_MODEL", "small"))
    t.load()
    text = t.transcribe(np.zeros(16000, dtype=np.float32))   # เสียงเงียบ 1 วิ
    return f"โหลดสำเร็จ (ถอดเสียงเงียบออกมาได้: '{text[:20] or '(ว่าง)'}')"


@check("ไมค์")
def _mic():
    import sounddevice as sd
    devs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
    assert devs, "ไม่เจอไมค์ — เสียบไมค์หรือตรวจ Settings › Privacy › Microphone"
    from stt import MicListener
    m = MicListener()
    floor = m.calibrate(0.8)
    m.close()
    assert floor >= 0, "อ่านค่าไมค์ไม่ได้"
    return f"{len(devs)} ตัว · เสียงแวดล้อม {floor:.4f} (ปกติ 0.002-0.02)"


@check("Jev ตอบกลับ (TypeSafe)")
def _jev():
    from jev_client import Choice, Jev
    from typesafe_sdk import Noul
    key = (os.getenv("TYPESAFE_API_KEY") or "").strip()
    assert key, "ไม่มีคีย์"
    j = Jev(key, os.getenv("JEV_MODEL", "jev-latest"))
    answers = j.ask("The user said: จาร์วิส เปิดยูทูบ",
                    {"is_command": Noul(instructions="Is this a command for the assistant?")})
    noul = answers["is_command"].noul
    assert noul > 0.5, f"คำตอบแปลก: {noul}"
    return f"ตอบถูก ({j.last_ms:.0f} ms · ${j.last_cost_usd:.6f})"


@check("อ่านจอ (OCR ทางเลือก)")
def _ocr():
    from actions import ocr_available
    if not ocr_available():
        return "ยังไม่ได้ติดตั้ง winsdk (ทางเลือก — pip install winsdk เพื่อเปิด 'อ่านจอ')"
    from actions import ocr_screen
    items = ocr_screen(5)
    return f"อ่านได้ {len(items)} บรรทัดแรก"


@check("เวลาภาษาไทย")
def _time():
    from actions import thai_time
    t = thai_time()
    assert t.startswith("ตอนนี้")
    return t


def main() -> None:
    no_mic = "--no-mic" in sys.argv
    print("─" * 62)
    print("  ตรวจสอบจาร์วิส เมอร์เซส (selftest)")
    print("─" * 62)
    _py()
    _pkgs()
    try:
        _env()
    except AssertionError:
        pass                      # ไม่มีคีย์ก็ทดสอบต่อได้
    try:
        _tts()
    except Exception:
        pass
    try:
        _vol()
    except Exception:
        pass
    try:
        _pag()
    except Exception:
        pass
    try:
        _shot()
    except Exception:
        pass
    try:
        _ocr()
    except Exception:
        pass
    try:
        _time()
    except Exception:
        pass
    if not no_mic:
        try:
            _stt()
        except Exception:
            pass
        try:
            _mic()
        except Exception:
            pass
        try:
            _jev()
        except Exception as e:
            if "ไม่มีคีย์" not in str(e):
                pass

    ok = sum(1 for _, good, _ in RESULTS if good)
    print("─" * 62)
    print(f"  ผล: {ok}/{len(RESULTS)} ผ่าน")
    for name, good, detail in RESULTS:
        if not good:
            print(f"  ✗ {name}: {detail}")
    print("─" * 62)


if __name__ == "__main__":
    main()

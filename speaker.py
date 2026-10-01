"""
speaker — พูดภาษาไทยด้วยเสียง Edge TTS (th-TH) เร็วและเสียงธรรมชาติ

- ประโยคสำเร็จรูป (คำตอบสั้นที่ใช้บ่อย) สังเคราะห์เสียงเก็บไว้ล่วงหน้า → ตอบได้ทันที
- แคชทั้งในหน่วยความจำและดิสก์ (.tts-cache) → ประโยคเดิมไม่ต้องขอเสียงใหม่
- เล่นเสียงเองผ่าน sounddevice → สั่งหยุดได้ทันที (ใช้ตอนผู้ใช้พูดแทรก)
- ถ้าออกไปเน็ตไม่ได้ จะใช้เสียง SAPI ในเครื่อง (pyttsx3) แทนโดยอัตโนมัติ
"""

from __future__ import annotations

import asyncio
import hashlib
import queue
import threading
import time
from pathlib import Path

import miniaudio
import sounddevice as sd


def _decode_mp3(mp3: bytes) -> tuple[int, "object"]:
    """mp3 → (samplerate, pcm int16 ndarray mono) เล่นกับ sounddevice ได้เลย"""
    import numpy as np
    dec = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16)
    arr = np.frombuffer(dec.samples, dtype=np.int16)
    if dec.nchannels > 1:
        arr = arr.reshape(-1, dec.nchannels)[:, 0].copy()   # เสียงพูดอยู่กึ่งกลาง เอาช่องซ้ายก็พอ
    return dec.sample_rate, arr


class _SapiFallback(threading.Thread):
    """เสียงสำรองจาก Windows เอง (SAPI) — ใช้เมื่อ Edge TTS ใช้ไม่ได้ (ออกไปเน็ตไม่ได้)"""

    def __init__(self):
        super().__init__(daemon=True)
        self._jobs: queue.Queue = queue.Queue()
        self.ok = False
        self.start()

    def run(self):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 190)
            self.ok = True
            while True:
                text, done = self._jobs.get()
                try:
                    engine.say(text)
                    engine.runAndWait()
                except Exception:
                    pass
                finally:
                    done.set()
        except Exception:
            self.ok = False
            while True:  # กลืนงานที่เหลือ ไม่ให้ค้าง
                if not self._jobs.get():
                    continue

    def speak(self, text: str, timeout: float = 30.0):
        done = threading.Event()
        self._jobs.put((text, done))
        done.wait(timeout)


class Speaker:
    def __init__(self, voice: str = "th-TH-NiwatNeural", rate: str = "+15%", pitch: str = "+0Hz",
                 cache_dir: Path | None = None, device: int | None = None, log=print):
        self.voice, self.rate, self.pitch = voice, rate, pitch
        self.device = device
        self.log = log
        self.speaking = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mem: dict[str, tuple[int, object]] = {}
        self._mem_order: list[str] = []
        self._cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._sapi: _SapiFallback | None = None

    # ── สังเคราะห์เสียง ────────────────────────────────────────────────────
    def _key(self, text: str) -> str:
        return hashlib.md5(f"{self.voice}|{self.rate}|{self.pitch}|{text}".encode()).hexdigest()

    async def _tts(self, text: str) -> bytes:
        import edge_tts
        com = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        buf = bytearray()
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                buf += chunk["data"]
        if not buf:
            raise RuntimeError("ไม่ได้รับเสียงกลับจาก Edge TTS")
        return bytes(buf)

    def synth(self, text: str) -> tuple[int, object]:
        """ขอ PCM ของประโยคนี้ (มีแคชใช้แคช) — ถ้าออกเน็ตไม่ได้จะ raise"""
        key = self._key(text)
        pcm = self._mem_get(key)
        if pcm is not None:
            return pcm
        path = self._cache_dir / f"{key}.mp3" if self._cache_dir else None
        if path and path.exists():
            pcm = _decode_mp3(path.read_bytes())
        else:
            mp3 = asyncio.run_coroutine_threadsafe(self._tts(text), self._loop).result(timeout=20)
            if path:
                path.write_bytes(mp3)
            pcm = _decode_mp3(mp3)
        self._mem_put(key, pcm)
        return pcm

    def _mem_get(self, key: str):
        return self._mem.get(key)

    def _mem_put(self, key: str, pcm) -> None:
        if key in self._mem:
            return
        self._mem[key] = pcm
        self._mem_order.append(key)
        while len(self._mem_order) > 300:      # จำกัดแรม (~300 ประโยคสั้นๆ)
            self._mem.pop(self._mem_order.pop(0), None)

    # ── เล่นเสียง ─────────────────────────────────────────────────────────
    def speak(self, text: str, wait: bool = True, on_done=None) -> None:
        """พูดหนึ่งประโยค — wait=True รอจนพูดจบ, ระหว่างนั้น self.stop() หยุดได้ทันที"""
        self.stop()
        self._stop.clear()
        self.speaking = True
        self._thread = threading.Thread(target=self._play, args=(text, on_done), daemon=True)
        self._thread.start()
        if wait:
            self.wait()

    def wait(self, timeout: float = 120.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _play(self, text: str, on_done) -> None:
        try:
            try:
                sr, pcm = self.synth(text)
            except Exception as e:             # ออกไปเน็ตไม่ได้ → เสียงในเครื่อง
                self.log(f"  ⚠️  Edge TTS ใช้ไม่ได้ ({e.__class__.__name__}) ใช้เสียง Windows แทน")
                if self._sapi is None:
                    self._sapi = _SapiFallback()
                if self._sapi.ok:
                    self._sapi.speak(text)
                return
            import numpy as np
            sd.play(pcm, samplerate=sr, device=self.device)
            while sd.get_stream().active:      # เล่นอยู่ → ระหว่างนี้ stop() มาหยุดได้
                if self._stop.is_set():
                    sd.stop()
                    return
                time.sleep(0.03)
        except Exception as e:
            self.log(f"  ⚠️  เล่นเสียงไม่สำเร็จ: {e}")
        finally:
            self.speaking = False
            sd.stop()
            if on_done and not self._stop.is_set():
                try:
                    on_done()
                except Exception:
                    pass

    def stop(self) -> None:
        """หยุดพูดทันที (ผู้ใช้พูดแทรก / สั่ง "หยุดพูด")"""
        self._stop.set()
        sd.stop()

    # ── พรีโหลดประโยคสำเร็จรูป ─────────────────────────────────────────────
    def preload(self, phrases, on_progress=None) -> None:
        """สังเคราะห์เสียงเก็บไว้ล่วงหน้า ให้คำตอบไวๆ ไม่ต้องรอเน็ตตอนตอบ"""
        phrases = [p for p in phrases if p and p not in self._mem]
        for i, p in enumerate(phrases, 1):
            try:
                self.synth(p)
            except Exception:
                return                         # ออกเน็ตไม่ได้ → ไว้ใช้เสียงสำรองตอนพูด
            if on_progress:
                on_progress(i, len(phrases))

"""
stt — ฟังไมค์ตลอดเวลา ตัดประโยคด้วยพลังงานเสียง (VAD) แล้วถอดเสียงเป็นข้อความไทย

- ถอดเสียงในเครื่องทั้งหมดด้วย faster-whisper (เสียงของคุณไม่ถูกส่งออกไปไหน)
- ไมค์เปิดค้างแบบ full duplex → ระหว่างที่จาร์วิสพูดยังวัดพลังงานได้ (ใช้พูดแทรกได้)
  เมื่อเปิด BARGE_IN ใน .env
"""

from __future__ import annotations

import queue
import threading
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

RATE = 16000
FRAME_MS = 30


class MicListener:
    """เปิดไมค์ค้างไว้ แล้วดึงทีละประโยค (บล็อกจนได้ยินเสียงพูดจบ)"""

    def __init__(self, silence_ms: float = 650, energy_mult: float = 3.0, device: int | None = None,
                 log=print):
        self.silence_ms = silence_ms
        self.energy_mult = energy_mult
        self.device = device
        self.log = log
        self.current_energy = 0.0          # พลังงานเฟรมล่าสุด (ให้ตัวพูดแทรกอ่านระหว่างเล่นเสียง)
        self._frames: queue.Queue = queue.Queue()
        self._noise_floor = 0.006          # ปรับหลังวัดเสียงแวดล้อม
        self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32",
                                      blocksize=RATE * FRAME_MS // 1000, callback=self._cb, device=device)
        self._stream.start()

    def _cb(self, indata, frames, time_info, status) -> None:
        self.current_energy = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        self._frames.put(indata[:, 0].copy())

    def calibrate(self, seconds: float = 1.0) -> float:
        """วัดเสียงแวดล้อมเพื่อตั้งเกณฑ์ — เงียบๆ หนึ่งวินาทีตอนเปิดโปรแกรม"""
        n = max(1, int(seconds * 1000 / FRAME_MS))
        rms = []
        self.drain()
        for _ in range(n):
            try:
                f = self._frames.get(timeout=seconds + 1)
                rms.append(float(np.sqrt(np.mean(f ** 2))))
            except queue.Empty:
                break
        self._noise_floor = max(0.003, float(np.median(rms)) if rms else 0.006)
        return self._noise_floor

    @property
    def threshold(self) -> float:
        return self._noise_floor * self.energy_mult

    def drain(self) -> None:
        """ทิ้งเสียงที่ค้างอยู่ในคิว (เช่น ตอนจาร์วิสพูดจบ)"""
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def record_utterance(self, idle_timeout: float = 60.0, max_sec: float = 12.0,
                         cancel: threading.Event | None = None) -> np.ndarray | None:
        """รอฟังประโยคถัดไป คืนเสียง float32 16kHz หรือ None ถ้าเงียบเกิน/ถูกยกเลิก
        idle_timeout = รอสูงสุดกี่วินาทีก่อนคืน None (วนกลับไปเช็คสถานะภายนอก)"""
        import time
        self.drain()
        pre: list[np.ndarray] = []          # เสียงก่อนขึ้นเกณฑ์ (กันตัดพยัญชนะต้นคำ)
        voiced: list[np.ndarray] = []
        silence_run = 0.0
        started_at: float | None = None
        frames_speaking = 0
        idle_deadline = time.monotonic() + idle_timeout
        max_pre = int(300 / FRAME_MS)
        while True:
            if cancel is not None and cancel.is_set():
                return None
            try:
                frame = self._frames.get(timeout=0.25)
            except queue.Empty:
                if started_at is None and time.monotonic() > idle_deadline:
                    return None
                continue
            rms = float(np.sqrt(np.mean(frame ** 2)))
            is_voice = rms > self.threshold
            now = time.monotonic()
            if started_at is None:
                if not is_voice:
                    pre.append(frame)
                    if len(pre) > max_pre:
                        pre.pop(0)
                    if now > idle_deadline:
                        return None
                    continue
                started_at = now
            if is_voice:
                frames_speaking += 1
                silence_run = 0.0
            else:
                silence_run += FRAME_MS / 1000
            voiced.append(frame)            # เก็บช่วงเงียบสั้นๆ ไว้ด้วย เผื่อหยุดหายใจกลางประโยค
            dur = now - started_at
            enough = frames_speaking >= 3   # สั้นกว่า ~90ms = เสียงรบกวน
            if dur >= max_sec:
                return np.concatenate(pre + voiced) if enough else None
            if silence_run >= self.silence_ms / 1000:
                return np.concatenate(pre + voiced) if enough else None

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass


class Transcriber:
    """faster-whisper รันในเครื่อง ภาษาไทย (โหลดครั้งเดียวใช้ตลอด)"""

    def __init__(self, model_size: str = "small", initial_prompt: str = "", log=print):
        self.model_size = model_size
        self.initial_prompt = initial_prompt
        self.log = log
        self.model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if self.model is not None:
            return
        with self._lock:
            if self.model is not None:
                return
            from faster_whisper import WhisperModel
            self.log(f"⏳ โหลดโมเดลถอดเสียง ({self.model_size}) ครั้งแรกอาจดาวน์โหลด ~460MB...")
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8",
                                      cpu_threads=max(2, __import__("os").cpu_count() or 4))
            self.log("  ✅ โมเดลถอดเสียงพร้อมแล้ว")

    def transcribe(self, audio: np.ndarray) -> str:
        """เสียง float32 16kHz → ข้อความไทย"""
        self.load()
        with self._lock:
            segments, _info = self.model.transcribe(
                audio.astype(np.float32), language="th", beam_size=1, vad_filter=True,
                initial_prompt=self.initial_prompt or None, condition_on_previous_text=False)
            text = "".join(getattr(s, "text", "") for s in segments).strip()
        return text


def save_wav(path: Path, audio: np.ndarray, rate: int = RATE) -> None:
    """เก็บประโยคเป็น WAV ไว้ทดสอบ (SAVE_UTTERANCES)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def list_devices() -> None:
    """รายชื่ออุปกรณ์เสียงในเครื่อง (เอาหมายเลขไปใส่ MIC_DEVICE/SPK_DEVICE)"""
    print("─" * 60)
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print(f"  ไมค์  #{i}: {d['name']}")
        if d["max_output_channels"] > 0:
            print(f"  ลำโพง #{i}: {d['name']}")
    print("─" * 60)

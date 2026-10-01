"""
Jev client — ตัวตัดสินใจเร็วของ TypeSafe (https://typesafe.ai)

หลักการเดียวกับ jarvisdemo001 บน Mac: ถาม Jev "ทุกคำถามพร้อมกัน" ในคำขอเดียว
(choice/score/noul fan-out) แล้วได้คำตอบ + ระดับความมั่นใจ (confidence) กลับมา
ทีเดียว — เร็ว (~0.3-1 วินาที) และไม่ต้องเดาสุ่ม ถ้าไม่มั่นใจก็ถามผู้ใช้ใหม่
"""

from __future__ import annotations

import time

from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
from typesafe_sdk import TypeSafeError

PRICE_PER_MTOK_INPUT = 0.042  # ดอลลาร์ต่อ input token 1 ล้าน (docs.typesafe.ai)


class JevError(RuntimeError):
    """เรียก Jev ไม่สำเร็จ (เน็ต/คีย์/โควตา) — ข้อความเป็นภาษาไทยพูดให้ผู้ใช้ฟังได้"""


class Jev:
    def __init__(self, api_key: str, model: str = "jev-latest", timeout: float = 12.0):
        if not api_key:
            raise JevError("ยังไม่ได้ใส่คีย์ TYPESAFE_API_KEY ในไฟล์ .env")
        try:
            self._client = TypeSafeClient(api_key=api_key, model=model, timeout=timeout)
        except TypeSafeError as e:
            raise JevError(f"คีย์ TypeSafe ใช้ไม่ได้: {e}") from e
        self.model = model
        self.last_ms = 0.0
        self.last_cost_usd = 0.0

    def ask(self, state: dict, questions: dict) -> dict:
        """ถามครั้งเดียว ได้คำตอบทุกข้อ — state คือสิ่งที่ Jev ต้องตัดสินใจ
        questions = {"ชื่อ": Choice(...)/Score(...)/Noul(...)} คืน {ชื่อ: คำตอบ}"""
        t0 = time.perf_counter()
        try:
            resp = self._client.system_one(state=state, questions=questions, model=self.model)
        except TypeSafeError as e:
            raise JevError(f"Jev ตอบไม่ได้: {e}") from e
        except Exception as e:  # เน็ตล่ม ฯลฯ
            raise JevError(f"ติดต่อ Jev ไม่ได้: {e}") from e
        self.last_ms = (time.perf_counter() - t0) * 1000
        try:
            self.last_cost_usd = resp.usage.input_tokens / 1e6 * PRICE_PER_MTOK_INPUT
        except Exception:
            self.last_cost_usd = 0.0
        return dict(resp.answers)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def choice(answer) -> tuple[str, float]:
    """ความมั่นใจของคำตอบแบบ choice → ("ตัวเลือก", confidence)"""
    return str(answer.choice), float(answer.confidence)


def score(answer) -> tuple[float, float]:
    """คำตอบแบบ score → (คะแนน 1..N, confidence)"""
    return float(answer.score), float(answer.confidence)


__all__ = ["Jev", "JevError", "Choice", "Score", "Noul", "choice", "score"]

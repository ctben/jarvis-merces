"""
hud — หน้าจอ J.A.R.V.I.S ลอยบนจอ Windows

วงกลมเรืองแสงเล็กๆ มุมจอ เปลี่ยนสีตามสถานะ:
  เทา = หยุดฟัง · ฟ้าหม่น = รอ · เขียว = กำลังฟัง · ส้ม = กำลังคิด · น้ำเงิน = กำลังพูด
ลากย้ายได้ · ดับเบิลคลิก = หยุด/เริ่มฟัง · คลิกขวา = เมนู
รันในเธรดของตัวเอง คุยกับโปรแกรมหลักผ่าน state/flag ที่ปลอดภัยต่อเธรด
"""

from __future__ import annotations

import threading
import tkinter as tk

SIZE = 168
TRANSPARENT = "#010101"

COLORS = {
    "off":       ("#1c1c1c", "#2e2e2e"),
    "idle":      ("#0b3c4d", "#12586e"),
    "listening": ("#0d5c33", "#18b45e"),
    "thinking":  ("#5c430c", "#c78f1e"),
    "speaking":  ("#0c2f63", "#1e63c7"),
}


class Hud(threading.Thread):
    def __init__(self, on_toggle=None, on_quit=None):
        super().__init__(daemon=True)
        self._state = "idle"
        self._want = None            # คำสั่งจากเธรดหลัก → เธรด tk
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.rect = (0, 0, 0, 0)     # (x, y, w, h) ตำแหน่งบนจอ (เก็บไว้ให้ตัวคุมคอมเลี่ยง)
        self.ready = threading.Event()

    # ── เรียกจากเธรดหลักได้ตลอด ───────────────────────────────────────────
    def set(self, state: str) -> None:
        self._state = state if state in COLORS else "idle"

    def close(self) -> None:
        """ขอปิดหน้าต่าง (เธรด tk จะปิดเองในรอบ tick ถัดไป)"""
        self._want = "destroy"

    @property
    def state(self) -> str:
        return self._state

    # ── วงจร tk ──────────────────────────────────────────────────────────
    def run(self) -> None:
        self.root = tk.Tk()
        self.root.title("jarvis-hud")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{SIZE}x{SIZE}+{sw - SIZE - 28}+{sh - SIZE - 68}")
        self.canvas = tk.Canvas(self.root, width=SIZE, height=SIZE, bg=TRANSPARENT,
                                highlightthickness=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)
        self._cx = self._cy = SIZE // 2
        self._rings: list[int] = []
        self._t = 0.0
        self._drag = None

        for btn in ("<Double-Button-1>", "<Double-Button-3>"):
            self.root.bind(btn, self._toggle)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<Button-3>", self._menu)
        self.root.after(40, self._tick)
        self.ready.set()
        self.root.mainloop()

    def _press(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _toggle(self, _e=None):
        if self.on_toggle:
            try:
                self.on_toggle()
            except Exception:
                pass

    def _menu(self, _e=None):
        m = tk.Menu(self.root, tearoff=0)
        state = self._state
        m.add_command(label="หยุดฟัง / เริ่มฟัง (ดับเบิลคลิก)", command=self._toggle)
        m.add_separator()
        m.add_command(label="ออก", command=self._quit)
        try:
            m.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            m.grab_release()

    def _quit(self):
        if self.on_quit:
            try:
                self.on_quit()
            except Exception:
                pass
        self.root.destroy()

    def _tick(self):
        if self._want == "destroy":
            self.root.destroy()
            return
        self._t += 0.12
        state = self._state
        inner, outer = COLORS[state]
        c = self.canvas
        c.delete("all")
        cx, cy = self._cx, self._cy
        active = state in ("listening", "thinking", "speaking")
        # วงนอกเต้นตุบๆ ตอนทำงาน
        pulse = 6 * abs(__import__("math").sin(self._t)) if active else 1.5
        c.create_oval(cx - 62 - pulse, cy - 62 - pulse, cx + 62 + pulse, cy + 62 + pulse,
                      outline=outer, width=2)
        c.create_oval(cx - 50, cy - 50, cx + 50, cy + 50, outline=outer, width=1)
        # วงใน
        c.create_oval(cx - 34, cy - 34, cx + 34, cy + 34, fill=inner, outline=outer, width=2)
        # แกนคอร์
        if state == "thinking":            # จุดหมุนรอบแกน
            ang = self._t % 6.283185
            dx, dy = 44 * __import__("math").cos(ang), 44 * __import__("math").sin(ang)
            c.create_oval(cx + dx - 4, cy + dy - 4, cx + dx + 4, cy + dy + 4, fill=outer, outline="")
        elif state == "speaking":          # ขีดสัญญาณเหมือนคลื่นเสียง
            for i, h in enumerate((8, 16, 24, 16, 8)):
                x = cx - 24 + i * 12
                c.create_line(x, cy - h, x, cy + h, fill=outer, width=3)
        elif state == "listening":         # วงคลื่นที่กำลังฟัง
            for r, a in ((40, 0.8), (56, 0.5)):
                c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=outer, width=1)
        else:
            c.create_oval(cx - 12, cy - 12, cx + 12, cy + 12, fill=outer, outline="")
        c.update_idletasks()
        try:
            self.rect = (self.root.winfo_x(), self.root.winfo_y(), SIZE, SIZE)
        except Exception:
            pass
        self.root.after(40, self._tick)

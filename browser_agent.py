"""
browser_agent — ค้นเว็บให้ และสรุปคำตอบสั้นๆ อ่านออกเสียงได้

เหมือนต้นฉบับแต่เบากว่า: ไม่ต้องติดตั้ง Playwright
- เปิดผลค้นหาในเบราว์เซอร์ของผู้ใช้ (Chrome/Edge/ค่าเริ่มต้น) ทันที
- ถ้ามี "สมองส่วนคุย" (LLM) จะดึงผลค้นหาจาก DuckDuckGo (html lite ไม่ต้องมีคีย์)
  แล้วให้ LLM สรุปเป็นภาษาพูดไทย 1-3 ประโยค พูดให้ฟังเลย
- ปลอดภัยเหมือนเดิม: ไม่ล็อกอิน ไม่กรอกรหัส ไม่ซื้อ ไม่ส่งฟอร์ม
"""

from __future__ import annotations

import re
import urllib.parse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "th,en;q=0.8"}

SEARCH_URL = {
    "google": "https://www.google.com/search?hl=th&q=",
    "bing": "https://www.bing.com/search?setlang=th&q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
}


def _open(url: str, browser: str = "chrome", profile: str = "") -> None:
    from actions import open_url_in_browser
    open_url_in_browser(url, browser, profile)


def search_url(query: str, engine: str = "google") -> str:
    return SEARCH_URL.get(engine, SEARCH_URL["google"]) + urllib.parse.quote_plus(query)


def open_search(query: str, browser: str = "chrome", profile: str = "", engine: str = "google") -> str:
    """เปิดหน้าค้นหา คืน URL"""
    url = search_url(query, engine)
    _open(url, browser, profile)
    return url


def open_youtube(query: str, browser: str = "chrome", profile: str = "") -> str:
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    _open(url, browser, profile)
    return url


def open_maps(query: str, browser: str = "chrome", profile: str = "") -> str:
    url = "https://www.google.com/maps/search/" + urllib.parse.quote_plus(query) + "?hl=th"
    _open(url, browser, profile)
    return url


def open_site(site_url: str, browser: str = "chrome", profile: str = "") -> str:
    if not site_url.startswith(("http://", "https://")):
        site_url = "https://" + site_url
    _open(site_url, browser, profile)
    return site_url


# ── ดึงผลค้นหาแบบข้อความ (สำหรับให้ LLM สรุป) ────────────────────────────

_TAG = re.compile(r"<[^>]+>")
_SQ = re.compile(r"\s+")


def _text(html: str) -> str:
    return _SQ.sub(" ", _TAG.sub(" ", html.replace("&amp;", "&").replace("&quot;", '"')
                                 .replace("&#x27;", "'").replace("&nbsp;", " "))).strip()


def fetch_results(query: str, limit: int = 6, timeout: float = 8.0) -> list[tuple[str, str]]:
    """DuckDuckGo lite → [(หัวข้อ, คำอธิบาย)] เรียงตามความเกี่ยวข้อง"""
    r = requests.post("https://lite.duckduckgo.com/lite/", data={"q": query}, headers=UA, timeout=timeout)
    r.raise_for_status()
    html = r.text
    results: list[tuple[str, str]] = []
    # หน้า lite เป็นตาราง: ลิงก์ผลค้นหาตามด้วยคำอธิบายใน <td class="result-snippet">
    links = re.findall(r'class="result-link"[^>]*>(.*?)</a>', html, re.S)
    snips = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', html, re.S)
    for title, snip in zip(links, snips):
        t, s = _text(title), _text(snip)
        if t:
            results.append((t, s[:300]))
        if len(results) >= limit:
            break
    return results


def web_answer(query: str, llm_chat, open_in: tuple[str, str] | None = None,
               browser: str = "chrome", profile: str = "") -> str:
    """ค้นเน็ตแล้วสรุปเป็นภาษาพูด — คืนข้อความสรุป (พูดได้) · ไม่มี LLM ก็เปิดผลค้นหาให้ดู
    open_in = (เว็บที่จะเปิด, ชนิด) เช่น (query, 'google') — จะเปิดให้ดูประกอบด้วย"""
    if open_in:
        what, kind = open_in
        (open_search if kind == "google" else open_youtube if kind == "youtube" else open_maps)(what, browser, profile)
    try:
        results = fetch_results(query)
    except Exception as e:
        if open_in:
            return "เปิดผลค้นหาให้แล้วนะ แต่สรุปให้ฟังไม่ได้ ขอโทษ"
        raise RuntimeError(f"ค้นเว็บไม่ได้: {e}") from e
    if not results:
        return "หาไม่เจออะ ลองเปลี่ยนคำถามดูไหม"
    if llm_chat is None:
        return "เปิดผลค้นหาให้แล้ว ลองดูบนจอนะ"
    joined = "\n".join(f"- {t}: {s}" for t, s in results)
    messages = [
        {"role": "system", "content":
            "คุณช่วยสรุปผลค้นหาจากเว็บเป็นภาษาไทยแบบภาษาพูด สั้นที่สุด ไม่เกิน 3 ประโยค "
            "บอกเฉพาะสาระสำคัญที่ตอบคำถาม ถ้ามีตัวเลข/ราคาให้เอ่ยชัดๆ ไม่ใช้ markdown ไม่ลงท้ายอ้างลิงก์"},
        {"role": "user", "content": f"คำถาม: {query}\nผลค้นหา:\n{joined}"},
    ]
    return (llm_chat(messages, max_tokens=220, temperature=0.3) or "").strip() or "เปิดผลค้นหาให้แล้ว ลองดูบนจอนะ"


__all__ = ["open_search", "open_youtube", "open_maps", "open_site", "search_url",
           "fetch_results", "web_answer"]

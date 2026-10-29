"""
打字游戏自动打字脚本
- 截屏 -> 找蓝色标签 -> OCR 识别单词 -> 优先打离你最近(最靠下)的怪 -> 回车
用法:
    python typer_bot.py              # 运行(3 秒后开始, 切到游戏窗口)
    python typer_bot.py --test a.png # 只识别一张截图, 输出 debug.png, 不打字
热键: F8 暂停/继续, F9 退出
"""
import argparse
import ctypes
from ctypes import wintypes
import itertools
import os
import re
import sys
import threading
import time

import cv2
import mss
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from i18n import resolve_language, tr

# ---------------- 配置 ----------------
MONITOR = 1            # 第几个显示器 (mss 编号, 1 = 主屏)
# 只在这个区域里找单词 (占整个屏幕的比例: 左, 上, 右, 下)
# 避开: 顶部 HP/按键提示, 左边聊天头像, 右上分数/BONUS, 底部玩家名/激活水印/任务栏
REGION = (0.12, 0.11, 0.81, 0.87)
# 区域里再挖掉的横条 (屏幕高度比例: 上, 下) —— 输入框, 免得把自己打的字又认成怪
IGNORE_BANDS = [(0.62, 0.69)]
# 标签按颜色的优先级, 数字越小越先打; 灰色/其他颜色不打。颜色判断见 classify()
PRIORITY = {"red": 0, "gold": 0, "green": 0, "blue": 1}
MAX_SPELLINGS = 8       # i/I/l 分不清时, 同一个词最多换几种拼法试
SIGN_DELAY = 3.0        # 红色禁止标志出现后再过几秒才停手
SIGN_WAIT = 3.0         # 红色禁止标志消失后再等几秒才继续打字
SIGN_CHECK_EVERY = 3    # 打字时每打几个字母检查一次禁止标志
SIGN_RADIUS = (0.008, 0.03)  # 禁止标志的半径 (占屏幕宽度比例), 认不到就调这里
BEFORE_TYPE = 0.15     # 每个词开始打之前等一下(秒), 游戏卡字就调大
KEY_DELAY = 0.03       # 每个按键间隔(秒)
SHIFT_DELAY = 0.03     # 标点要按 Shift 时, Shift 按下/松开前后的等待
BEFORE_ENTER = 0.08    # 打完字到按回车之间等一下
AFTER_ENTER = 0.15     # 回车后等待
RETRY_COOLDOWN = 1.5   # 同一个词打完后多久内不再重打 (等怪死亡动画)
FORGET_AFTER = 5.0     # 一个词多久没出现就忘掉它的重试记录 (之后再出现当新词)
MIN_SCORE = 0.6        # OCR 置信度下限
# -------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
VK_SHIFT, VK_RETURN, VK_F8, VK_F9 = 0x10, 0x0D, 0x77, 0x78
GAME_EXECUTABLES = {"ffxiv_dx11.exe", "ffxiv.exe"}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
# 这两个返回 SHORT, 不设 restype 的话 -1 (打不出的字符) 会变成 65535
user32.VkKeyScanW.restype = ctypes.c_short
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class GameNotFocused(Exception):
    """Typing was skipped because FFXIV is not the foreground application."""


def game_is_focused():
    """Check the foreground process executable, not its easily spoofed title."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return False
    try:
        name = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(name))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
            return False
        return os.path.basename(name.value).lower() in GAME_EXECUTABLES
    finally:
        kernel32.CloseHandle(handle)


def require_game_focus():
    if not game_is_focused():
        raise GameNotFocused


stop_requested = threading.Event()
pause_requested = threading.Event()


class StopRequested(Exception):
    """Raised when the F9 emergency stop has been requested."""


def check_stop():
    if stop_requested.is_set():
        raise StopRequested


def watch_hotkeys(language="en"):
    """Poll the documented key-down bit independently of OCR and typing.
    F9 stops, F8 toggles pause; OCR can take a while, so the main loop polling would miss short taps."""
    was_down = {VK_F8: False, VK_F9: False}
    while not stop_requested.is_set():
        for vk in was_down:
            down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if down and not was_down[vk]:
                if vk == VK_F9:
                    stop_requested.set()
                    return
                if pause_requested.is_set():
                    pause_requested.clear()
                    print(tr("resumed", language))
                else:
                    pause_requested.set()
                    print(tr("paused", language))
            was_down[vk] = down
        time.sleep(0.01)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]


def _send_scan(vk, up=False):
    # 用扫描码发送, DirectX 游戏也能收到
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=1, u=_INPUTunion(ki=KEYBDINPUT(0, scan, flags, 0, None)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def tap(vk, shift=False):
    check_stop()
    require_game_focus()
    # Shift 前后都要留时间, 不然游戏会把顺序搞乱
    if shift:
        _send_scan(VK_SHIFT)
        time.sleep(SHIFT_DELAY)
    try:
        # Re-check after Shift; always release keys even if focus changes.
        check_stop()
        require_game_focus()
        _send_scan(vk)
        try:
            time.sleep(KEY_DELAY / 2)
        finally:
            _send_scan(vk, up=True)
    finally:
        if shift:
            time.sleep(SHIFT_DELAY)
            _send_scan(VK_SHIFT, up=True)
            time.sleep(SHIFT_DELAY)
    time.sleep(KEY_DELAY)


def type_text(text, guard=None):
    time.sleep(BEFORE_TYPE)
    # 大小写无所谓, 字母一律小写打, 只有标点才需要 Shift
    for k, ch in enumerate(text.lower()):
        check_stop()
        require_game_focus()
        if guard and k % SIGN_CHECK_EVERY == 0:
            guard.wait()  # 打到一半出现禁止标志就停下, 消失后接着打
        r = user32.VkKeyScanW(ord(ch))
        if r == -1 or r & 0x600:
            continue  # 当前键盘布局打不出, 或者要 Ctrl/Alt (AltGr) 才能打, 跳过
        tap(r & 0xFF, shift=bool(r & 0x100))
    time.sleep(BEFORE_ENTER)
    if guard:
        guard.wait()
    tap(VK_RETURN)


def has_stop_sign(img, screen_w):
    """画面里有没有红色禁止标志 (红圈 + 斜杠): 外轮廓是圆的, 里面被斜杠分成洞"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 150, 150), (8, 255, 255)) | cv2.inRange(hsv, (170, 150, 150), (180, 255, 255))
    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return False
    for i, c in enumerate(cs):
        if hier[0][i][3] != -1:
            continue
        _, r = cv2.minEnclosingCircle(c)
        if not SIGN_RADIUS[0] <= r / screen_w <= SIGN_RADIUS[1]:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not 0.8 <= w / h <= 1.25 or cv2.contourArea(c) / (np.pi * r * r) < 0.8:
            continue  # 不是圆 (红色框是长方形)
        if any(hier[0][j][3] == i and cv2.contourArea(cs[j]) > 0.03 * np.pi * r * r for j in range(len(cs))):
            return True  # 圆里有洞 = 圆环
    return False


class StopSignGuard:
    """禁止标志出现 SIGN_DELAY 秒后停手, 消失 SIGN_WAIT 秒后再继续打
    后台线程一直盯着标志, 这样出现/消失的时间点准确, 不受 OCR 慢的影响"""

    def __init__(self, mon, language="en"):
        self.language = language
        self.screen_w = mon["width"]
        self.box = {"left": mon["left"] + int(REGION[0] * mon["width"]),
                    "top": mon["top"] + int(REGION[1] * mon["height"]),
                    "width": int((REGION[2] - REGION[0]) * mon["width"]),
                    "height": int((REGION[3] - REGION[1]) * mon["height"])}
        self.first_seen = None  # 这一次标志第一次出现的时间
        self.last_seen = 0.0
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        with mss.mss() as sct:  # mss 不能跨线程用, 线程里自己开一个
            while True:
                try:
                    img = cv2.cvtColor(np.array(sct.grab(self.box)), cv2.COLOR_BGRA2BGR)
                    seen = has_stop_sign(img, self.screen_w)
                except Exception as exc:  # 偶尔截图失败别让线程静默退出, 否则再也认不到标志
                    print(tr("capture_failed", self.language, error=exc))
                    time.sleep(1)
                    continue
                now = time.time()
                if seen:
                    if self.first_seen is None:
                        self.first_seen = now
                        print(tr("sign_seen", self.language, delay=SIGN_DELAY))
                    self.last_seen = now
                elif self.first_seen is not None and now - self.last_seen >= SIGN_WAIT:
                    self.first_seen = None  # 消失够久了, 这一次结束
                time.sleep(0.05)

    def blocked(self):
        now = time.time()
        first_seen = self.first_seen  # 只读一次: 后台线程随时可能把它改成 None
        return first_seen is not None and now - first_seen >= SIGN_DELAY and now - self.last_seen < SIGN_WAIT

    def wait(self):
        check_stop()
        if not self.blocked():
            return
        print(tr("sign_blocked", self.language))
        while self.blocked():
            check_stop()
            time.sleep(0.05)
        print(tr("sign_cleared", self.language))


def clean(text):
    # 保留字母、数字、空格和英文标点; OCR 认出的中文全角标点转成半角
    text = text.translate(str.maketrans("，。！？：；“”‘’（）", ",.!?:;\"\"''()"))
    text = re.sub(r"[^\x20-\x7E]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def spellings(word):
    """i/I/l 容易认错, 给出几种可能的拼法 (都是小写), 最可能的排第一"""
    first = []
    for k, c in enumerate(word):
        if c in "Il|":
            # I/l 长得一样: 整句第一个字母或单独的 "I" 先试 i, 其他位置先试 l (句子里的 let/like 等)
            alone = (k == 0 or not word[k - 1].isalpha()) and (k + 1 == len(word) or not word[k + 1].isalpha())
            first.append("i" if k == 0 or alone else "l")
        else:
            first.append(c.lower())
    first = "".join(first)
    # 只换 I/l, 带点的小写 i 不会认错, 不动
    amb = [k for k, c in enumerate(word) if c in "Il|"]
    swap = {"i": "l", "l": "i"}
    out = [first]
    # 之后按"改动的字母越少越先试"换拼法
    for n in range(1, len(amb) + 1):
        for ks in itertools.combinations(amb, n):
            if len(out) >= MAX_SPELLINGS:
                return out
            s = list(first)
            for k in ks:
                s[k] = swap[s[k]]
            out.append("".join(s))
    return out


def is_ambiguous(word):
    """有没有真正分不清 I/l 的地方: 任何大写 I 或 |, 或者整句开头的小写 l"""
    return bool(re.search(r"[I|]|^l", word))


def forget_stale(words, last_seen, tries, recent, now):
    """记下这次认到的词; 很久没出现的词清掉重试记录, 不然同一个词下一波再出现会被排到最后、
    从错误的拼法开始试"""
    for word in words:
        last_seen[word.lower()] = now
    for key in [k for k, t in last_seen.items() if now - t > FORGET_AFTER]:
        del last_seen[key]
        tries.pop(key, None)
        recent.pop(key, None)


def classify(hsv, x0, y0, x1, y1):
    """根据文字颜色和框底色判断标签颜色, 返回 'blue'/'gold'/'green'/'red' 或 None(灰色/背景字, 不打)
    框底色取文字外面紧贴的一圈 (0.1~0.3 个字高): 真标签这一圈是均匀的框色,
    直接写在背景上的字 (比如 Boss 战中间的红字提示横幅) 这一圈是杂乱的背景"""
    h = y1 - y0
    a, b = max(int(0.1 * h), 1), max(int(0.3 * h), 2)
    ring = np.concatenate([hsv[max(y0 - b, 0):max(y0 - a, 0), x0:x1].reshape(-1, 3),
                           hsv[y1 + a:y1 + b, x0:x1].reshape(-1, 3),
                           hsv[y0:y1, max(x0 - b, 0):max(x0 - a, 0)].reshape(-1, 3),
                           hsv[y0:y1, x1 + a:x1 + b].reshape(-1, 3)]).astype(int)
    if len(ring) == 0:
        return None
    fh, fs, fv = np.median(ring, 0)
    hue_spread = np.std(ring[:, 0])
    px = hsv[y0:y1, x0:x1].reshape(-1, 3).astype(int)
    th, ts, tv = np.median(px[px[:, 2] >= np.percentile(px[:, 2], 70)], 0)  # 最亮的 30% 当作文字
    if 105 <= fh <= 130 and fs >= 120 and fv >= 120:
        return "blue"                      # 蓝底白字
    if (fh <= 12 or fh >= 165) and fs >= 100 and fv >= 100:
        return "red"                       # 红底
    if hue_spread > 25:
        return None                        # 周围颜色杂乱 = 没有框, 是背景上的字
    if 15 <= fh <= 65 and fv >= 110 and 8 <= th <= 30 and ts >= 60 and tv >= 140:
        return "gold"                      # 金底, 橙黄字
    if 60 <= fh <= 85 and fs >= 70 and fv >= 90 and 50 <= th <= 80 and ts >= 60:
        return "green"                     # 绿底绿字
    return None


def find_words(ocr, frame):
    """返回 [(word, x, y, score, color, priority)], 红/金/绿在前, 同色按 y 从大到小 (越靠下越近)"""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = int(REGION[0] * w), int(REGION[1] * h), int(REGION[2] * w), int(REGION[3] * h)
    roi = frame[y0:y1, x0:x1].copy()
    for b0, b1 in IGNORE_BANDS:
        roi[max(int(b0 * h) - y0, 0):max(int(b1 * h) - y0, 0)] = 0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    rh, rw = roi.shape[:2]
    result, _ = ocr(roi)
    words = []
    for box, text, score in result or []:
        if len(clean(text)) < 2 or float(score) < MIN_SCORE:
            continue
        pts = np.array(box, dtype=np.int32)
        bx0, by0 = np.maximum(pts.min(0), 0)
        bx1, by1 = pts.max(0)
        color = classify(hsv, bx0, by0, bx1, by1)
        if color is None:
            continue
        # 整图识别时偶尔会吞掉空格, 把文字紧贴着裁出来再认一次, 字母一样才用它补空格
        pad = (by1 - by0) // 8
        crop = roi[max(by0 - pad, 0):min(by1 + pad, rh), max(bx0 - pad, 0):min(bx1 + pad, rw)]
        rec, _ = ocr(crop, use_det=False, use_cls=False)
        if rec:
            squash = lambda s: clean(s).replace(" ", "").lower()
            if squash(rec[0][0]) == squash(text) and clean(rec[0][0]).count(" ") > clean(text).count(" "):
                text = rec[0][0]
        word = clean(text)
        words.append((word, (bx0 + bx1) // 2 + x0, (by0 + by1) // 2 + y0, float(score),
                      color, PRIORITY[color]))
    words.sort(key=lambda t: (t[5], -t[2]))
    return words


def test(path, language="en"):
    ocr = RapidOCR()
    frame = cv2.imread(path)
    if frame is None:
        raise SystemExit(tr("image_unreadable", language, path=path))
    t = time.time()
    words = find_words(ocr, frame)
    print(tr("elapsed", language, seconds=time.time() - t))
    h, w = frame.shape[:2]
    region = frame[int(REGION[1] * h):int(REGION[3] * h), int(REGION[0] * w):int(REGION[2] * w)]
    status = tr("sign_present", language) if has_stop_sign(region, w) else tr("sign_absent", language)
    print(tr("sign_status", language, status=status))
    for w_ in words:
        print(w_[:5], tr("ambiguous", language) if is_ambiguous(w_[0]) else "",
              tr("spellings", language), spellings(w_[0]))
        cv2.putText(frame, f"{w_[0]} [{w_[4]}]",(w_[1] - 60, w_[2] + 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (int(REGION[0] * w), int(REGION[1] * h)), (int(REGION[2] * w), int(REGION[3] * h)), (0, 255, 0), 2)
    for b0, b1 in IGNORE_BANDS:
        cv2.rectangle(frame, (int(REGION[0] * w), int(b0 * h)), (int(REGION[2] * w), int(b1 * h)), (0, 0, 255), 2)
    cv2.imwrite("debug.png", frame)
    print(tr("debug_saved", language))


def run(language="en"):
    stop_requested.clear()
    pause_requested.clear()
    threading.Thread(target=watch_hotkeys, args=(language,), daemon=True).start()
    ocr = RapidOCR()
    recent = {}     # word -> 上次打的时间
    tries = {}      # word -> 打过几次
    last_seen = {}  # word -> 上次认到的时间
    last_error = 0.0
    print(tr("starting", language))
    time.sleep(3)
    with mss.mss() as sct:
        mon = sct.monitors[MONITOR]
        guard = StopSignGuard(mon, language)
        while True:
            check_stop()
            if pause_requested.is_set():
                time.sleep(0.1)
                continue
            if not game_is_focused():
                time.sleep(0.1)
                continue
            guard.wait()
            try:
                frame = cv2.cvtColor(np.array(sct.grab(mon)), cv2.COLOR_BGRA2BGR)
                detected = find_words(ocr, frame)
            except (cv2.error, ValueError, TypeError, IndexError, OSError) as exc:
                # A single corrupt capture / OCR result should not end the session.
                if time.monotonic() - last_error > 5:
                    print(tr("capture_failed", language, error=exc))
                    last_error = time.monotonic()
                time.sleep(0.1)
                continue
            now = time.time()
            forget_stale([t[0] for t in detected], last_seen, tries, recent, now)
            # 排序: 所有拼法都试过还没消失的词最后 (多半是标签重叠认错了),
            # I/l 分不清的词其次, 剩下的按颜色优先级、离你远近 (find_words 已排好)
            words = sorted(detected,
                           key=lambda t: (tries.get(t[0].lower(), 0) >= len(spellings(t[0])),
                                          is_ambiguous(t[0])))
            for word, x, y, score, color, _ in words:
                key = word.lower()
                if now - recent.get(key, 0) < RETRY_COOLDOWN:
                    continue
                # 上次打了没消失, 就换一种 i/l 拼法再试
                opts = spellings(word)
                text = opts[tries.get(key, 0) % len(opts)]
                print(tr("typing", language, text=text, word=word, color=color, y=y, score=score))
                try:
                    type_text(text, guard)
                except GameNotFocused:
                    print(tr("not_focused", language))
                    break
                recent[key] = time.time()
                tries[key] = tries.get(key, 0) + 1
                time.sleep(AFTER_ENTER)
                break  # 打完一个就重新截图 (画面已变化)
            else:
                time.sleep(0.03)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Keybound Brawler auto typer / 自动打字脚本")
    ap.add_argument("--test", help="Recognize a screenshot without typing / 用截图测试识别")
    ap.add_argument("--lang", choices=("auto", "en", "zh"), default="auto",
                    help="Console language / 控制台语言 (default: auto)")
    a = ap.parse_args()
    language = resolve_language(a.lang)
    try:
        if a.test:
            test(a.test, language)
        else:
            run(language)
    except (StopRequested, KeyboardInterrupt):
        print(tr("exiting", language))
    except Exception:
        import traceback
        traceback.print_exc()
        if getattr(sys, "frozen", False):
            input(tr("error_exit", language))  # 打包成 exe 双击运行时, 别让窗口一闪而过

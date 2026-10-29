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


class StopRequested(Exception):
    """Raised when the F9 emergency stop has been requested."""


def check_stop():
    if stop_requested.is_set():
        raise StopRequested


def watch_emergency_stop():
    """Poll the documented key-down bit independently of OCR and typing."""
    was_down = False
    while not stop_requested.is_set():
        down = bool(user32.GetAsyncKeyState(VK_F9) & 0x8000)
        if down and not was_down:
            stop_requested.set()
            return
        was_down = down
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
        if r == -1:
            continue
        tap(r & 0xFF, shift=bool(r & 0x100))
    time.sleep(BEFORE_ENTER)
    if guard:
        guard.wait()
    tap(VK_RETURN)

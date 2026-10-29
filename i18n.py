"""Small, dependency-free console translations for English and Simplified Chinese."""

import locale


MESSAGES = {
    "starting": {"en": "Starting in 3 seconds. Switch to the game window. F8: pause/resume; F9: quit.",
                 "zh": "3 秒后开始, 请切到游戏窗口。F8 暂停/继续, F9 退出"},
    "paused": {"en": "Paused", "zh": "暂停"},
    "resumed": {"en": "Resumed", "zh": "继续"},
    "exiting": {"en": "Exiting", "zh": "退出"},
    "sign_seen": {"en": "No-typing sign detected; stopping in {delay:g} seconds",
                  "zh": "发现禁止标志, {delay:g} 秒后停手"},
    "sign_blocked": {"en": "No-typing sign: typing paused...", "zh": "禁止标志, 停止打字..."},
    "sign_cleared": {"en": "Sign cleared: resuming", "zh": "标志消失, 继续"},
    "elapsed": {"en": "Elapsed: {seconds:.2f}s", "zh": "耗时 {seconds:.2f}s"},
    "sign_status": {"en": "No-typing sign: {status}", "zh": "禁止标志: {status}"},
    "sign_present": {"en": "present (typing disabled)", "zh": "有 (不会打字)"},
    "sign_absent": {"en": "absent", "zh": "无"},
    "ambiguous": {"en": "ambiguous I/l", "zh": "I/l分不清"},
    "spellings": {"en": "Spellings:", "zh": "拼法:"},
    "debug_saved": {"en": "Saved debug.png", "zh": "已保存 debug.png"},
    "typing": {"en": "Typing: {text} (recognized {word}, {color}, y={y}, confidence={score:.2f})",
               "zh": "打: {text}  (认到 {word}, {color}, y={y}, conf={score:.2f})"},
    "focus_lost": {"en": "FFXIV is not in the foreground; typing paused",
                   "zh": "FFXIV 不在前台, 已暂停输入"},
    "test_help": {"en": "Recognize words in one screenshot without typing",
                  "zh": "用截图测试识别"},
    "error_exit": {"en": "Error. Press Enter to close the window",
                   "zh": "出错了, 按回车关闭窗口"},
}


def resolve_language(requested="auto", system_locale=None):
    """Select English by default, or Simplified Chinese for Chinese locales."""
    if requested in ("en", "zh"):
        return requested
    if requested != "auto":
        raise ValueError(f"Unsupported language: {requested}")
    if system_locale is None:
        system_locale = locale.getlocale()[0] or ""
    code = system_locale.replace("-", "_").lower()
    return "zh" if code.startswith("zh") or code.startswith("chinese") else "en"


def tr(key, language, **values):
    """Format one console message in the selected language."""
    return MESSAGES[key][language].format(**values)

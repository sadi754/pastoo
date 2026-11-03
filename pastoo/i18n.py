"""English or Persian for what the app shows outside its window: the tray menu and tooltip, the
notifications. (The window has its own translations, web/i18n.js; the logs and the command line
stay in English.) Settings -> App -> Language: "auto" follows Windows' display language."""
import ctypes

from . import settings

LANGUAGES = ("auto", "en", "fa")
_LANG_PERSIAN = 0x29

FA = {
    "Open Pastoo": "باز کردن Pastoo", "Back up now": "همین حالا بکاپ بگیر", "Exit": "خروج",
    "No backups set up yet - open Pastoo to add a folder": "هنوز بکاپی تنظیم نشده - Pastoo را باز کنید و یک پوشه اضافه کنید",
    "Backing up {name}": "در حال بکاپ {name}", " - {i}/{total} bundles, {sent}": " - {i}/{total} بسته، {sent}",
    "{name}: the last backup failed": "{name}: آخرین بکاپ ناموفق بود",
    "{name}: an automatic backup waits for your OK": "{name}: یک بکاپ خودکار منتظر تأیید شماست",
    "Last backup: {ago}": "آخرین بکاپ: {ago}", " - time for a backup": " - وقت بکاپ است",
    "never": "هرگز", "just now": "همین الان", "{n} min ago": "{n} دقیقه پیش", "{n} h ago": "{n} ساعت پیش",
    "{n} days ago": "{n} روز پیش",
    "Backup finished": "بکاپ تمام شد", "{name}: {bundles} bundles, {sent} uploaded": "{name}: {bundles} بسته، {sent} آپلود شد",
    "Backup failed": "بکاپ ناموفق بود", "see the log": "لاگ را ببینید",
    "Automatic backup waits for you": "بکاپ خودکار منتظر شماست",
    "{name}: {why}. Open Pastoo, look at the changes, then press Back up now.":
        "{name}: {why}. Pastoo را باز کنید، تغییرات را ببینید و بعد «همین حالا بکاپ بگیر» را بزنید.",
    "Time for a backup": "وقت بکاپ است",
    "{name}: {since}, {changed} files changed. Right-click the tray icon -> Back up now.":
        "{name}: {since}، {changed} فایل عوض شده. روی آیکون tray کلیک راست کنید ← همین حالا بکاپ بگیر.",
    "{days} days since the last backup": "{days} روز از آخرین بکاپ", "never backed up": "هنوز بکاپ نگرفته",
    "Automatic backups don't run while Pastoo is closed.\n\nExit anyway?":
        "وقتی Pastoo بسته است، بکاپ خودکار انجام نمی‌شود.\n\nبا این حال خارج می‌شوید؟",
}
_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def windows_language():
    """"fa" when Windows shows itself in Persian, else "en"."""
    try:
        return "fa" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == _LANG_PERSIAN else "en"
    except (AttributeError, OSError):
        return "en"


def language(data=None):
    """The language in use: "en" or "fa"."""
    chosen = (data or settings.load()).get("language", "auto")
    return chosen if chosen in ("en", "fa") else windows_language()


def t(text, **values):
    fa = language() == "fa"
    out = FA.get(text, text) if fa else text
    if values:
        out = out.format(**{k: (str(v).translate(_DIGITS) if fa and isinstance(v, int) else v) for k, v in values.items()})
    return out

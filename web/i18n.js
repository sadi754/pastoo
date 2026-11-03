"use strict";
// The window in English or Persian. The English text is the key: t("{n} new", { n }) gives it back in
// the language in use, with the values filled in. The page's own text (index.html) is translated by
// translatePage(); messages from the app (Python) by tMsg(). Run before app.js.

let LANG = "en";

const FA = {
  // ---- the page (index.html) ----
  "Dashboard": "داشبورد", "History": "تاریخچه", "Restore": "بازیابی", "Settings": "تنظیمات",
  "Lost the connection to Pastoo - is it still running in the tray?": "ارتباط با Pastoo قطع شد - هنوز در tray در حال اجراست؟",
  "Welcome to Pastoo": "به Pastoo خوش آمدید",
  "Pastoo backs up your folders to your own files.ir account. The first backup uploads everything; after that only what changed goes up. Three steps to start:":
    "Pastoo از پوشه‌های شما روی حساب files.ir خودتان بکاپ می‌گیرد. بکاپ اول همه‌چیز را آپلود می‌کند؛ از آن به بعد فقط چیزی که عوض شده بالا می‌رود. سه قدم برای شروع:",
  "Open Settings": "باز کردن تنظیمات",
  "When": "زمان", "Result": "نتیجه", "New": "جدید", "Changed": "تغییرکرده", "Deleted": "پاک‌شده", "Uploaded": "آپلود",
  "Bundles": "بسته‌ها", "Show older runs": "اجراهای قدیمی‌تر",
  "Choose a run to see what it backed up.": "یک اجرا را انتخاب کنید تا ببینید از چه چیزهایی بکاپ گرفته.",
  "What to restore from": "بازیابی از کجا", "Find a file or folder ...": "جستجوی فایل یا پوشه ...",
  "Loading ...": "در حال بارگذاری ...", "Tick the files or folders to get back.": "فایل‌ها یا پوشه‌هایی را که می‌خواهید برگردانید تیک بزنید.",
  "Where they were": "سر جای خودشان", "Another folder": "یک پوشه‌ی دیگر", "e.g. D:\\Restored": "D:\\Restored",
  "Browse ...": "انتخاب ...", "Replace files that are already there": "جایگزینی فایل‌هایی که از قبل هستند",
  "otherwise they are skipped": "وگرنه رد می‌شوند", "Check the backup": "بررسی بکاپ",
  "Downloads bundles from files.ir and checks every file in them against the checksum taken when it was backed up - so you know the backup really can be restored.":
    "بسته‌ها را از files.ir دانلود می‌کند و هر فایل داخلشان را با checksum زمان بکاپ مقایسه می‌کند - تا مطمئن شوید بکاپ واقعاً قابل بازیابی است.",
  "Check 5 random bundles": "بررسی ۵ بسته‌ی تصادفی", "Check everything": "بررسی همه", "Stop": "توقف",
  "Test the connection": "آزمایش اتصال", "Paste a new key (my.files.ir: account settings → Developers)": "یک کلید جدید بچسبانید (my.files.ir: تنظیمات حساب ← Developers)",
  "Save key": "ذخیره‌ی کلید",
  "The key is kept in Windows Credential Manager (Windows Credentials → Pastoo/files.ir), not in a file.":
    "کلید در Windows Credential Manager نگه داشته می‌شود (Windows Credentials ← Pastoo/files.ir)، نه در یک فایل.",
  "Limits": "محدودیت‌ها", "Read from files.ir": "خوانده از files.ir", "Set by hand": "دستی", "Check again": "بررسی دوباره",
  "Space": "فضا", "GB": "گیگابایت", "Files": "فایل‌ها", "Per file": "هر فایل", "MB": "مگابایت", "Save": "ذخیره",
  "Backup jobs": "کارهای بکاپ", "Add a folder": "افزودن پوشه", "App": "برنامه",
  "Start with Windows": "اجرا با ویندوز", "in the tray, without the window": "در tray، بدون پنجره",
  "Remind me after": "یادآوری بعد از", "days without a backup": "روز بدون بکاپ", "(only when files changed)": "(فقط وقتی فایل‌ها عوض شده باشند)",
  "Language": "زبان", "Same as Windows": "مثل ویندوز",
  "Show / hide this job's settings": "نمایش / پنهان کردن تنظیمات این کار", "unsaved changes": "تغییرات ذخیره‌نشده",
  "Remove": "حذف", "Name": "نام", "Folder on files.ir": "پوشه روی files.ir", "Folder to back up": "پوشه‌ای که بکاپ گرفته می‌شود",
  "This job has backups already, so its folder and its folder on files.ir stay as they are.":
    "این کار از قبل بکاپ دارد، برای همین پوشه‌اش و پوشه‌اش روی files.ir همان‌طور می‌مانند.",
  "Skip folders named": "رد کردن پوشه‌هایی با اسم", "one per line, anywhere in the tree": "هر خط یکی، هر جای درخت",
  "Skip these paths": "رد کردن این مسیرها", "relative to the folder, e.g. Projects/old": "نسبت به پوشه، مثلاً Projects/old",
  "Skip files matching": "رد کردن فایل‌های مطابق", "e.g. *.mkv or ~$*": "مثلاً *.mkv یا ~$*",
  "+ Add common skips": "+ افزودن موارد رایج",
  "Python / Node / PlatformIO build and cache folders, Windows thumbnail files, Office lock files":
    "پوشه‌های build و cache پایتون / Node / PlatformIO، فایل‌های thumbnail ویندوز، فایل‌های قفل Office",
  "Bundle size, MB": "اندازه‌ی بسته، مگابایت", "a folder up to this = one zip": "پوشه‌ی تا این اندازه = یک zip",
  "Big file, MB": "فایل بزرگ، مگابایت", "goes up on its own": "جدا آپلود می‌شود",
  "Keep old versions": "نگهداری نسخه‌های قبلی", "newest per bundle ...": "جدیدترین‌ها برای هر بسته ...",
  "... or for days": "... یا به مدت روز", "whichever keeps more": "هر کدام بیشتر نگه دارد",
  "Automatic backup": "بکاپ خودکار", "Off - only when I press Back up now": "خاموش - فقط وقتی خودم دکمه‌ی بکاپ را می‌زنم",
  "Every day at a set time": "هر روز سر یک ساعت", "Every few hours": "هر چند ساعت", "Time": "ساعت",
  "Every, hours": "هر چند ساعت", "after the last backup": "بعد از آخرین بکاپ",
  "While Pastoo runs in the tray; if the PC was off at that time, a few minutes after you sign in. An automatic backup that would delete or change many files at once waits for you to look first.":
    "وقتی Pastoo در tray در حال اجراست؛ اگر کامپیوتر آن موقع خاموش بوده، چند دقیقه بعد از ورود به ویندوز. بکاپ خودکاری که بخواهد یک‌جا فایل‌های زیادی را پاک یا عوض کند، اول منتظر نگاه شما می‌ماند.",
  "Undo changes": "برگرداندن تغییرات", "Changes": "تغییرات", "Close": "بستن", "Back up now": "همین حالا بکاپ بگیر",
  "Show / hide details": "نمایش / پنهان کردن جزئیات", "Last backup": "آخرین بکاپ", "Backed up": "بکاپ‌شده",
  "On files.ir": "روی files.ir", "Old versions": "نسخه‌های قبلی", "Review changes": "دیدن تغییرات",
  "Check for changes": "بررسی تغییرات", "Recent runs": "اجراهای اخیر",

  // ---- app.js ----
  "never": "هرگز", "just now": "همین الان", "{n} min ago": "{n} دقیقه پیش", "{n} h ago": "{n} ساعت پیش", "{n} days ago": "{n} روز پیش",
  "Done": "انجام شد", "No changes": "بدون تغییر", "Failed": "ناموفق", "Stopped": "متوقف شد", "Running": "در حال اجرا",
  "Waited for OK": "منتظر تأیید ماند",
  "First backup: {files}": "بکاپ اول: {files}", "{n} new": "{n} جدید", "{n} changed": "{n} تغییرکرده", "{n} deleted": "{n} پاک‌شده",
  "{bundles} · {size} before zipping": "{bundles} · {size} پیش از zip",
  "<b>{files} deleted</b> since the last backup (in red below). The backup will no longer have them in its current bundles; the old bundles stay in <b>_versions</b> for at least 30 days. If a deletion was a mistake, close this and restore the file first.":
    "<b>{files} پاک شده</b> از آخرین بکاپ (قرمز در پایین). بکاپ دیگر آن‌ها را در بسته‌های فعلی‌اش نخواهد داشت؛ بسته‌های قبلی دست‌کم ۳۰ روز در <bdi><b>_versions</b></bdi> می‌مانند. اگر پاک شدنی اشتباه بوده، این را ببندید و اول آن فایل را بازیابی کنید.",
  "Nothing changed since the last backup.": "از آخرین بکاپ چیزی عوض نشده.",
  "Bundles to upload": "بسته‌هایی که آپلود می‌شوند", "Bundles uploaded": "بسته‌های آپلودشده",
  "Bundles split into smaller ones (old ones go to _versions)": "بسته‌هایی که به بسته‌های کوچک‌تر تقسیم شدند (قبلی‌ها به ⁦_versions⁩ می‌روند)",
  "in {bundle}": "در {bundle}", "{files}, {size}": "{files}، {size}",
  "every day at {time}": "هر روز ساعت {time}", "every {hours}": "هر {hours}", ", next {when}": "، بعدی {when}", ", next soon": "، بعدی به‌زودی",
  "automatic: {how}{next}": "خودکار: {how}{next}",
  "{files} in use by another program ({which}): the last backed-up copy stays": "{files} دست برنامه‌ی دیگری است ({which}): آخرین نسخه‌ی بکاپ‌شده می‌ماند",
  ", and {bundles} with other changes wait": "، و {bundles} با تغییرات دیگر منتظر می‌ماند",
  ". Close it, then back up again.": ". ببندیدش، بعد دوباره بکاپ بگیرید.",
  "Changes in {name}": "تغییرات در {name}", "Looking for changes ...": "در حال جستجوی تغییرات ...",
  "{source} · checked {when}": "{source} · بررسی {when}", "{files} will leave the current backup": "{files} از بکاپ فعلی بیرون می‌رود",
  "Back up now (with {n} deletions)": "همین حالا بکاپ بگیر (با {n} پاک‌شده)",
  "Checking ...": "در حال بررسی ...", "no changes": "بدون تغییر", "bundles to tidy up": "بسته‌هایی برای مرتب کردن",
  "Bundles to tidy up": "بسته‌هایی برای مرتب کردن",
  "Backing up": "در حال بکاپ", "Last backup failed": "آخرین بکاپ ناموفق بود", "Needs your OK": "منتظر تأیید شما",
  "Changes to back up": "تغییراتی برای بکاپ", "Never backed up": "هنوز بکاپ نگرفته", "Time for a backup": "وقت بکاپ است",
  "Up to date": "به‌روز", "none yet": "هنوز ندارد", "{n} files": "{n} فایل",
  "Not checked yet": "هنوز بررسی نشده", "Checking failed: {error}": "بررسی ناموفق بود: {error}",
  "No changes since the last backup": "از آخرین بکاپ تغییری نیست", "· checked {when}": "· بررسی {when}",
  "{bundles} to upload": "{bundles} برای آپلود",
  "The automatic backup waits for you: {why}. Look at the changes, then press Back up now if they are right.":
    "بکاپ خودکار منتظر شماست: {why}. تغییرات را ببینید و اگر درست بودند، «همین حالا بکاپ بگیر» را بزنید.",
  "Backing up - {progress}": "در حال بکاپ - {progress}", "looking for changes": "جستجوی تغییرات",
  "Last backup {when}": "آخرین بکاپ {when}",
  "Uploading": "در حال آپلود", "Finishing ...": "در حال تمام کردن ...",
  "{i} / {bundles} · {size} sent · {s} s": "{i} / {bundles} · {size} ارسال‌شده · {s} ثانیه",
  "Backup finished: {bundles}, {size} uploaded": "بکاپ تمام شد: {bundles}، {size} آپلود شد", " · report {report}": " · گزارش {report}",
  "Nothing changed - the backup is up to date.": "چیزی عوض نشده - بکاپ به‌روز است.",
  "Stopped. The next backup continues where this one stopped.": "متوقف شد. بکاپ بعدی از همین‌جا ادامه می‌دهد.",
  "The backup failed: {error}. Run it again - it continues where it stopped.": "بکاپ ناموفق بود: {error}. دوباره اجرایش کنید - از جایی که مانده ادامه می‌دهد.",
  "see the log": "لاگ را ببینید",
  "Another backup is running (from the command line?). Try again when it is done.": "یک بکاپ دیگر در حال اجراست (از خط فرمان؟). وقتی تمام شد دوباره امتحان کنید.",
  "The automatic backup waits for you: {why}.": "بکاپ خودکار منتظر شماست: {why}.",
  "No backups yet.": "هنوز بکاپی نیست.", "took {s} s": "{s} ثانیه طول کشید", "{size} uploaded": "{size} آپلود شد",
  "report: {report}": "گزارش: {report}", "Nothing had changed.": "چیزی عوض نشده بود.",
  "No details were kept for this run.": "جزئیاتی از این اجرا نگه داشته نشده.",
  "New backup job": "کار بکاپ جدید",
  "Changing the bundle sizes re-packs the folders: the next backup uploads most bundles again.":
    "عوض کردن اندازه‌ی بسته‌ها پوشه‌ها را از نو بسته‌بندی می‌کند: بکاپ بعدی بیشتر بسته‌ها را دوباره آپلود می‌کند.",
  "Files that the new rules skip leave the backup: the next backup shows them as deleted (red in the preview).":
    "فایل‌هایی که قواعد جدید رد می‌کنند از بکاپ بیرون می‌روند: بکاپ بعدی آن‌ها را پاک‌شده نشان می‌دهد (قرمز در پیش‌نمایش).",
  "Start with Windows is off (App, below): automatic backups only run while Pastoo is open.":
    "«اجرا با ویندوز» خاموش است (بخش برنامه، پایین): بکاپ خودکار فقط وقتی Pastoo باز است انجام می‌شود.",
  "Choose the folder to back up.": "پوشه‌ای را که می‌خواهید بکاپ بگیرید انتخاب کنید.", "Counting ...": "در حال شمارش ...",
  "Backed up with these rules: <b>{files} · {size}</b> in about {bundles}": "با این قواعد بکاپ گرفته می‌شود: <b>{files} · {size}</b> در حدود {bundles}",
  " &nbsp;·&nbsp; skipped: {files} · {size}": " &nbsp;·&nbsp; ردشده: {files} · {size}", "Biggest skipped:": "بزرگ‌ترین ردشده‌ها:",
  "Saving ...": "در حال ذخیره ...", "Saved.": "ذخیره شد.",
  "Remove \"{name}\" from Pastoo?\nIts backup on files.ir stays as it is.": "«{name}» از Pastoo حذف شود؟\nبکاپش روی files.ir همان‌طور می‌ماند.",
  "The folder dialog works in the app's own window - type the folder instead.": "پنجره‌ی انتخاب پوشه فقط در پنجره‌ی خود برنامه کار می‌کند - مسیر پوشه را تایپ کنید.",
  "{name} backup": "{name} backup",
  "Key saved in Windows Credential Manager.": "کلید در Windows Credential Manager ذخیره شده.",
  "No files.ir key yet - paste one below.": "هنوز کلید files.ir ندارید - یکی را پایین بچسبانید.",
  "Key checked with files.ir and saved in Windows Credential Manager.": "کلید با files.ir بررسی و در Windows Credential Manager ذخیره شد.",
  "Cancel": "انصراف", "Checking the key with files.ir ...": "در حال بررسی کلید با files.ir ...", "Connecting to files.ir ...": "در حال اتصال به files.ir ...",
  "{space} · {files} · {file} per file": "{space} · {files} · {file} برای هر فایل",
  "files.ir did not say ({error}) - using {which}: {limits}": "files.ir جواب نداد ({error}) - استفاده از {which}: {limits}",
  "what it said last time": "آخرین جوابش", "the Free plan's limits": "محدودیت‌های پلن رایگان",
  " · read {when}": " · خوانده {when}", "unknown": "نامعلوم", "{used} of {total} ({p}%)": "{used} از {total} ({p}٪)",
  "about {used} of {total} ({p}%)": "حدود {used} از {total} ({p}٪)",
  "Could not ask files.ir about the space: {error}. ": "پرسیدن فضا از files.ir ممکن نشد: {error}. ",
  "Space is the whole account's; files are Pastoo's own (other apps' files on the account count too). Files bigger than {size} go up in parts. Checked {when}.":
    "فضا مال کل حساب است؛ فایل‌ها فقط مال Pastoo (فایل‌های برنامه‌های دیگر روی حساب هم حساب می‌شوند). فایل‌های بزرگ‌تر از {size} در چند تکه آپلود می‌شوند. بررسی {when}.",
  "space": "فضا", "number of files": "تعداد فایل",
  "files.ir is {p}% full ({what}) - see Settings → files.ir. A bigger plan, fewer old versions, or more skips will help.":
    "files.ir {p}٪ پر است ({what}) - تنظیمات ← files.ir را ببینید. پلن بزرگ‌تر، نسخه‌های قبلی کمتر یا رد کردن بیشتر کمک می‌کند.",
  "Asking files.ir ...": "در حال پرسیدن از files.ir ...",
  "Latest backup": "آخرین بکاپ", "Old versions (bundles that were replaced)": "نسخه‌های قبلی (بسته‌هایی که جایگزین شدند)",
  "until {when} · {key} ({size})": "تا {when} · {key} ({size})", "Check everything ({bundles}, {size})": "بررسی همه ({bundles}، {size})",
  "Downloading that version from files.ir ...": "در حال دانلود آن نسخه از files.ir ...",
  "Nothing in here.": "این‌جا چیزی نیست.", "Nothing matches.": "چیزی پیدا نشد.", "More match - type more of the name.": "موارد بیشتری هست - بیشتر از اسم را تایپ کنید.",
  "<b>{files}</b> chosen · {size}": "<b>{files}</b> انتخاب شده · {size}", "Restore {files}": "بازیابی {files}",
  "Not checked yet.": "هنوز بررسی نشده.", "everything": "همه",
  "Last check: {when} ({ago}) · {what}, {files} · {result}": "آخرین بررسی: {when} ({ago}) · {what}، {files} · {result}",
  "all good": "همه سالم",
  "Restored {files} into {to}.": "{files} در {to} بازیابی شد.", "The restore failed: {error}": "بازیابی ناموفق بود: {error}",
  " {n} files were already there and skipped - tick \"Replace\" to overwrite.": " {n} فایل از قبل بود و رد شد - برای جایگزینی «جایگزینی» را تیک بزنید.",
  " {files} FAILED the check and were not written: {which}": " {files} در بررسی رد شد و نوشته نشد: {which}",
  "All {files} in {bundles} are fine.": "همه‌ی {files} در {bundles} سالم‌اند.", "Stopped.": "متوقف شد.",
  "{problems}: ": "{problems}: ", "The check failed: {error}": "بررسی ناموفق بود: {error}",
  "Choose the folder to restore into - a full path such as D:\\Restored.": "پوشه‌ای را که می‌خواهید در آن بازیابی شود انتخاب کنید - یک مسیر کامل مثل D:\\Restored.",
  "Replace files in {folder} with their backed-up copies?\nChanges made to them since that backup will be lost.":
    "فایل‌های {folder} با نسخه‌ی بکاپ‌شده‌شان جایگزین شوند؟\nتغییراتی که از آن بکاپ به بعد رویشان انجام شده از بین می‌رود.",
  "Connected - files.ir accepts the key.": "وصل شد - files.ir کلید را قبول می‌کند.", "files.ir refused: {message}": "files.ir قبول نکرد: {message}",
  "Could not open that version.": "باز کردن آن نسخه ممکن نشد.",
};

// counted words: plural(n, "file") -> "3 files" / "۳ فایل" (Persian doesn't change the word)
const FA_WORDS = { file: "فایل", bundle: "بسته", hour: "ساعت", "deleted file": "فایل پاک‌شده", "random bundle": "بسته‌ی تصادفی",
                   problem: "مشکل" };

// what the app (Python) sends, with values in it; the field names of the forms' checks
const FA_FIELDS = { "name": "نام", "source": "پوشه", "remote root": "پوشه روی files.ir", "bundle mb": "اندازه‌ی بسته",
  "big file mb": "فایل بزرگ", "keep versions": "تعداد نسخه‌های قبلی", "keep days": "روزهای نگهداری", "space gb": "فضا",
  "files": "تعداد فایل", "file mb": "حجم هر فایل", "skip_dir_names": "پوشه‌های ردشده", "skip_paths": "مسیرهای ردشده",
  "skip_files": "فایل‌های ردشده" };
const FA_MESSAGES = {
  "automatic backup: off, every day or every few hours": "بکاپ خودکار: خاموش، هر روز یا هر چند ساعت",
  "automatic backup: a time such as 21:00": "بکاپ خودکار: ساعتی مثل 21:00",
  "automatic backup: every 1 to 168 hours": "بکاپ خودکار: هر ۱ تا ۱۶۸ ساعت",
  "wait until the backup / restore / check has finished": "صبر کنید تا بکاپ / بازیابی / بررسی تمام شود",
  "that job is gone": "آن کار دیگر وجود ندارد",
  "this job has backups already - its folder and its folder on files.ir stay as they are": "این کار از قبل بکاپ دارد - پوشه‌اش و پوشه‌اش روی files.ir همان‌طور می‌مانند",
  "reminder: between 1 and 365 days": "یادآوری: بین ۱ تا ۳۶۵ روز", "limits: automatic or set by hand": "محدودیت‌ها: خودکار یا دستی",
  "language: automatic, English or Persian": "زبان: خودکار، انگلیسی یا فارسی",
  "that does not look like a files.ir key": "این شبیه کلید files.ir نیست",
  "the folder on files.ir: a plain name, without / \\ : * ? \" < > |": "پوشه روی files.ir: یک اسم ساده، بدون / \\ : * ? \" < > |",
  "A backup, restore or check is running already.": "یک بکاپ، بازیابی یا بررسی از قبل در حال اجراست.",
  "A backup is running (the command line?) - try again when it is done.": "یک بکاپ در حال اجراست (خط فرمان؟) - وقتی تمام شد دوباره امتحان کنید.",
  "A backup is already running.": "یک بکاپ از قبل در حال اجراست.", "another backup was running": "یک بکاپ دیگر در حال اجرا بود",
  "no files.ir key yet - add it on the Settings page": "هنوز کلید files.ir ندارید - در تنظیمات اضافه‌اش کنید",
};
const FA_PATTERNS = [
  [/^not a full folder path: (.*)$/s, "مسیر کامل یک پوشه نیست: $1"],
  [/^not in the backup: (.*)$/s, "در بکاپ نیست: $1"], [/^not in that version: (.*)$/s, "در آن نسخه نیست: $1"],
  [/^(.+): missing or too long$/, (m, f) => `${field(f)}: خالی است یا خیلی بلند`],
  [/^(.+): between (.+) and (.+)$/, (m, f, a, b) => `${field(f)}: بین ${a} و ${b}`],
  [/^(.+): a list of names$/, (m, f) => `${field(f)}: فهرستی از اسم‌ها`],
  [/^no such folder: (.*)$/s, "چنین پوشه‌ای نیست: $1"],
  [/^the folder on files\.ir is used by "(.*)" already$/, "این پوشه روی files.ir را «$1» استفاده می‌کند"],
  [/^files\.ir did not accept this key: (.*)$/s, "files.ir این کلید را قبول نکرد: $1"],
  [/^Something went wrong: (.*)$/s, "مشکلی پیش آمد: $1"], [/^Could not look for changes: (.*)$/s, "جستجوی تغییرات ممکن نشد: $1"],
  [/^Could not open that old version: (.*)$/s, "باز کردن آن نسخه‌ی قبلی ممکن نشد: $1"],
  [/^the folder (.*) isn't there - is its drive connected\?$/s, "پوشه‌ی $1 وجود ندارد - درایوش وصل است؟"],
  [/^(\d+) of (\d+) files deleted$/, (m, a, b) => `${num(+a)} فایل از ${num(+b)} فایل پاک شده`],
  [/^(\d+) of (\d+) files changed at once$/, (m, a, b) => `${num(+a)} فایل از ${num(+b)} فایل یک‌جا عوض شده`],
  [/^(\d+) bundles failed$/, (m, a) => `${num(+a)} بسته ناموفق بود`],
];

function field(f) { return FA_FIELDS[f] || f; }

const ARROW = () => (LANG === "fa" ? "←" : "→");          // "changes -> bundles", in the reading direction
const digits = (text) => (LANG === "fa" ? String(text).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]) : String(text));

function num(n, digits) {
  const opts = digits === undefined ? {} : { minimumFractionDigits: digits, maximumFractionDigits: digits };
  return Number(n).toLocaleString(LANG === "fa" ? "fa-IR" : "en-US", opts);
}

function t(text, values) {
  let out = LANG === "fa" && FA[text] !== undefined ? FA[text] : text;
  if (values) out = out.replace(/\{(\w+)\}/g, (all, k) => (typeof values[k] === "number" ? num(values[k]) : values[k] ?? ""));
  return out;
}

// a message from the app, in the language in use
function tMsg(message) {
  if (LANG !== "fa" || !message) return message;
  if (FA_MESSAGES[message] !== undefined) return FA_MESSAGES[message];
  for (const [re, to] of FA_PATTERNS) if (re.test(message)) return message.replace(re, to);
  return message;
}

// Persian: the page's own text, placeholders and tooltips; the templates too (cards and forms are made from them)
function translatePage() {
  if (LANG !== "fa") return;
  const walk = (root) => {
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = it.nextNode(); node; node = it.nextNode()) {
      const key = node.nodeValue.replace(/\s+/g, " ").trim();
      if (key && FA[key] !== undefined) node.nodeValue = node.nodeValue.replace(/\S[\s\S]*\S|\S/, FA[key]);
    }
    for (const e of root.querySelectorAll("[placeholder], [title], [aria-label], optgroup[label]")) {
      for (const a of ["placeholder", "title", "aria-label", "label"]) {
        const v = e.getAttribute(a);
        if (v && FA[v] !== undefined) e.setAttribute(a, FA[v]);
      }
    }
    for (const e of root.querySelectorAll("[data-t]")) e.innerHTML = FA_HTML[e.dataset.t] ?? e.innerHTML;
    for (const tpl of root.querySelectorAll("template")) walk(tpl.content);
  };
  walk(document.body);
}

// bits of the page with markup inside, translated whole (their data-t names them)
const FA_HTML = {
  "welcome-1": "در <b>my.files.ir</b>: تنظیمات حساب ← <b>Developers</b> ← یک کلید API بسازید.",
  "welcome-2": "این‌جا، <b>تنظیمات ← files.ir</b>: کلید را بچسبانید و <b>ذخیره‌ی کلید</b> را بزنید.",
  "welcome-3": "<b>تنظیمات ← کارهای بکاپ ← افزودن پوشه</b>، بعد برگردید و <b>همین حالا بکاپ بگیر</b> را بزنید.",
  "no-jobs": "هنوز از چیزی بکاپ گرفته نشده - در صفحه‌ی <a href=\"#settings\">تنظیمات</a> یک پوشه اضافه کنید.",
};

function setLanguage(lang) {
  LANG = lang === "fa" ? "fa" : "en";
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === "fa" ? "rtl" : "ltr";
  translatePage();
}

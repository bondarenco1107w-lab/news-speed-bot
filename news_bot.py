import os, re, json, time, html, hashlib, email.utils, signal
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ["BOT_TOKEN"]
CHAT = str(os.environ.get("CHAT_ID") or "7365523999")
API = f"https://api.telegram.org/bot{TOKEN}"
F = "state_news.json"
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "21000"))
SCAN_EVERY = int(os.environ.get("SCAN_EVERY", "60"))
PS = 6
HOT_N = 3
PUSH_MAX = 5
UA = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}


def gn(site, lang="en"):
    if lang == "ru":
        return f"https://news.google.com/rss/search?q=site:{site}+when:1d&hl=ru&gl=RU&ceid=RU:ru"
    return f"https://news.google.com/rss/search?q=site:{site}+when:1d&hl=en-US&gl=US&ceid=US:en"


SRC = {
    "reuters": ("Reuters", [gn("reuters.com")]),
    "ap": ("AP", [gn("apnews.com")]),
    "bbc": ("BBC", ["https://feeds.bbci.co.uk/news/world/rss.xml", gn("bbc.com")]),
    "aj": ("Al Jazeera", ["https://www.aljazeera.com/xml/rss/all.xml", gn("aljazeera.com")]),
    "f24": ("France 24", ["https://www.france24.com/en/rss", gn("france24.com")]),
    "dw": ("DW", ["https://rss.dw.com/rdf/rss-en-all", gn("dw.com")]),
    "yna": ("Yonhap", ["https://en.yna.co.kr/RSS/news.xml", gn("en.yna.co.kr")]),
    "aa": ("AA (RU)", ["https://www.aa.com.tr/ru/rss/default?cat=guncel", gn("aa.com.tr/ru", "ru")]),
}
LABELS = {"🔥 Горячее": "hot", "🆕 Свежее": "all", "Reuters": "reuters", "AP": "ap", "BBC": "bbc",
          "Al Jazeera": "aj", "France 24": "f24", "DW": "dw", "Yonhap": "yna", "AA (RU)": "aa"}
NAMES = {"hot": "🔥 Горячее", "all": "🆕 Свежее", **{k: v[0] for k, v in SRC.items()}}
KB = json.dumps({"keyboard": [
    [{"text": "🔥 Горячее"}, {"text": "🆕 Свежее"}],
    [{"text": "Reuters"}, {"text": "AP"}, {"text": "BBC"}, {"text": "Al Jazeera"}],
    [{"text": "France 24"}, {"text": "DW"}, {"text": "Yonhap"}, {"text": "AA (RU)"}],
    [{"text": "🔔 Авто вкл"}, {"text": "🔕 Авто выкл"}]],
    "resize_keyboard": True, "one_time_keyboard": True})
HELP = ("Кнопки внизу:\n"
        "🔥 Горячее - срочные новости и сюжеты, о которых пишут 3+ издания\n"
        "🆕 Свежее - последнее со всех источников\n"
        "Reuters, AP, BBC, Al Jazeera, France 24, DW, Yonhap, AA - лента одного издания\n"
        "🔔 Авто вкл / 🔕 Авто выкл - присылать горячее самому")
BREAK = re.compile(r"\b(breaking|urgent|just in|developing)\b|срочно|молния", re.I)
STOP = set("with from that this have will been were their about after over into says said "
           "more than amid also what when where which while would could should they them "
           "your news live updates update video watch report reports".split())

cache = {}
s = {}
saved = ""


def load():
    try:
        d = json.load(open(F, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("offset", 0)
    d.setdefault("sent", [])
    d.setdefault("auto", True)
    d.setdefault("init", False)
    return d


def save():
    global saved
    d = json.dumps(s, ensure_ascii=False, sort_keys=True)
    if d != saved:
        open(F, "w", encoding="utf-8").write(d)
        saved = d


def tg(method, **data):
    try:
        return requests.post(f"{API}/{method}", data=data, timeout=20).json()
    except Exception:
        return {}


def say(text, markup=None, kb=False):
    d = {"chat_id": CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if markup or kb:
        d["reply_markup"] = markup or KB
    return bool(tg("sendMessage", **d).get("ok"))


def ago(ts):
    sec = max(0, int(time.time() - ts))
    if sec >= 86400:
        return f"{sec // 86400} д"
    if sec >= 3600:
        return f"{sec // 3600} ч"
    if sec >= 60:
        return f"{sec // 60} мин"
    return "только что"


def pdate(t):
    if not t or not t.strip():
        return None
    t = t.strip()
    try:
        d = email.utils.parsedate_to_datetime(t)
    except Exception:
        try:
            d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def ln(tag):
    return tag.split("}")[-1].lower() if isinstance(tag, str) else ""


def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(t)))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:230].rsplit(" ", 1)[0] + "…" if len(t) > 230 else t


def parse_feed(b, key, google):
    root = ET.fromstring(b)
    out = []
    for el in root.iter():
        if ln(el.tag) not in ("item", "entry"):
            continue
        title = link = None
        ts = None
        desc = ""
        for c in el:
            n = ln(c.tag)
            if n in ("description", "summary", "encoded", "content") and not desc:
                desc = clean(c.text or "")
            elif n == "title":
                title = html.unescape((c.text or "").strip())
            elif n == "link" and not link:
                link = (c.text or "").strip() or c.get("href")
            elif n in ("pubdate", "published", "updated", "date") and ts is None:
                ts = pdate(c.text)
        if not title or not link:
            continue
        if google:
            title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
            desc = ""
        if desc and (len(desc) < 40 or desc.lower().startswith(title.lower()[:40])):
            desc = ""
        out.append({"src": key, "title": title, "link": link, "ts": ts or time.time(), "desc": desc,
                    "id": hashlib.sha1((link or title).encode()).hexdigest()[:12]})
    return out


def fetch(key):
    for url in SRC[key][1]:
        try:
            r = requests.get(url, headers=UA, timeout=15)
            if r.status_code != 200:
                continue
            items = parse_feed(r.content, key, "news.google.com" in url)
            if items:
                return key, items
        except Exception:
            continue
    return key, []


def collect(force=False):
    now = time.time()
    need = [k for k in SRC if force or k not in cache or now - cache[k][0] > 25]
    if need:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for k, items in ex.map(fetch, need):
                if items or k not in cache:
                    cache[k] = (now, items)
    out = []
    for k in SRC:
        out += cache.get(k, (0, []))[1]
    return out


def toks(t):
    return {w for w in re.findall(r"[A-Za-zА-Яа-я0-9]{4,}", t.lower()) if w not in STOP}


def same(a, b):
    sh = len(a & b)
    return sh >= 3 and sh / max(1, min(len(a), len(b))) >= 0.4


def ent(items):
    items = sorted(items, key=lambda x: -x["ts"])
    srcs = []
    for i in items:
        if SRC[i["src"]][0] not in srcs:
            srcs.append(SRC[i["src"]][0])
    r = items[0]
    d = next((i["desc"] for i in items if i.get("desc")), "")
    return {"title": r["title"], "link": r["link"], "ts": r["ts"], "srcs": srcs, "desc": d,
            "ids": [i["id"] for i in items]}


def hot_entries(items):
    now = time.time()
    rec = [i for i in items if now - i["ts"] < 86400]
    rec.sort(key=lambda x: -x["ts"])
    tk = [toks(i["title"]) for i in rec]
    cl = []
    for n, i in enumerate(rec):
        for c in cl:
            if any(same(tk[n], tk[m]) for m in c):
                c.append(n)
                break
        else:
            cl.append([n])
    out = []
    for c in cl:
        its = [rec[m] for m in c]
        e = ent(its)
        if len(e["srcs"]) >= HOT_N or any(BREAK.search(i["title"]) for i in its):
            out.append(e)
    out.sort(key=lambda e: -e["ts"])
    return out


def entries_for(key, force=False):
    items = collect(force)
    if key == "hot":
        return hot_entries(items)
    if key == "all":
        its = [i for i in items if time.time() - i["ts"] < 86400]
    else:
        its = [i for i in items if i["src"] == key]
    its.sort(key=lambda x: -x["ts"])
    return [ent([i]) for i in its[:60]]


def line(e, key, n):
    t = html.escape(e["title"][:170])
    u = html.escape(e["link"], quote=True)
    if len(e["srcs"]) >= HOT_N:
        meta = "🔥 " + ", ".join(e["srcs"][:5])
    elif key in ("hot", "all"):
        meta = ", ".join(e["srcs"][:4])
    else:
        meta = ""
    meta = f"🕐 {ago(e['ts'])}" + (" · " + html.escape(meta) if meta else "")
    d = ("\n<i>" + html.escape(e["desc"]) + "</i>") if e.get("desc") else ""
    return f'{n}. <a href="{u}"><b>{t}</b></a>{d}\n{meta}'


def render(key, page, force=False):
    es = entries_for(key, force)
    n = max(1, (len(es) + PS - 1) // PS)
    page = min(max(page, 0), n - 1)
    chunk = es[page * PS:(page + 1) * PS]
    head = f"<b>{html.escape(NAMES[key])}</b> · {page + 1}/{n}"
    body = [line(e, key, page * PS + k + 1) for k, e in enumerate(chunk)] or ["Пока ничего нет."]
    row = []
    if page > 0:
        row.append({"text": "◀", "callback_data": f"p:{key}:{page - 1}"})
    row.append({"text": "🔄", "callback_data": f"r:{key}:{page}"})
    if page < n - 1:
        row.append({"text": "▶", "callback_data": f"p:{key}:{page + 1}"})
    return head + "\n\n" + "\n\n".join(body), json.dumps({"inline_keyboard": [row]})


def auto_scan():
    if s["init"] and not s["auto"]:
        return
    items = collect(True)
    sent = set(s["sent"])
    hot = [e for e in hot_entries(items) if not any(i in sent for i in e["ids"])]
    if not s["init"]:
        s["sent"] = [i for e in hot for i in e["ids"]][-3000:]
        s["init"] = True
        say("✅ Бот запущен. Нажимай кнопки внизу. Горячее буду присылать сам, пока включено 🔔 Авто.", kb=True)
        return
    now = time.time()
    fresh = sorted([e for e in hot if now - e["ts"] < 3 * 3600], key=lambda e: e["ts"])[-PUSH_MAX:]
    for e in fresh:
        t = html.escape(e["title"][:200])
        u = html.escape(e["link"], quote=True)
        head = "🔥 " + (", ".join(e["srcs"][:5]) if len(e["srcs"]) > 1 else e["srcs"][0])
        d = ("\n<i>" + html.escape(e["desc"]) + "</i>") if e.get("desc") else ""
        say(f'{head}\n<a href="{u}"><b>{t}</b></a>{d}\n🕐 {ago(e["ts"])}')
    s["sent"] = (s["sent"] + [i for e in hot for i in e["ids"]])[-3000:]


def on_message(m):
    t = (m.get("text") or "").strip()
    low = t.lower()
    if low in ("/start", "start", "/help", "help", "помощь"):
        say("Привет! " + HELP, kb=True)
    elif low in ("🔔 авто вкл", "авто вкл"):
        s["auto"] = True
        say("🔔 Горячее буду присылать сам", kb=True)
    elif low in ("🔕 авто выкл", "авто выкл"):
        s["auto"] = False
        say("🔕 Автоматическая отправка выключена, новости только по кнопкам", kb=True)
    elif t in LABELS:
        text, markup = render(LABELS[t], 0)
        say(text, markup)
    elif t:
        say(HELP, kb=True)


def on_callback(cq):
    data = cq.get("data", "")
    msg = cq.get("message") or {}
    try:
        kind, key, page = data.split(":")
        text, markup = render(key, int(page), force=(kind == "r"))
        tg("editMessageText", chat_id=CHAT, message_id=msg.get("message_id"), text=text,
           parse_mode="HTML", disable_web_page_preview="true", reply_markup=markup)
    except Exception:
        pass
    tg("answerCallbackQuery_id", callback_query_id=cq["id"])


def handle(u):
    s["offset"] = u["update_id"] + 1
    if "callback_query" in u:
        cq = u["callback_query"]
        if str(((cq.get("message") or {}).get("chat") or {}).get("id")) == CHAT:
            on_callback(cq)
    elif "message" in u:
        m = u["message"]
        if str((m.get("chat") or {}).get("id")) == CHAT:
            on_message(m)


def run():
    global s
    s = load()
    end = time.time() + RUN_SECONDS
    last = 0
    while True:
        left = end - time.time()
        if left <= 0:
            break
        wait = int(min(15, max(1, left)))
        ups = []
        try:
            r = requests.get(f"{API}/getUpdates",
                             params={"offset": s["offset"], "timeout": wait,
                                     "allowed_updates": json.dumps(["message", "callback_query"])},
                             timeout=wait + 15).json()
            ups = r.get("result", [])
            if not r.get("ok"):
                print("getUpdates:", r)
                time.sleep(3)
        except Exception as e:
            print("getUpdates error:", repr(e))
            time.sleep(3)
        try:
            for u in ups:
                handle(u)
            if time.time() - last >= SCAN_EVERY:
                last = time.time()
                auto_scan()
            if ups:
                save()
        except Exception as e:
            print("error:", repr(e))
            time.sleep(3)
    save()


def stop(*a):
    if s:
        save()
    os._exit(0)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    run()


if __name__ == "__main__":
    main()


import os
import time
import html
import requests
import feedparser

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = "7365523999"

FEEDS = {
    "Anadolu RU": "https://www.aa.com.tr/ru/rss/default?cat=guncel",
    "Reuters EN": "https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "Al Jazeera EN": "https://www.aljazeera.com/xml/rss/all.xml",
    "Yonhap EN": "https://en.yna.co.kr/RSS/news.xml",
}

DB_FILE = "sent_urls.txt"
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"


def send(text):
    try:
        response = session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        data = response.json()

        if data.get("ok"):
            return True

        print("Telegram error:", data.get("description", data))
    except Exception as error:
        print("Telegram error:", error)

    return False


def main():
    if not send("✅ Новости-бот запущен"):
        print("Не удалось отправить тестовое сообщение.")
        return

    sent = set()
    if os.path.exists(DB_FILE):
        with open(DB_FILE, encoding="utf-8") as file:
            sent = set(file.read().splitlines())

    for source, url in FEEDS.items():
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            feed = feedparser.parse(response.content)

            if not feed.entries:
                print(f"{source}: RSS пуст или недоступен")
                continue

            count = 0
            for item in feed.entries:
                link = item.get("link", "").strip()
                title = item.get("title", "").strip()

                if not link or not title or link in sent:
                    continue

                message = (
                    f"📰 <b>{html.escape(source)}</b>\n\n"
                    f"{html.escape(title)}\n\n"
                    f"🔗 {html.escape(link, quote=True)}"
                )

                if send(message):
                    with open(DB_FILE, "a", encoding="utf-8") as file:
                        file.write(link + "\n")
                    sent.add(link)
                    count += 1
                    time.sleep(1)

                if count >= 3:
                    break

            print(f"{source}: отправлено {count}")

        except Exception as error:
            print(f"{source}: ошибка — {error}")


if __name__ == "__main__":
    main()

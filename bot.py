import os
import time
import requests
import xml.etree.ElementTree as ET

# Сюда вшиты самые быстрые RSS-ленты агентств
FEEDS = {
    "Anadolu (RU)": "https://aa.com.tr",
    "Reuters (EN)": "https://reutersagency.com",
    "Al Jazeera (EN)": "https://aljazeera.com",
    "Yonhap (EN)": "https://yna.co.kr"
}

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DB_FILE = "sent_urls.txt"

def get_sent_urls():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()

def save_sent_url(url):
    with open(DB_FILE, "a") as f:
        f.write(url + "\n")

def send_telegram(text):
    url = f"https://telegram.org{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def check_feeds():
    sent_urls = get_sent_urls()
    headers = {"User-Agent": "Mozilla/5.0"}
    
    for source, feed_url in FEEDS.items():
        try:
            response = requests.get(feed_url, headers=headers, timeout=15)
            if response.status_code != 200:
                continue
            
            root = ET.fromstring(response.content)
            for item in root.findall(".//item")[:3]: # Проверяем последние 3 новости
                title = item.find("title").text
                link = item.find("link").text.strip()
                
                if link not in sent_urls:
                    message = f"🚨 <b>{source} BREAKING:</b>\n\n{title}\n\n🔗 {link}"
                    send_telegram(message)
                    save_sent_url(link)
                    time.sleep(1)
        except Exception as e:
            print(f"Ошибка парсинга {source}: {e}")

if __name__ == "__main__":
    check_feeds()

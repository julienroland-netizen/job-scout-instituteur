import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path



TELEGRAM_TOKEN = "8972333573:AAHQkjNoVe_uAbciQ7aL_Mm2TXiVWv6TrJ0"
CHAT_ID = "7554156182"

SEEN_FILE = Path("seen_jobs.json")

URLS = [
    "https://www.jobecole.be/offres-emploi",
    "https://www.enseignons.be/jobs/",
]

KEYWORDS_JOB = [
    "instituteur primaire",
    "institutrice primaire",
    "maître primaire",
    "maitresse primaire",
]

KEYWORDS_FULLTIME = [
    "temps plein",
    "24/24",
    "full time",
    "plein temps",
]

KEYWORDS_LOCATION = [
    "bruxelles",
    "wallonie",
    "namur",
    "liège",
    "liege",
    "charleroi",
    "mons",
    "nivelles",
    "wavre",
    "ottignies",
    "louvain-la-neuve",
    "tournai",
    "verviers",
    "arlon",
    "luxembourg",
]


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen), indent=2))


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    print(response.text)


def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 JobScoutBot/1.0"
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def extract_possible_jobs(url):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    jobs = []

    for element in soup.find_all(["article", "div", "li", "a", "h2", "h3", "p"]):
        text = " ".join(element.get_text(" ", strip=True).split())

        if len(text) < 20:
            continue

        lower = text.lower()

        if any(keyword in lower for keyword in KEYWORDS_JOB):
            link = None

            if element.name == "a" and element.get("href"):
                link = element.get("href")
            else:
                a = element.find("a")
                if a and a.get("href"):
                    link = a.get("href")

            if link:
                if link.startswith("/"):
                    base = "/".join(url.split("/")[:3])
                    link = base + link
            else:
                link = url

            jobs.append({
                "title": text[:300],
                "url": link,
                "source": url,
            })

    return jobs


def is_match(job):
    text = job["title"].lower()

    has_job = any(keyword in text for keyword in KEYWORDS_JOB)

    # On garde volontairement le filtre temps plein souple au début,
    # car certains sites affichent le temps de travail uniquement sur la page détail.
    has_fulltime = any(keyword in text for keyword in KEYWORDS_FULLTIME)
    has_location = any(keyword in text for keyword in KEYWORDS_LOCATION)

    return has_job and (has_fulltime or has_location or True)


def main():
    seen = load_seen()
    new_matches = []

    for url in URLS:
        print(f"Analyse de {url}")

        try:
            jobs = extract_possible_jobs(url)

            for job in jobs:
                job_id = job["url"] + "|" + job["title"]

                if job_id not in seen and is_match(job):
                    new_matches.append(job)
                    seen.add(job_id)

        except Exception as e:
            print(f"Erreur sur {url}: {e}")

    if new_matches:
        for job in new_matches[:10]:
            message = (
                "Nouvelle offre possible 👇\n\n"
                f"{job['title']}\n\n"
                f"{job['url']}"
            )
            send_telegram(message)
    else:
        print("Aucune nouvelle offre.")

    save_seen(seen)


if __name__ == "__main__":
    main()
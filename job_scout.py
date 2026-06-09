import json
import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
ORS_API_KEY = os.environ["ORS_API_KEY"]

SEEN_FILE = Path("seen_jobs.json")

JODOIGNE_COORDS = [4.8697, 50.7236]  # lon, lat
MAX_DRIVE_MINUTES = 60

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
    headers = {"User-Agent": "Mozilla/5.0 JobScoutBot/1.0"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def geocode_location(text):
    url = "https://api.openrouteservice.org/geocode/search"

    params = {
        "api_key": ORS_API_KEY,
        "text": text,
        "boundary.country": "BE",
        "size": 1,
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()

    data = response.json()

    if not data.get("features"):
        return None

    return data["features"][0]["geometry"]["coordinates"]


def driving_minutes_from_jodoigne(destination_coords):
    url = "https://api.openrouteservice.org/v2/directions/driving-car"

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "coordinates": [
            JODOIGNE_COORDS,
            destination_coords,
        ]
    }

    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()

    data = response.json()
    seconds = data["routes"][0]["summary"]["duration"]

    return round(seconds / 60)


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

            if link and link.startswith("/"):
                base = "/".join(url.split("/")[:3])
                link = base + link

            jobs.append({
                "title": text[:300],
                "url": link or url,
                "source": url,
            })

    return jobs


def is_match(job):
    text = job["title"].lower()

    has_job = any(keyword in text for keyword in KEYWORDS_JOB)

    if not has_job:
        return False, None, "Pas instituteur primaire"

    try:
        coords = geocode_location(job["title"])

        if coords is None:
            return True, None, "Lieu non détecté — à vérifier"

        minutes = driving_minutes_from_jodoigne(coords)

        if minutes <= MAX_DRIVE_MINUTES:
            return True, minutes, f"{minutes} min depuis Jodoigne"

        return False, minutes, f"Trop loin : {minutes} min"

    except Exception as e:
        return True, None, f"Distance non calculée — à vérifier"


def main():
    seen = load_seen()
    new_matches = []

    for url in URLS:
        print(f"Analyse de {url}")

        try:
            jobs = extract_possible_jobs(url)

            for job in jobs:
                job_id = job["url"] + "|" + job["title"]

                match, drive_minutes, reason = is_match(job)

                if job_id not in seen and match:
                    job["drive_minutes"] = drive_minutes
                    job["reason"] = reason
                    new_matches.append(job)
                    seen.add(job_id)

        except Exception as e:
            print(f"Erreur sur {url}: {e}")

    if new_matches:
        for job in new_matches[:10]:
            message = (
                "Nouvelle offre possible 👇\n\n"
                f"{job['title']}\n\n"
                f"Trajet : {job.get('reason', 'Non calculé')}\n\n"
                f"{job['url']}"
            )
            send_telegram(message)
    else:
        print("Aucune nouvelle offre.")

    save_seen(seen)


if __name__ == "__main__":
    main()
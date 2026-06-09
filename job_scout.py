import json
import os
import re
import html
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
ORS_API_KEY = os.environ["ORS_API_KEY"]

SEEN_FILE = Path("seen_jobs.json")
DOCS_DIR = Path("docs")
JOBS_JSON = DOCS_DIR / "jobs.json"
INDEX_HTML = DOCS_DIR / "index.html"

JODOIGNE_COORDS = [4.8697, 50.7236]

KEYWORDS_JOB = [
    "instituteur primaire",
    "institutrice primaire",
    "maître primaire",
    "maitre primaire",
    "maitresse primaire",
    "enseignant primaire",
    "enseignante primaire",
    "enseignement primaire",
]

KEYWORDS_FULLTIME = [
    "temps plein",
    "plein temps",
    "24/24",
    "full time",
    "38h",
]

BAD_LOCATION_WORDS = [
    "fermer",
    "ouvrir",
    "menu",
    "connexion",
    "postuler",
    "rechercher",
    "voir",
    "suivant",
    "précédent",
]


def clean_text(text):
    return " ".join(text.replace("\n", " ").replace("\t", " ").split())


def fetch_html(url):
    headers = {"User-Agent": "Mozilla/5.0 JobScoutBot/1.0"}
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    return response.text


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen), indent=2))


def save_public_jobs(jobs):
    DOCS_DIR.mkdir(exist_ok=True)
    JOBS_JSON.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))


def generate_site(jobs):
    DOCS_DIR.mkdir(exist_ok=True)

    rows = ""

    if jobs:
        for job in jobs:
            title = html.escape(job.get("title", ""))
            url = html.escape(job.get("url", ""))
            location = html.escape(job.get("location", "Non détecté"))
            drive_time = html.escape(job.get("drive_time", "À vérifier"))
            time_status = html.escape(job.get("time_status", "Non confirmé"))
            contract_duration = html.escape(job.get("contract_duration", "Durée non détectée"))
            source = html.escape(job.get("source", ""))
            found_at = html.escape(job.get("found_at", ""))

            rows += f"""
            <tr>
                <td><a href="{url}" target="_blank">{title}</a></td>
                <td>{location}</td>
                <td>{drive_time}</td>
                <td>{time_status}</td>
                <td>{contract_duration}</td>
                <td>{source}</td>
                <td>{found_at}</td>
            </tr>
            """
    else:
        rows = """
        <tr>
            <td colspan="7">Aucune offre détectée pour le moment.</td>
        </tr>
        """

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    html_content = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Job Scout Instituteur</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 40px;
            background: #f6f7f9;
            color: #222;
        }}
        h1 {{
            margin-bottom: 5px;
        }}
        .subtitle {{
            color: #555;
            margin-bottom: 20px;
        }}
        .meta {{
            color: #777;
            font-size: 14px;
            margin-bottom: 25px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
        }}
        th, td {{
            padding: 12px;
            border-bottom: 1px solid #ddd;
            vertical-align: top;
        }}
        th {{
            background: #222;
            color: white;
            text-align: left;
        }}
        a {{
            color: #0057b8;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <h1>Job Scout Instituteur</h1>
    <div class="subtitle">Toutes les offres détectées. Telegram notifie uniquement les nouvelles.</div>
    <div class="meta">Dernière mise à jour : {generated_at}</div>

    <table>
        <thead>
            <tr>
                <th>Offre</th>
                <th>Lieu</th>
                <th>Trajet depuis Jodoigne</th>
                <th>Temps</th>
                <th>Durée contrat</th>
                <th>Source</th>
                <th>Détectée le</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
</body>
</html>
"""

    INDEX_HTML.write_text(html_content, encoding="utf-8")


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


def extract_jobs_from_listing(list_url, source_name):
    html_page = fetch_html(list_url)
    soup = BeautifulSoup(html_page, "html.parser")

    jobs = {}

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        href = urljoin(list_url, a["href"])

        if len(text) < 5:
            continue

        parent_text = clean_text(a.parent.get_text(" ", strip=True)) if a.parent else text
        combined = f"{text} {parent_text}".lower()

        if any(keyword in combined for keyword in KEYWORDS_JOB):
            title = text if len(text) >= 5 else parent_text

            jobs[href] = {
                "title": title[:250],
                "url": href,
                "source": source_name,
            }

    return list(jobs.values())


def scrape_jobecole():
    urls = [
        "https://www.jobecole.be/offres-emploi",
        "https://www.jobecole.be/offres-emploi?start=15",
        "https://www.jobecole.be/offres-emploi?start=30",
        "https://www.jobecole.be/offres-emploi?start=45",
        "https://www.jobecole.be/offres-emploi/fondamental/2-instituteur-primaire/toutes-regions",
        "https://www.jobecole.be/offres-emploi/fondamental/2-instituteur-primaire/toutes-regions?start=15",
        "https://www.jobecole.be/offres-emploi/fondamental/2-instituteur-primaire/toutes-regions?start=30",
        "https://www.jobecole.be/offres-emploi/fondamental/2-instituteur-primaire/1-bruxelles-capitale",
        "https://www.jobecole.be/offres-emploi/fondamental/2-instituteur-primaire/2-brabant-wallon",
        "https://www.jobecole.be/offres-emploi/tous-niveaux-enseignement/4-namur",
        "https://www.jobecole.be/offres-emploi/tous-niveaux-enseignement/5-liege",
    ]

    jobs = []

    for url in urls:
        try:
            print(f"Analyse JobEcole : {url}")
            jobs.extend(extract_jobs_from_listing(url, "JobEcole"))
        except Exception as e:
            print(f"Erreur JobEcole sur {url}: {e}")

    return jobs


def scrape_enseignons():
    urls = [
        "https://www.enseignons.be/jobs/",
    ]

    jobs = []

    for url in urls:
        try:
            print(f"Analyse Enseignons : {url}")
            jobs.extend(extract_jobs_from_listing(url, "Enseignons.be"))
        except Exception as e:
            print(f"Erreur Enseignons sur {url}: {e}")

    return jobs


def scrape_actiris():
    urls = [
        "https://www.actiris.brussels/fr/citoyens/emplois/enseignant-dans-l-enseignement-fondamental-T%276",
        "https://www.actiris.brussels/fr/citoyens/emplois/enseignement-scolaire-T%276",
    ]

    jobs = []

    for url in urls:
        try:
            print(f"Analyse Actiris : {url}")
            jobs.extend(extract_jobs_from_listing(url, "Actiris"))
        except Exception as e:
            print(f"Erreur Actiris sur {url}: {e}")

    return jobs


def scrape_wbe():
    urls = [
        "https://www.wbe.be/jepostule/",
        "https://www.wbe.be/jepostule/remplacement/",
    ]

    jobs = []

    for url in urls:
        try:
            print(f"Analyse WBE : {url}")
            jobs.extend(extract_jobs_from_listing(url, "WBE"))
        except Exception as e:
            print(f"Erreur WBE sur {url}: {e}")

    return jobs


SCRAPERS = [
    scrape_jobecole,
    scrape_enseignons,
    scrape_actiris,
    scrape_wbe,
]


def fetch_job_detail(job):
    try:
        html_page = fetch_html(job["url"])
        soup = BeautifulSoup(html_page, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        detail_text = clean_text(soup.get_text(" ", strip=True))
        job["detail_text"] = detail_text[:5000]
        return job

    except Exception as e:
        job["detail_text"] = job["title"]
        job["detail_error"] = str(e)
        return job
        
def detect_fulltime(text):
    lower = text.lower()
    if any(keyword in lower for keyword in KEYWORDS_FULLTIME):
        return "Temps plein probable"
    return "Temps non confirmé"

def extract_contract_duration(text):
    patterns = [
        r"du\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+au\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"du\s+\d{1,2}\s+[a-zéû]+\s+\d{4}\s+au\s+\d{1,2}\s+[a-zéû]+\s+\d{4}",
        r"jusqu['’]au\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"jusqu['’]au\s+\d{1,2}\s+[a-zéû]+\s+\d{4}",
        r"du\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"à partir du\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"année scolaire\s+\d{4}[-/]\d{4}",
        r"année\s+scolaire\s+\d{4}\s*-\s*\d{4}",
        r"contrat\s*[:\-]\s*([^\.|,;\n]{3,120})",
        r"durée\s*[:\-]\s*([^\.|,;\n]{3,120})",
        r"date de début\s*[:\-]\s*([^\.|,;\n]{3,120})",
        r"date de fin\s*[:\-]\s*([^\.|,;\n]{3,120})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))

    return "Durée non détectée"


def extract_location_candidate(text):
    title_location = re.search(
        r"(?:instituteur primaire|institutrice primaire|enseignant primaire|enseignante primaire)\s+à\s+([A-Za-zÀ-ÿ'’\-]+(?:\s+[A-Za-zÀ-ÿ'’\-]+){0,2})",
        text,
        flags=re.IGNORECASE,
    )

    if title_location:
        candidate = clean_text(title_location.group(1))

        stop_words = [
            "Offres",
            "offres",
            "Source",
            "Temps",
            "Durée",
            "Trajet",
            "Contrat",
        ]

        for stop in stop_words:
            if stop in candidate:
                candidate = candidate.split(stop)[0].strip()

        if candidate and candidate.lower() not in BAD_LOCATION_WORDS:
            return candidate + ", Belgique"

    postcode_match = re.search(
        r"\b([1-9][0-9]{3})\s+([A-Za-zÀ-ÿ'’\-\s]{3,40})",
        text,
    )

    if postcode_match:
        candidate = clean_text(postcode_match.group(2))

        if candidate.lower() in BAD_LOCATION_WORDS:
            return None

        return clean_text(postcode_match.group(0)) + ", Belgique"

    patterns = [
        r"(?:lieu|localité|localite|commune|adresse|implantation)\s*[:\-]\s*([^\.|,;\n]{3,80})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = clean_text(match.group(1))

            if candidate.lower() in BAD_LOCATION_WORDS:
                continue

            if len(candidate) >= 3:
                return candidate + ", Belgique"

    return None


def geocode_location(location_text):
    url = "https://api.openrouteservice.org/geocode/search"

    params = {
        "api_key": ORS_API_KEY,
        "text": location_text,
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

    response = requests.post(url, headers=headers, json=payload, timeout=25)
    response.raise_for_status()

    data = response.json()
    seconds = data["routes"][0]["summary"]["duration"]

    return round(seconds / 60)


def analyze_job(job):
    full_text = f"{job.get('title', '')} {job.get('detail_text', '')}"
    lower = full_text.lower()

    has_job = any(keyword in lower for keyword in KEYWORDS_JOB)

    if not has_job:
        return False, {
            "reason": "Pas instituteur primaire",
            "location": None,
            "minutes": None,
            "time_status": None,
            "contract_duration": "Durée non détectée",
        }

    time_status = detect_fulltime(full_text)
    contract_duration = extract_contract_duration(full_text)
    location = extract_location_candidate(full_text)

    if not location:
        return True, {
            "reason": "Lieu non détecté — à vérifier manuellement",
            "location": None,
            "minutes": None,
            "time_status": time_status,
            "contract_duration": contract_duration,
        }

    try:
        coords = geocode_location(location)

        if coords is None:
            return True, {
                "reason": "Lieu trouvé mais non géocodé — à vérifier",
                "location": location,
                "minutes": None,
                "time_status": time_status,
                "contract_duration": contract_duration,
            }

        minutes = driving_minutes_from_jodoigne(coords)

        return True, {
            "reason": f"{minutes} min depuis Jodoigne",
            "location": location,
            "minutes": minutes,
            "time_status": time_status,
            "contract_duration": contract_duration,
        }

    except Exception:
        return True, {
            "reason": "Distance non calculée — à vérifier",
            "location": location,
            "minutes": None,
            "time_status": time_status,
            "contract_duration": contract_duration,
        }


def build_site_job(job, analysis):
    return {
        "title": job["title"],
        "url": job["url"],
        "source": job["source"],
        "location": analysis.get("location") or "Non détecté",
        "drive_time": analysis.get("reason") or "À vérifier",
        "time_status": analysis.get("time_status") or "Non confirmé",
        "contract_duration": analysis.get("contract_duration") or "Durée non détectée",
        "found_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def deduplicate_jobs(jobs):
    unique = {}

    for job in jobs:
        key = job["url"]
        unique[key] = job

    return list(unique.values())


def main():
    seen = load_seen()
    new_matches = []
    all_matches = []

    all_jobs = []

    for scraper in SCRAPERS:
        try:
            all_jobs.extend(scraper())
        except Exception as e:
            print(f"Erreur scraper {scraper.__name__}: {e}")

    all_jobs = deduplicate_jobs(all_jobs)

    print(f"{len(all_jobs)} offre(s) candidate(s) trouvée(s).")

    for job in all_jobs:
        job = fetch_job_detail(job)
        job_id = job["url"]

        match, analysis = analyze_job(job)

        if match:
            site_job = build_site_job(job, analysis)
            all_matches.append(site_job)

            if job_id not in seen:
                job["analysis"] = analysis
                new_matches.append(job)
                seen.add(job_id)

    if new_matches:
        for job in new_matches:
            analysis = job["analysis"]

            message = (
                "Nouvelle offre possible 👇\n\n"
                f"{job['title']}\n\n"
                f"Source : {job['source']}\n"
                f"Temps : {analysis.get('time_status')}\n"
                f"Durée : {analysis.get('contract_duration')}\n"
                f"Lieu : {analysis.get('location') or 'Non détecté'}\n"
                f"Trajet : {analysis.get('reason')}\n\n"
                f"{job['url']}"
            )

            send_telegram(message)
    else:
        print("Aucune nouvelle offre.")

    all_matches = all_matches[:150]

    save_public_jobs(all_matches)
    generate_site(all_matches)
    save_seen(seen)


if __name__ == "__main__":
    main()
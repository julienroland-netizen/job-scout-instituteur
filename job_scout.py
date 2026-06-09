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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

CONFIG_FILE = Path("config.json")
SEEN_FILE = Path("seen_jobs.json")
AI_CACHE_FILE = Path("ai_cache.json")
DOCS_DIR = Path("docs")
JOBS_JSON = DOCS_DIR / "jobs.json"
INDEX_HTML = DOCS_DIR / "index.html"


def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

JODOIGNE_COORDS = CONFIG["jodoigne_coords"]
MAX_JOBS_ON_SITE = CONFIG.get("max_jobs_on_site", 150)
GEMINI_MODEL = CONFIG.get("gemini_model", "gemini-3.5-flash")
KEYWORDS_JOB = CONFIG["keywords_job"]
KEYWORDS_FULLTIME = CONFIG["keywords_fulltime"]
BAD_LOCATION_WORDS = CONFIG["bad_location_words"]
SOURCES = CONFIG["sources"]


def clean_text(text):
    return " ".join(str(text).replace("\n", " ").replace("\t", " ").split())


def fetch_html(url):
    headers = {"User-Agent": "Mozilla/5.0 JobScoutBot/1.0"}
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    return response.text


def load_json_file(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json_file(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_seen():
    return set(load_json_file(SEEN_FILE, []))


def save_seen(seen):
    save_json_file(SEEN_FILE, sorted(list(seen)))


def load_ai_cache():
    return load_json_file(AI_CACHE_FILE, {})


def save_ai_cache(cache):
    save_json_file(AI_CACHE_FILE, cache)


def save_public_jobs(jobs):
    DOCS_DIR.mkdir(exist_ok=True)
    save_json_file(JOBS_JSON, jobs)


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
            contract_type = html.escape(job.get("contract_type", "Type non détecté"))
            ai_confidence = html.escape(str(job.get("ai_confidence", "")))
            source = html.escape(job.get("source", ""))
            found_at = html.escape(job.get("found_at", ""))

            rows += f"""
            <tr>
                <td><a href="{url}" target="_blank">{title}</a></td>
                <td>{location}</td>
                <td>{drive_time}</td>
                <td>{time_status}</td>
                <td>{contract_duration}</td>
                <td>{contract_type}</td>
                <td>{ai_confidence}</td>
                <td>{source}</td>
                <td>{found_at}</td>
            </tr>
            """
    else:
        rows = """
        <tr>
            <td colspan="9">Aucune offre détectée pour le moment.</td>
        </tr>
        """

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    html_content = f"""<!DOCTYPE html>
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
        h1 {{ margin-bottom: 5px; }}
        .subtitle {{ color: #555; margin-bottom: 20px; }}
        .meta {{ color: #777; font-size: 14px; margin-bottom: 25px; }}
        table {{ width: 100%; border-collapse: collapse; background: white; }}
        th, td {{ padding: 12px; border-bottom: 1px solid #ddd; vertical-align: top; }}
        th {{ background: #222; color: white; text-align: left; }}
        a {{ color: #0057b8; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Job Scout Instituteur</h1>
    <div class="subtitle">Toutes les offres détectées. Telegram notifie uniquement les nouvelles. Gemini complète les durées non détectées.</div>
    <div class="meta">Dernière mise à jour : {generated_at}</div>

    <table>
        <thead>
            <tr>
                <th>Offre</th>
                <th>Lieu</th>
                <th>Trajet depuis Jodoigne</th>
                <th>Temps</th>
                <th>Durée contrat</th>
                <th>Type contrat</th>
                <th>Confiance IA</th>
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


def scrape_sources():
    jobs = []

    for source_name, urls in SOURCES.items():
        for url in urls:
            try:
                print(f"Analyse {source_name} : {url}")
                jobs.extend(extract_jobs_from_listing(url, source_name))
            except Exception as e:
                print(f"Erreur {source_name} sur {url}: {e}")

    return jobs


def fetch_job_detail(job):
    try:
        html_page = fetch_html(job["url"])
        soup = BeautifulSoup(html_page, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        detail_text = clean_text(soup.get_text(" ", strip=True))
        job["detail_text"] = detail_text[:9000]
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


def extract_contract_duration_regex(text):
    patterns = [
        r"du\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+au\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"du\s+\d{1,2}\s+[a-zéû]+\s+\d{4}\s+au\s+\d{1,2}\s+[a-zéû]+\s+\d{4}",
        r"jusqu['’]au\s+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        r"jusqu['’]au\s+\d{1,2}\s+[a-zéû]+\s+\d{4}",
        r"année scolaire\s+\d{4}\s*[-/]\s*\d{4}",
        r"contrat\s*[:\-]\s*([^\.|,;\n]{3,160})",
        r"durée\s*[:\-]\s*([^\.|,;\n]{3,160})",
        r"date de début\s*[:\-]?\s*([^\.|,;\n]{3,160})",
        r"date de fin\s*[:\-]?\s*([^\.|,;\n]{3,160})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))[:180]

    return "Durée non détectée"


def safe_json_from_text(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    return json.loads(text)


def analyze_with_gemini(job_text):
    if not GEMINI_API_KEY:
        return {}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

    prompt = f"""
Tu analyses une offre d'emploi d'instituteur primaire en Belgique.

Objectif: extraire uniquement les informations explicitement présentes ou raisonnablement déductibles du texte.
Ne devine pas si l'information n'est pas présente.

Réponds uniquement en JSON valide, sans markdown, avec ces champs:
{{
  "contract_duration": "durée lisible du contrat ou 'Durée non détectée'",
  "start_date": "date de début au format YYYY-MM-DD ou null",
  "end_date": "date de fin au format YYYY-MM-DD ou null",
  "contract_type": "CDD, CDI, remplacement, année scolaire, intérim, ou 'Type non détecté'",
  "time_status": "Temps plein, temps partiel, ou 'Temps non confirmé'",
  "location": "commune/lieu court, sans Belgique, ou null",
  "confidence": 0.0
}}

Texte de l'annonce:
{job_text[:7000]}
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0,
            "maxOutputTokens": 512
        }
    }

    response = requests.post(
        url,
        headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=35,
    )
    response.raise_for_status()

    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]

    return safe_json_from_text(text)


def extract_location_from_title(text):
    patterns = [
        r"(?:instituteur primaire|institutrice primaire|enseignant primaire|enseignante primaire)\s+à\s+([A-Za-zÀ-ÿ'’\-]+(?:\s+[A-Za-zÀ-ÿ'’\-]+){0,2})",
        r"recherche\s+(?:un|une)?\s*(?:instituteur primaire|institutrice primaire|enseignant primaire|enseignante primaire)\s+à\s+([A-Za-zÀ-ÿ'’\-]+(?:\s+[A-Za-zÀ-ÿ'’\-]+){0,2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = clean_text(match.group(1))

            stop_words = [
                "Offres",
                "offres",
                "Source",
                "Temps",
                "Durée",
                "Trajet",
                "Contrat",
                "Pourvu",
            ]

            for stop in stop_words:
                if stop in candidate:
                    candidate = candidate.split(stop)[0].strip()

            candidate = candidate.strip(" -–—()[]")

            if candidate and candidate.lower() not in BAD_LOCATION_WORDS:
                return candidate

    return None


def extract_location_candidate(text):
    title_candidate = extract_location_from_title(text)
    if title_candidate:
        return title_candidate + ", Belgique"

    postcode_match = re.search(
        r"\b([1-9][0-9]{3})\s+([A-Za-zÀ-ÿ'’\-\s]{3,40})",
        text,
    )

    if postcode_match:
        candidate = clean_text(postcode_match.group(2)).strip(" -–—()[]")

        if candidate.lower() in BAD_LOCATION_WORDS:
            return None

        return clean_text(f"{postcode_match.group(1)} {candidate}") + ", Belgique"

    patterns = [
        r"(?:lieu|localité|localite|commune|adresse|implantation)\s*[:\-]\s*([^\.|,;\n]{3,80})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = clean_text(match.group(1)).strip(" -–—()[]")

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


def maybe_use_gemini(job, analysis, ai_cache):
    job_id = job["url"]

    needs_ai = (
        analysis.get("contract_duration") == "Durée non détectée"
        or analysis.get("time_status") == "Temps non confirmé"
        or not analysis.get("location")
    )

    if not needs_ai:
        return analysis

    if job_id in ai_cache:
        ai_result = ai_cache[job_id]
    else:
        try:
            print(f"Analyse Gemini : {job['url']}")
            full_text = f"{job.get('title', '')}\n\n{job.get('detail_text', '')}"
            ai_result = analyze_with_gemini(full_text)
            ai_cache[job_id] = ai_result
        except Exception as e:
            print(f"Erreur Gemini sur {job['url']}: {e}")
            return analysis

    if analysis.get("contract_duration") == "Durée non détectée":
        value = ai_result.get("contract_duration")
        if value and value != "Durée non détectée":
            analysis["contract_duration"] = value

    if analysis.get("time_status") == "Temps non confirmé":
        value = ai_result.get("time_status")
        if value and value != "Temps non confirmé":
            analysis["time_status"] = value

    if not analysis.get("location"):
        value = ai_result.get("location")
        if value:
            analysis["location"] = value

    contract_type = ai_result.get("contract_type")
    if contract_type:
        analysis["contract_type"] = contract_type

    confidence = ai_result.get("confidence")
    if confidence is not None:
        analysis["ai_confidence"] = confidence

    return analysis


def analyze_job(job, ai_cache):
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
            "contract_type": "Type non détecté",
            "ai_confidence": "",
        }

    time_status = detect_fulltime(full_text)
    contract_duration = extract_contract_duration_regex(full_text)
    location = extract_location_candidate(full_text)

    analysis = {
        "reason": "Lieu non détecté — à vérifier manuellement",
        "location": location.replace(", Belgique", "") if location else None,
        "minutes": None,
        "time_status": time_status,
        "contract_duration": contract_duration,
        "contract_type": "Type non détecté",
        "ai_confidence": "",
    }

    analysis = maybe_use_gemini(job, analysis, ai_cache)

    location_for_route = analysis.get("location")
    if location_for_route:
        try:
            coords = geocode_location(f"{location_for_route}, Belgique")
            if coords is not None:
                minutes = driving_minutes_from_jodoigne(coords)
                analysis["minutes"] = minutes
                analysis["reason"] = f"{minutes} min depuis Jodoigne"
            else:
                analysis["reason"] = "Lieu trouvé mais non géocodé — à vérifier"
        except Exception:
            analysis["reason"] = "Distance non calculée — à vérifier"

    return True, analysis


def build_site_job(job, analysis):
    return {
        "title": job["title"],
        "url": job["url"],
        "source": job["source"],
        "location": analysis.get("location") or "Non détecté",
        "drive_time": analysis.get("reason") or "À vérifier",
        "time_status": analysis.get("time_status") or "Non confirmé",
        "contract_duration": analysis.get("contract_duration") or "Durée non détectée",
        "contract_type": analysis.get("contract_type") or "Type non détecté",
        "ai_confidence": analysis.get("ai_confidence") if analysis.get("ai_confidence") != "" else "",
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
    ai_cache = load_ai_cache()
    new_matches = []
    all_matches = []

    all_jobs = scrape_sources()
    all_jobs = deduplicate_jobs(all_jobs)

    print(f"{len(all_jobs)} offre(s) candidate(s) trouvée(s).")

    for job in all_jobs:
        job = fetch_job_detail(job)
        job_id = job["url"]

        match, analysis = analyze_job(job, ai_cache)

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
                f"Type : {analysis.get('contract_type')}\n"
                f"Lieu : {analysis.get('location') or 'Non détecté'}\n"
                f"Trajet : {analysis.get('reason')}\n\n"
                f"{job['url']}"
            )

            send_telegram(message)
    else:
        print("Aucune nouvelle offre.")

    all_matches = all_matches[:MAX_JOBS_ON_SITE]

    save_public_jobs(all_matches)
    generate_site(all_matches)
    save_seen(seen)
    save_ai_cache(ai_cache)


if __name__ == "__main__":
    main()

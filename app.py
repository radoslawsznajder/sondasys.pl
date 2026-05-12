import csv
import random
import time
import threading
from urllib.parse import urljoin, urlparse
from io import StringIO

import requests
from flask import Flask

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ============================================================
# KONFIGURACJA
# ============================================================
TARGET_URL = "https://www.profitablecpmratenetwork.com/abb4uvw82?key=b84cc7aa929d2fb43077400fd1e094b1"
ACTION_DELAY_MS = 1500

# Może być ścieżka lokalna albo URL (tu: raw GitHub)
SIMULATION_CSV = "https://raw.githubusercontent.com/radoslawsznajder/sondasys.pl/refs/heads/main/simulation_profiles.csv"  # kolumny: ip_address,user_agent

REFERER = "https://sondasys.pl/"

HEADLESS = True
PAGE_TIMEOUT_MS = 1000
MAX_LINKS_TO_SAMPLE = 5

# 0 = bez końca, >0 = konkretna liczba iteracji
SCAN_COUNT = 0


def load_simulation_profiles(csv_path: str) -> list[dict]:
    profiles: list[dict] = []

    # Obsługa zarówno lokalnej ścieżki jak i URL
    if csv_path.startswith(("http://", "https://")):
        resp = requests.get(csv_path, timeout=10)
        resp.raise_for_status()
        f = StringIO(resp.text)
    else:
        f = open(csv_path, "r", encoding="utf-8-sig", newline="")

    with f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        required = {"ip_address", "user_agent"}
        missing = required - set(fieldnames)
        if missing:
            raise ValueError(
                f"Brakuje wymaganych kolumn w pliku {csv_path}: {', '.join(sorted(missing))}"
            )

        for row in reader:
            ip_address = (row.get("ip_address") or "").strip()
            user_agent = (row.get("user_agent") or "").strip()

            if ip_address and user_agent:
                profiles.append(
                    {
                        "ip_address": ip_address,
                        "user_agent": user_agent,
                    }
                )

    if not profiles:
        raise ValueError(f"Brak poprawnych rekordów w pliku {csv_path}")

    return profiles


def same_domain(base_url: str, candidate_url: str) -> bool:
    try:
        b = urlparse(base_url).netloc.replace("www.", "")
        c = urlparse(candidate_url).netloc.replace("www.", "")
        return b == c
    except Exception:
        return False


def extract_internal_links(page, base_url: str) -> list[str]:
    hrefs = page.eval_on_selector_all(
        "a[href]",
        """
        elements => elements
            .map(el => el.getAttribute('href'))
            .filter(Boolean)
        """,
    )

    cleaned: list[str] = []
    for href in hrefs:
        href = (href or "").strip()
        if not href:
            continue

        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        absolute = urljoin(base_url, href)

        if absolute.startswith(("http://", "https://")) and same_domain(
            base_url, absolute
        ):
            cleaned.append(absolute)

    deduped = list(dict.fromkeys(cleaned))
    random.shuffle(deduped)
    return deduped[:MAX_LINKS_TO_SAMPLE]


def random_sleep(ms: int):
    jitter = random.randint(150, 600)
    time.sleep((ms + jitter) / 1000)


def human_like_interaction(page):
    try:
        page.mouse.move(
            random.randint(100, 800),
            random.randint(100, 500),
            steps=random.randint(10, 30),
        )
    except Exception:
        pass

    random_sleep(ACTION_DELAY_MS)

    try:
        page.mouse.wheel(0, random.randint(250, 1200))
    except Exception:
        pass

    random_sleep(ACTION_DELAY_MS)


def run_single_scan(playwright, scan_no: int, profile: dict):
    ua = profile["user_agent"]
    xff_ip = profile["ip_address"]

    browser = playwright.chromium.launch(headless=HEADLESS)

    context = browser.new_context(
        user_agent=ua,
        viewport={
            "width": random.choice([1366, 1440, 1536]),
            "height": random.choice([768, 864, 900]),
        },
        locale=random.choice(["pl-PL", "en-US"]),
        color_scheme=random.choice(["light", "dark"]),
        extra_http_headers={
            "X-Forwarded-For": xff_ip,
        },
    )

    page = context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT_MS)

    result = {
        "scan_no": scan_no,
        "target_url": TARGET_URL,
        "landing_url": None,
        "clicked_url": None,
        "final_url": None,
        "user_agent": ua,
        "x_forwarded_for": xff_ip,
        "status": "ok",
        "error": None,
    }

    try:
        page.goto(TARGET_URL, referer=REFERER, wait_until="domcontentloaded")
        result["landing_url"] = page.url

        human_like_interaction(page)

        links = extract_internal_links(page, page.url)

        if not links:
            result["status"] = "no_links_found"
            result["final_url"] = page.url
            return result

        selected = random.choice(links)
        result["clicked_url"] = selected

        # Losowo wybieramy sposób przejścia:
        # 1) bezpośrednie goto
        # 2) próba kliknięcia pasującego linku na stronie
        navigation_mode = random.choice(["goto", "click"])

        if navigation_mode == "click":
            clicked = False
            anchors = page.locator("a[href]")
            count = anchors.count()

            sample_indexes = list(range(count))
            random.shuffle(sample_indexes)

            for idx in sample_indexes[:20]:
                try:
                    anchor = anchors.nth(idx)
                    href = anchor.get_attribute("href") or ""
                    absolute = urljoin(page.url, href)

                    if absolute == selected:
                        anchor.click(timeout=5000)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                page.goto(selected, referer=page.url, wait_until="domcontentloaded")
        else:
            page.goto(selected, referer=page.url, wait_until="domcontentloaded")

        human_like_interaction(page)

        result["final_url"] = page.url
        return result

    except PlaywrightTimeoutError as e:
        result["status"] = "timeout"
        result["error"] = str(e)
        result["final_url"] = page.url
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        try:
            result["final_url"] = page.url
        except Exception:
            result["final_url"] = None
        return result

    finally:
        context.close()
        browser.close()


def print_result(result: dict):
    print("-" * 80)
    print(f"scan_no          : {result['scan_no']}")
    print(f"status           : {result['status']}")
    print(f"target_url       : {result['target_url']}")
    print(f"landing_url      : {result['landing_url']}")
    print(f"clicked_url      : {result['clicked_url']}")
    print(f"final_url        : {result['final_url']}")
    print(f"x_forwarded_for  : {result['x_forwarded_for']}")
    print(f"user_agent       : {result['user_agent'][:120]}")
    if result["error"]:
        print(f"error            : {result['error']}")


def main():
    profiles = load_simulation_profiles(SIMULATION_CSV)
    all_results: list[dict] = []
    scan_no = 1

    try:
        with sync_playwright() as p:
            if SCAN_COUNT <= 0:
                while True:
                    profile = random.choice(profiles)
                    print(f"\n[{scan_no}] Start | profile_ip={profile['ip_address']}")
                    result = run_single_scan(p, scan_no, profile)
                    all_results.append(result)
                    print_result(result)
                    scan_no += 1
                    random_sleep(ACTION_DELAY_MS)
            else:
                while scan_no <= SCAN_COUNT:
                    profile = random.choice(profiles)
                    print(
                        f"\n[{scan_no}/{SCAN_COUNT}] Start | profile_ip={profile['ip_address']}"
                    )
                    result = run_single_scan(p, scan_no, profile)
                    all_results.append(result)
                    print_result(result)
                    scan_no += 1
                    random_sleep(ACTION_DELAY_MS)

    except KeyboardInterrupt:
        print("\n\nZatrzymano skrypt przez użytkownika (Ctrl+C).")

    finally:
        print("\n=== OSTATNIE WYNIKI ===")
        for row in all_results[-10:]:
            print_result(row)


# ============================================================
# CZĘŚĆ WEBOWA (Flask) DLA RENDER / GUNICORN
# ============================================================

app = Flask(__name__)  # <- tego szuka gunicorn w "app:app"


def worker():
    # Jedno wywołanie main() – w środku jest pętla nieskończona
    main()


# Startujemy Playwright worker w tle przy imporcie modułu
threading.Thread(target=worker, daemon=True).start()


@app.route("/healthz")
def healthz():
    return "OK", 200

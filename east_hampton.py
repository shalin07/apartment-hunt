import re
import json
import os
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ─────────────────────────────────────────────
# 🔧 CONFIGURATION
# ─────────────────────────────────────────────

EMAIL_SENDER    = "shalinbarot34@gmail.com"      # Your Gmail address
EMAIL_PASSWORD  = "zymabljarsvdsboj"    # Gmail App Password
                                               # → myaccount.google.com/apppasswords
EMAIL_RECIPIENT = "shalinbarot34@gmail.com"      # Where alerts go

# ─────────────────────────────────────────────

BUILDING_URL = "https://www.newportrentals.com/apartments-jersey-city-for-rent/east-hampton/"
BUILDING_NAME = "East Hampton"
STATE_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_east_hampton.json")


# ── Persistence ───────────────────────────────

def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(STATE_FILE, "w") as f:
        json.dump(list(seen), f)


# ── Matching logic ────────────────────────────

def matches_criteria(unit: str) -> bool:
    unit = unit.strip()
    if not unit.isdigit() or not unit.endswith("04") or len(unit) < 3:
        return False
    return int(unit[:-2]) > 10


# ── Selenium ──────────────────────────────────

def fetch_listings() -> list[dict]:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )

    apartments = []

    try:
        print(f"  🌐 Loading {BUILDING_URL}")
        driver.get(BUILDING_URL)
        wait = WebDriverWait(driver, 20)

        # Click 1 BR tab
        one_br_tab = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//*[normalize-space(text())='1 BR' or normalize-space(text())='1BR']"
                       "[self::button or self::a or self::label or self::span or self::div]")
        ))
        driver.execute_script("arguments[0].click();", one_br_tab)
        print("  ✅ Clicked '1 BR' tab")
        time.sleep(5)

        # Get all listing ROW elements that contain "Residence XXXX"
        # We look for the row-level container (tr or a known listing div)
        # and check is_displayed() to skip hidden ones
        all_rows = driver.find_elements(By.XPATH,
            "//tr[.//td[contains(text(),'Residence')]] | "
            "//*[contains(@class,'unit') or contains(@class,'listing') or contains(@class,'apartment')]"
            "[.//*[contains(text(),'Residence')]]"
        )

        print(f"  Found {len(all_rows)} total row elements, filtering visible ones...")

        seen_units = set()
        for row in all_rows:
            # ── Skip anything hidden by the tab filter ──
            if not row.is_displayed():
                continue

            row_text = row.text.strip()
            if not row_text:
                continue

            m = re.search(r"Residence\s+(\d{3,4})", row_text)
            if not m:
                continue

            unit = m.group(1)
            if unit in seen_units:
                continue
            seen_units.add(unit)

            rent_m  = re.search(r"\$([\d,]+)\s*/mo", row_text)
            sqft_m  = re.search(r"(\d{3,4})\s*Sq\s*Ft", row_text)
            avail_m = re.search(r"Available\s+(Now|\d{1,2}/\d{1,2}/\d{4})", row_text)

            apartments.append({
                "unit":         unit,
                "name":         f"{BUILDING_NAME} | Residence {unit}",
                "rent":         f"${rent_m.group(1)}/mo" if rent_m else "N/A",
                "sqft":         sqft_m.group(0) if sqft_m else "N/A",
                "availability": avail_m.group(0) if avail_m else "Unknown",
            })

    finally:
        driver.quit()

    return apartments


# ── Email ─────────────────────────────────────

def send_email(matches: list[dict]):
    rows = "".join(f"""
        <tr>
          <td style="padding:8px;border:1px solid #ddd">{a['name']}</td>
          <td style="padding:8px;border:1px solid #ddd">{a['unit']}</td>
          <td style="padding:8px;border:1px solid #ddd">{a['rent']}</td>
          <td style="padding:8px;border:1px solid #ddd">{a['sqft']}</td>
          <td style="padding:8px;border:1px solid #ddd">{a['availability']}</td>
        </tr>""" for a in matches)

    html = f"""<html><body>
    <h2 style="color:#0077b6">🏠 {BUILDING_NAME} — New Match!</h2>
    <p>New <b>{BUILDING_NAME} 1BR</b> on <b>floor &gt; 16</b> with unit ending in <b>04</b>:</p>
    <table style="border-collapse:collapse;width:100%;font-family:sans-serif">
      <thead>
        <tr style="background:#0077b6;color:white">
          <th style="padding:8px">Apartment</th>
          <th style="padding:8px">Unit #</th>
          <th style="padding:8px">Rent</th>
          <th style="padding:8px">Size</th>
          <th style="padding:8px">Available</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <br>
    <a href="{BUILDING_URL}"
       style="background:#0077b6;color:white;padding:10px 20px;
              text-decoration:none;border-radius:5px">
      View {BUILDING_NAME} Listings →
    </a>
    <p style="color:#999;font-size:12px;margin-top:16px">
      Checked at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    </p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏠 Newport Alert: {len(matches)} {BUILDING_NAME} 1BR unit(s) found!"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(EMAIL_SENDER, EMAIL_PASSWORD)
        srv.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    print(f"  ✅ Email sent to {EMAIL_RECIPIENT}")


# ── Main ──────────────────────────────────────

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking {BUILDING_NAME} 1BR…")

    seen     = load_seen()
    listings = fetch_listings()

    print(f"  Visible 1BR units: {[a['unit'] for a in listings]}")

    new_matches = []

    for apt in listings:
        u = apt["unit"]
        if matches_criteria(u) and u not in seen:
            new_matches.append(apt)
            print(f"  🎯 MATCH: Residence {u} — {apt['rent']} — {apt['availability']}")

    # Only save matched units
    matched_this_run = {a["unit"] for a in listings if matches_criteria(a["unit"])}
    seen.update(matched_this_run)
    save_seen(seen)

    if new_matches:
        send_email(new_matches)
    else:
        hits = [a["unit"] for a in listings if matches_criteria(a["unit"])]
        if hits:
            print(f"  ℹ️  Already alerted on: {hits}")
        else:
            print(f"  ℹ️  No matching units yet (floor > 16, ends in 04)")


if __name__ == "__main__":
    main()

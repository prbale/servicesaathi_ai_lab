"""Browser walkthrough: login -> NL request -> pick slot -> confirm -> ticket; dev mode; labs."""
import sys
from playwright.sync_api import sync_playwright
import os
OUT = os.environ.get("SHOT_DIR", "e2e-screenshots"); os.makedirs(OUT, exist_ok=True)
BASE = os.environ.get("BASE_URL", "http://localhost:8000")
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
    pg = b.new_page(viewport={"width": 1360, "height": 900})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/login"); pg.wait_for_timeout(800)
    pg.screenshot(path=f"{OUT}/01_login.png")
    pg.get_by_role("button", name="Sign in").click()
    pg.wait_for_url("**/customer"); pg.wait_for_timeout(400)
    pg.get_by_role("button", name="Use the example").click()
    pg.get_by_role("button", name="Find a technician").click()
    pg.wait_for_selector(".tech", timeout=10000)
    pg.screenshot(path=f"{OUT}/02_request.png", full_page=True)
    pg.locator(".slot").first.click()
    pg.wait_for_selector(".confirm")
    pg.screenshot(path=f"{OUT}/03_confirm.png", full_page=True)
    pg.get_by_role("button", name="Confirm booking").click()
    pg.wait_for_selector(".ticket", timeout=10000); pg.wait_for_timeout(600)
    pg.screenshot(path=f"{OUT}/04_ticket.png")
    print("ticket:", pg.locator(".ticket-ref").inner_text())
    # missing-fields flow
    pg.get_by_role("button", name="Book another service").click()
    pg.fill("textarea", "Washing machine is not spinning")
    pg.get_by_role("button", name="Find a technician").click()
    pg.wait_for_selector(".question"); pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/05_questions.png", full_page=True)
    # policy tab
    pg.get_by_role("tab", name="Ask about policies").click()
    pg.get_by_role("button", name="How late can I cancel my booking for free?").click()
    pg.wait_for_selector(".answer"); pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/06_policy.png", full_page=True)
    # dev mode
    pg.get_by_role("checkbox", name="Developer mode").check()
    pg.get_by_role("tab", name="Book a service").click()
    pg.fill("textarea", "Burning smell and sparks from the switch board in Baner, today evening")
    pg.get_by_role("button", name="Find a technician").click()
    pg.wait_for_selector(".trace"); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/07_devmode.png")
    pg.get_by_role("checkbox", name="Developer mode").uncheck()
    # labs
    for lab, action in [("booking", "Run the race"), ("ml", "Classify"), ("rag", "Retrieve and answer"), ("sql", "Run read-only")]:
        pg.goto(f"{BASE}/lab/{lab}"); pg.wait_for_timeout(700)
        pg.get_by_role("button", name=action).click(); pg.wait_for_timeout(1800)
        pg.screenshot(path=f"{OUT}/08_lab_{lab}.png", full_page=True)
    # mobile
    m = b.new_page(viewport={"width": 390, "height": 844})
    m.goto(BASE + "/login"); m.wait_for_timeout(600)
    m.screenshot(path=f"{OUT}/09_mobile_login.png", full_page=True)
    sw = m.evaluate("document.documentElement.scrollWidth")
    print("mobile scrollWidth", sw)
    b.close()
print("console errors:", errors)

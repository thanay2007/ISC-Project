"""Run with a live stack: python -m backend.tests.browser_smoke."""
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[2]
output = root / ".verifex" / "browser-smoke"
output.mkdir(parents=True, exist_ok=True)
base = os.getenv("VERIFEX_TEST_URL", "http://localhost:3000")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel=os.getenv("VERIFEX_BROWSER_CHANNEL", "chrome"))
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    expect.set_options(timeout=20000)
    errors = []
    stages = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda res: stages.append(res.status) if "/events" in res.url else None)
    page.goto(base, wait_until="networkidle")
    expect(page.get_by_role("heading", name="Trust every document. Verify every detail.")).to_be_visible()
    expect(page.get_by_role("link", name="Open workspace")).to_have_count(0)
    expect(page.get_by_role("link", name="Explore the demo lab")).to_have_count(0)
    expect(page.get_by_role("link", name="Sign up", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="Sign in", exact=True)).to_have_class("button button-primary landing-sign-in")
    expect(page.get_by_text("DOCUMENT FORENSICS / 01", exact=True)).to_have_count(0)
    expect(page.locator(".landing-footer")).to_have_count(0)
    page.screenshot(path=output / "landing.png", full_page=True)
    page.get_by_role("link", name="Analyze a document", exact=True).click()
    expect(page).to_have_url(base + "/login?next=%2Fanalyzer")
    expect(page.get_by_role("heading", name="Sign in to VERIFEX")).to_be_visible()
    page.goto(base + "/sign-up?next=%2Fanalyzer")
    expect(page).to_have_url(base + "/login?next=%2Fanalyzer")
    expect(page.get_by_role("heading", name="Sign in to VERIFEX")).to_be_visible()
    page.goto(base + "/admin")
    expect(page.get_by_role("heading", name="Administrator access required")).to_be_visible()
    page.goto(base + "/dashboard")
    expect(page.get_by_role("heading", name="Verification activity")).to_be_visible()
    expect(page.get_by_role("heading", name="Security alerts")).to_have_count(0)
    expect(page.locator("aside").get_by_text("Forensic Workspace", exact=True)).to_have_count(0)
    page.goto(base + "/demo")
    expect(page.get_by_role("heading", name="Live demo lab")).to_be_visible(timeout=15000)
    nav = page.get_by_role("navigation", name="Main navigation")
    for name in ("Comparison", "QR verification", "Security monitoring", "Live demo", "Model performance", "Settings"):
        expect(nav.get_by_role("link", name=name, exact=True)).to_have_count(0)
    page.get_by_role("heading", name="Modified grade").locator("..").get_by_role("button", name="Run scenario").click()
    expect(page.get_by_text("Fake", exact=True)).to_be_visible(timeout=240000)
    expect(page.get_by_text("100/100 confidence", exact=True)).to_be_visible()
    expect(page.get_by_role("img", name="Uploaded document page 1")).to_be_visible()
    assert 200 in stages, "The live SSE stream was never established"
    page.get_by_role("button", name="text", exact=True).click()
    expect(page.get_by_role("heading", name="Extracted fields")).to_be_visible()
    expect(page.get_by_role("button", name="A+", exact=True)).to_be_visible()
    page.get_by_role("button", name="visual", exact=True).click()
    expect(page.get_by_role("heading", name="Custom AI Forgery Detection Engine")).to_be_visible()
    page.get_by_label("Image layer").select_option("heatmap")
    expect(page.locator(".image-layer")).to_have_js_property("complete", True, timeout=15000)
    assert page.locator(".image-layer").evaluate("(image) => image.naturalWidth > 0")
    page.screenshot(path=output / "analysis.png", full_page=True)
    expect(page.get_by_role("link", name="Compare", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="Signature file", exact=True)).to_have_count(0)
    page.goto(base + "/reports")
    expect(page.get_by_role("link", name="Download PDF", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="SIG", exact=True)).to_have_count(0)
    page.goto(base + "/demo")
    page.get_by_role("heading", name="Unauthorized access").locator("..").get_by_role("button", name="Run scenario").click()
    expect(page.get_by_text("HTTP 403", exact=True)).to_be_visible(timeout=10000)
    page.get_by_role("link", name="Open recorded security alert").click()
    expect(page.get_by_text("Attempted to access a restricted certificate")).to_be_visible()
    page.goto(base + "/analyzer")
    expect(page.get_by_role("heading", name="Sign in to analyze a document")).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/model-performance")
    expect(page.get_by_role("heading", name="Model performance", exact=True)).to_be_visible()
    expect(page.get_by_text("Accuracy", exact=True).first).to_be_visible()
    expect(page.get_by_role("heading", name="Results by dataset", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth"), "Horizontal overflow at 390px"
    page.screenshot(path=output / "model-mobile.png", full_page=True)
    assert not errors, errors
    print(f"Browser smoke passed. Screenshots: {output}")

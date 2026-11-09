"""Run with a live stack: python -m backend.tests.browser_smoke."""
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright
from reportlab.pdfgen import canvas

root = Path(__file__).resolve().parents[2]
output = root / ".verifex" / "browser-smoke"
output.mkdir(parents=True, exist_ok=True)
base = os.getenv("VERIFEX_TEST_URL", "http://localhost:3000")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel=os.getenv("VERIFEX_BROWSER_CHANNEL", "chrome"))
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    stages = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda res: stages.append(res.status) if "/events" in res.url else None)
    page.goto(base, wait_until="networkidle")
    expect(page.get_by_role("heading", name="Trust every document. Verify every detail.")).to_be_visible()
    page.screenshot(path=output / "landing.png", full_page=True)
    page.goto(base + "/login?next=/demo")
    page.get_by_role("button", name="New to VERIFEX? Create an account").click()
    page.get_by_label("Display name").fill("Browser Smoke")
    page.get_by_label("Email address").fill(f"smoke-{uuid4().hex[:8]}@example.test")
    page.get_by_label("Password").fill("temporary-smoke-test-321")
    page.get_by_role("button", name="Create account", exact=True).click()
    expect(page.get_by_role("heading", name="Live demo lab")).to_be_visible(timeout=15000)
    page.get_by_role("heading", name="Modified grade").locator("..").get_by_role("button", name="Run scenario").click()
    expect(page.get_by_text("Integrity mismatch", exact=True)).to_be_visible(timeout=240000)
    expect(page.get_by_role("img", name="Uploaded document page 1")).to_be_visible()
    assert 200 in stages, "The live SSE stream was never established"
    page.get_by_role("button", name="text", exact=True).click()
    expect(page.get_by_role("heading", name="Authorized original vs. uploaded OCR")).to_be_visible()
    expect(page.locator("table").get_by_role("cell", name="A+", exact=True)).to_be_visible()
    page.get_by_role("button", name="visual", exact=True).click()
    expect(page.get_by_role("heading", name="Custom AI Forgery Detection Engine")).to_be_visible()
    page.get_by_label("Image layer").select_option("heatmap")
    expect(page.locator(".image-layer")).to_have_js_property("complete", True, timeout=15000)
    assert page.locator(".image-layer").evaluate("(image) => image.naturalWidth > 0")
    page.screenshot(path=output / "analysis.png", full_page=True)
    page.get_by_role("link", name="Compare", exact=True).click()
    expect(page.get_by_role("img", name="Authorized original page 1")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Before / after").click()
    expect(page.get_by_label("Original reveal percentage")).to_be_visible()
    page.goto(base + "/demo")
    page.get_by_role("heading", name="Unauthorized access").locator("..").get_by_role("button", name="Run scenario").click()
    expect(page.get_by_text("HTTP 403", exact=True)).to_be_visible(timeout=10000)
    page.get_by_role("link", name="Open recorded security alert").click()
    expect(page.get_by_text("Attempted to access a restricted certificate")).to_be_visible()
    pdf = output / "local-upload.pdf"
    document = canvas.Canvas(str(pdf))
    for index in range(2):
        document.drawString(70, 770, f"Student: Fictional Test {index + 1}")
        document.showPage()
    document.save()
    page.goto(base + "/analyzer")
    page.locator('input[type="file"]').set_input_files(pdf)
    expect(page.locator(".local-preview canvas")).to_be_visible(timeout=20000)
    page.get_by_role("button", name="Run analysis").click()
    expect(page.get_by_role("link", name="Signed report")).to_be_visible(timeout=40000)
    page.get_by_role("button", name="Next page").click()
    expect(page.get_by_role("img", name="Uploaded document page 2")).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/model-performance")
    expect(page.get_by_role("heading", name="Model performance", exact=True)).to_be_visible()
    expect(page.get_by_text("Accuracy", exact=True).first).to_be_visible()
    expect(page.get_by_text("Kriyam TamperFlow · C0 · 16 images", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth"), "Horizontal overflow at 390px"
    page.screenshot(path=output / "model-mobile.png", full_page=True)
    assert not errors, errors
    print(f"Browser smoke passed. Screenshots: {output}")

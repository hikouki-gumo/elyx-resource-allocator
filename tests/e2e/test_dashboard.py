"""E2E/UI tests (Playwright) — drive the rendered dashboard, capture screenshots.

Run: .venv/bin/python -m pytest tests/e2e -m e2e
"""
from pathlib import Path
import pytest

from elyx_allocator.pipeline import build_site


@pytest.fixture
def site(tmp_path):
    """Build the real dashboard from the full pipeline into a temp dir."""
    return Path(build_site(tmp_path))


@pytest.mark.e2e
def test_event_click_reveals_reason(page, site, tmp_path):
    page.goto(site.as_uri())
    page.get_by_test_id("event").first.click()
    reason = page.get_by_test_id("reason")
    assert reason.is_visible()
    assert reason.inner_text().strip()
    page.screenshot(path=str(tmp_path / "event-detail.png"))


@pytest.mark.e2e
def test_back_button_returns_to_day(page, site, tmp_path):
    page.goto(site.as_uri())
    page.get_by_test_id("day").first.click()          # open day schedule
    page.get_by_test_id("day-event").first.click()    # drill into an event
    page.get_by_test_id("back").click()               # back to the day
    assert page.get_by_test_id("day-schedule").is_visible()


@pytest.mark.e2e
def test_month_toggle_shows_month_grid(page, site, tmp_path):
    page.goto(site.as_uri())
    page.get_by_test_id("view-month").click()
    assert page.get_by_test_id("month-grid").is_visible()
    page.screenshot(path=str(tmp_path / "month-view.png"))


@pytest.mark.e2e
def test_type_filter_hides_events(page, site):
    page.goto(site.as_uri())
    before = page.get_by_test_id("event").count()
    page.get_by_test_id("filter-fitness").click()  # toggle off the Fitness type
    after = page.get_by_test_id("event").count()
    assert after < before


@pytest.mark.e2e
def test_milestone_click_opens_detail(page, site):
    page.goto(site.as_uri())
    page.get_by_test_id("milestone").first.click()
    assert page.get_by_test_id("reason").is_visible() or page.get_by_test_id("day-schedule").is_visible()

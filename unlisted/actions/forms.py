"""Fill opt-out web forms in a real, visible browser, handing off to you at CAPTCHAs.

Recipes live in unlisted/recipes/<name>.yaml (or ~/.unlisted/recipes/) as a
list of steps:

  - goto: "{optout_url}"
  - fill: {selector: "input[name=url]", value: "{listing_url}"}
  - click: "button[type=submit]"
  - human: "Solve the CAPTCHA, then press Enter here."
  - wait_for: "text=Check your email"

Values are formatted with the profile fields and the listing URL. Playwright
is optional: `pip install playwright` (browsers must be installed separately).
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml

from ..profile import Profile, home_dir


class RecipeUnavailable(Exception):
    pass


def load_recipe(name: str) -> list[dict]:
    local = home_dir() / "recipes" / f"{name}.yaml"
    if local.exists():
        return yaml.safe_load(local.read_text())
    bundled = resources.files("unlisted.recipes").joinpath(f"{name}.yaml")
    if not bundled.is_file():
        raise RecipeUnavailable(f"no recipe named {name!r}")
    return yaml.safe_load(bundled.read_text())


def recipe_vars(profile: Profile, optout_url: str, listing_url: str) -> dict[str, str]:
    a = profile.primary_address
    return {
        "optout_url": optout_url,
        "listing_url": listing_url,
        "full_name": profile.full_name,
        "first": profile.first,
        "last": profile.last,
        "email": profile.contact_email,
        "phone": profile.phones[0] if profile.phones else "",
        "street": a.street, "city": a.city, "state": a.state, "zip": a.zip,
    }


def run_recipe(steps: list[dict], values: dict[str, str], screenshot_dir: Path) -> Path:
    """Run a recipe; returns the path of a screenshot of the final page as a receipt."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RecipeUnavailable("playwright is not installed") from exc

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        for step in steps:
            (action, arg), = step.items()
            if action == "goto":
                page.goto(arg.format(**values))
            elif action == "fill":
                page.fill(arg["selector"], arg["value"].format(**values))
            elif action == "select":
                page.select_option(arg["selector"], arg["value"].format(**values))
            elif action == "check":
                page.check(arg)
            elif action == "click":
                page.click(arg)
            elif action == "wait_for":
                page.wait_for_selector(arg, timeout=120_000)
            elif action == "human":
                input(f"\n>>> {arg} ")
            else:
                raise ValueError(f"unknown recipe step {action!r}")
        receipt = screenshot_dir / f"{values['optout_url'].split('/')[2]}.png"
        page.screenshot(path=str(receipt), full_page=True)
        browser.close()
    return receipt

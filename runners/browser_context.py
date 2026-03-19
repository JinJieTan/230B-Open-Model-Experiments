from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from scripts.runtime import env_bool, env_int, env_str


_ALLOWED_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BrowserSettings:
    enabled: bool
    url: str
    timeout_sec: int
    max_chars: int
    max_links: int
    wait_until: str
    headless: bool
    disable_sandbox: bool
    refresh_every_round: bool
    round_interval: int
    required: bool


class BrowserSession:
    def __init__(self, settings: BrowserSettings) -> None:
        self.settings = settings
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._loaded = False

    @property
    def required(self) -> bool:
        return self.settings.required

    def snapshot(self, *, round_number: int, total_rounds: int) -> dict[str, Any]:
        if self.settings.round_interval > 1 and (round_number - 1) % self.settings.round_interval != 0:
            return {
                "status": "skipped_interval",
                "round": round_number,
                "total_rounds": total_rounds,
                "captured_at": utcnow_iso(),
                "url": self.settings.url,
            }

        self._ensure_started()

        timeout_ms = max(1, self.settings.timeout_sec) * 1000
        if self.settings.refresh_every_round or not self._loaded:
            self._page.goto(self.settings.url, wait_until=self.settings.wait_until, timeout=timeout_ms)
            self._loaded = True

        title = str(self._page.title() or "").strip()
        body_text = str(self._page.evaluate("() => document.body ? document.body.innerText : ''") or "")
        body_text = " ".join(body_text.split())
        if self.settings.max_chars > 0 and len(body_text) > self.settings.max_chars:
            body_text = body_text[: self.settings.max_chars] + " ... (truncated)"

        links: list[dict[str, str]] = []
        raw_links = self._page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({text: (e.innerText || '').trim(), href: e.href || ''}))",
        )
        seen: set[str] = set()
        for item in raw_links:
            href = str(item.get("href", "")).strip()
            if not href or href in seen:
                continue
            seen.add(href)
            text = str(item.get("text", "")).strip()
            links.append({"text": text, "href": href})
            if len(links) >= self.settings.max_links:
                break

        return {
            "status": "ok",
            "round": round_number,
            "total_rounds": total_rounds,
            "captured_at": utcnow_iso(),
            "url": self._page.url,
            "title": title,
            "text": body_text,
            "links": links,
        }

    def close(self) -> None:
        for obj in [self._page, self._context, self._browser]:
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:  # noqa: BLE001
                pass

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._loaded = False

    def _ensure_started(self) -> None:
        if self._page is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Playwright is not available. Install with: pip install playwright && python -m playwright install chromium"
            ) from exc

        self._playwright = sync_playwright().start()

        launch_args: list[str] = []
        if self.settings.disable_sandbox:
            launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox"])

        self._browser = self._playwright.chromium.launch(
            headless=self.settings.headless,
            args=launch_args,
        )
        self._context = self._browser.new_context()
        self._page = self._context.new_page()


def resolve_browser_settings(config: dict[str, Any]) -> BrowserSettings:
    browser_cfg = config.get("browser")
    if not isinstance(browser_cfg, dict):
        browser_cfg = {}

    enabled = bool(browser_cfg.get("enabled", env_bool("ENABLE_HEADLESS_BROWSER", False)))

    url = str(browser_cfg.get("url", env_str("BROWSER_BASE_URL", ""))).strip()
    timeout_sec = int(browser_cfg.get("timeout_sec", env_int("BROWSER_TIMEOUT_SEC", 60)))
    max_chars = int(browser_cfg.get("max_chars", env_int("BROWSER_MAX_CHARS", 3000)))
    max_links = int(browser_cfg.get("max_links", env_int("BROWSER_MAX_LINKS", 8)))
    wait_until = str(browser_cfg.get("wait_until", env_str("BROWSER_WAIT_UNTIL", "domcontentloaded"))).strip().lower()
    if wait_until not in _ALLOWED_WAIT_UNTIL:
        wait_until = "domcontentloaded"

    headless = bool(browser_cfg.get("headless", env_bool("BROWSER_HEADLESS", True)))
    disable_sandbox = bool(browser_cfg.get("disable_sandbox", env_bool("BROWSER_DISABLE_SANDBOX", True)))
    refresh_every_round = bool(browser_cfg.get("refresh_every_round", env_bool("BROWSER_REFRESH_EVERY_ROUND", True)))
    round_interval = int(browser_cfg.get("round_interval", env_int("BROWSER_ROUND_INTERVAL", 1)))
    required = bool(browser_cfg.get("required", env_bool("BROWSER_REQUIRED", False)))

    if enabled and not url:
        enabled = False

    return BrowserSettings(
        enabled=enabled,
        url=url,
        timeout_sec=max(5, timeout_sec),
        max_chars=max(400, max_chars),
        max_links=max(0, max_links),
        wait_until=wait_until,
        headless=headless,
        disable_sandbox=disable_sandbox,
        refresh_every_round=refresh_every_round,
        round_interval=max(1, round_interval),
        required=required,
    )


def browser_snapshot_to_message(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status", "unknown"))
    if status != "ok":
        return f"[Browser Snapshot] status={status} url={snapshot.get('url', '')}"

    lines: list[str] = []
    lines.append("[Browser Snapshot]")
    lines.append(f"round: {snapshot.get('round')}/{snapshot.get('total_rounds')}")
    lines.append(f"url: {snapshot.get('url', '')}")
    lines.append(f"title: {snapshot.get('title', '')}")
    lines.append(f"captured_at: {snapshot.get('captured_at', '')}")

    text = str(snapshot.get("text", "")).strip()
    if text:
        lines.append("body_excerpt:")
        lines.append(text)

    links = snapshot.get("links") or []
    if links:
        lines.append("top_links:")
        for idx, item in enumerate(links, start=1):
            href = str(item.get("href", "")).strip()
            text = str(item.get("text", "")).strip()
            lines.append(f"{idx}. {text} -> {href}")

    lines.append("Use this snapshot as external context and cite assumptions.")
    return "\n".join(lines)


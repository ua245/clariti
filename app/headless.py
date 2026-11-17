#!/usr/bin/env python3
"""Headless Clariti runner: sitemap capture + companion prompt to stdout/chat.

Example:
  python3 -m app.headless https://example.com --scope "Public pages privacy review"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.checklist.service import load_default_template
from app.companions.manual import ManualCompanionConnector
from app.config import PLAYWRIGHT_BROWSERS_DIR
from app.evidence.service import (
    add_bytes_screenshot_evidence,
    add_rendered_text_evidence,
)
from app.export.reports import pdf_report
from app.fetch.network_policy import NetworkPolicyError
from app.fetch.site_capture import capture_full_site
from app.storage.db import Database


def _ensure_browser_env() -> None:
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and PLAYWRIGHT_BROWSERS_DIR.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)


def _validate_website(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "Website must be an HTTPS URL without embedded credentials."
        )
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Clariti headless sitemap capture and print companion-ready output "
            "for chat / clipboard use."
        )
    )
    parser.add_argument("website", help="HTTPS website URL to review")
    parser.add_argument(
        "--scope",
        default="Headless Clariti privacy evidence capture of public pages.",
        help="Review scope text",
    )
    parser.add_argument(
        "--checklist",
        nargs="*",
        default=None,
        help="Checklist item IDs (default: all active template items)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Optional durable data directory (default: temp dir)",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Optional path to write a draft PDF including all screenshots",
    )
    parser.add_argument(
        "--package",
        type=Path,
        default=None,
        help="Optional path to copy the Companion handoff zip (prompt + screenshots)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help=(
            "Open a headed browser, pause for Cloudflare/login (press Enter in this "
            "terminal), then crawl the sitemap in that session"
        ),
    )
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="Also print a machine-readable JSON summary block after the prompt",
    )
    return parser.parse_args(argv)


async def run_headless(args: argparse.Namespace) -> int:
    from app.security_runtime import bootstrap_security_checks

    try:
        bootstrap_security_checks()
    except SystemExit as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    _ensure_browser_env()
    try:
        website = _validate_website(args.website.strip())
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    if args.data_dir:
        data_dir = args.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        cleanup = None
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="clariti-headless-")
        data_dir = Path(cleanup.name)

    database = Database(data_dir / "clariti.sqlite3")
    template = load_default_template()
    database.initialize(template)
    selected = args.checklist or [item.id for item in template.items]
    available = {item.id for item in template.items}
    unknown = set(selected) - available
    if unknown:
        print(f"ERROR: unknown checklist IDs: {sorted(unknown)}", file=sys.stderr)
        return 2

    review_id = f"review-{uuid4()}"
    database.create_review(review_id, website, args.scope.strip(), template, selected)

    print(f"# Clariti headless capture\n", flush=True)
    print(f"- review_id: `{review_id}`")
    print(f"- website: `{website}`")
    mode_label = (
        "sitemap headed HITL"
        if args.headed
        else "sitemap headless"
    )
    print(f"- mode: `{mode_label}` (full sitemap + prioritized screenshots)\n", flush=True)

    try:
        if args.headed:
            from app.fetch.site_capture import HitlSitemapSession

            session = HitlSitemapSession(website)
            task = asyncio.create_task(session.run())
            while session.status == "starting":
                await asyncio.sleep(0.05)
            while session.status == "waiting_for_human":
                print(
                    f"\nHITL pause: {session.hint or 'Complete Cloudflare/login in the browser.'}"
                )
                print("Press Enter here after the browser gate is done (or type cancel)…", flush=True)
                line = await asyncio.to_thread(sys.stdin.readline)
                if line.strip().lower() == "cancel":
                    session.request_cancel()
                    await task
                    print("Cancelled.", file=sys.stderr)
                    return 1
                session.request_continue()
                # Wait until scanning, completed, failed, cancelled, or another pause.
                while session.status == "waiting_for_human":
                    await asyncio.sleep(0.05)
                while session.status == "scanning":
                    await asyncio.sleep(0.1)
            await task
            if session.status != "completed" or session.site_result is None:
                print(
                    f"ERROR: headed sitemap failed: {session.error or session.status}",
                    file=sys.stderr,
                )
                return 1
            site = session.site_result
        else:
            site = await capture_full_site(website, headless=True)
    except NetworkPolicyError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"ERROR: capture failed: {error.__class__.__name__}: {error}", file=sys.stderr)
        return 1

    evidence_ids: list[str] = []
    evidence_ids.append(
        add_rendered_text_evidence(
            database,
            review_id,
            site.overview_text(),
            site.final_url or website,
            site.limitations,
        )
    )
    evidence_ids.append(
        add_rendered_text_evidence(
            database,
            review_id,
            site.sitemap.summary_text(),
            website,
            site.sitemap.limitations,
            capture_method="static",
        )
    )
    for page in site.pages:
        evidence_ids.append(
            add_rendered_text_evidence(
                database,
                review_id,
                page.text,
                page.final_url,
                page.limitations,
                capture_method="static",
                http_status=page.http_status,
            )
        )
    for shot in site.shots:
        evidence_ids.append(
            add_bytes_screenshot_evidence(
                database,
                review_id,
                shot.png_bytes,
                shot.source_url,
                f"{shot.note} {site.limitations}".strip(),
            )
        )

    review = database.get_review(review_id)
    assert review is not None
    evidence = database.list_evidence(review_id)
    connector = ManualCompanionConnector()
    handoff = connector.prepare_handoff(
        review,
        evidence,
        artifact_dir=database.artifact_dir,
        package_dir=database.artifact_dir / "handoffs",
    )
    database.create_handoff_batch(
        handoff.batch_id,
        review_id,
        str(review["checklist_version"]),
        evidence_ids,
        handoff.manifest,
        handoff.prompt,
    )

    print("## Capture summary\n")
    print(f"- sitemap URLs: **{len(site.sitemap.page_urls)}**")
    print(f"- static page texts: **{len(site.pages)}**")
    print(f"- screenshots: **{len(site.shots)}**")
    print(f"- evidence items: **{len(evidence_ids)}**")
    print(f"- batch_id: `{handoff.batch_id}`")
    if handoff.package_path:
        print(f"- handoff package (prompt + screenshots): `{handoff.package_path}`")
    print()

    print("## Companion system prompt + handoff (paste into chat / Companion)\n")
    print("```text")
    print(handoff.prompt)
    print("```\n")
    if handoff.screenshot_count:
        print(
            f"Upload the **{handoff.screenshot_count}** screenshot file(s) from the "
            "handoff zip `screenshots/` folder with the Companion turn.\n"
        )

    if args.pdf:
        review_payload = dict(review)
        review_payload["evidence"] = evidence
        review_payload["effective_findings"] = []
        args.pdf.parent.mkdir(parents=True, exist_ok=True)
        args.pdf.write_bytes(
            pdf_report(review_payload, final=False, artifact_dir=database.artifact_dir)
        )
        print(f"Wrote PDF with all screenshots to `{args.pdf}`\n")

    if args.package:
        args.package.parent.mkdir(parents=True, exist_ok=True)
        if handoff.package_path and handoff.package_path.is_file():
            args.package.write_bytes(handoff.package_path.read_bytes())
            print(f"Wrote Companion handoff package to `{args.package}`\n")

    if args.json_summary:
        summary = {
            "review_id": review_id,
            "batch_id": handoff.batch_id,
            "website": website,
            "final_url": site.final_url,
            "sitemap_url_count": len(site.sitemap.page_urls),
            "page_text_count": len(site.pages),
            "screenshot_count": len(site.shots),
            "handoff_screenshot_count": handoff.screenshot_count,
            "evidence_ids": evidence_ids,
            "pdf": str(args.pdf) if args.pdf else None,
            "package": str(args.package)
            if args.package
            else (str(handoff.package_path) if handoff.package_path else None),
        }
        print("## JSON summary\n")
        print("```json")
        print(json.dumps(summary, indent=2))
        print("```")

    if cleanup is not None:
        cleanup.cleanup()
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    raise SystemExit(asyncio.run(run_headless(args)))


if __name__ == "__main__":
    main()

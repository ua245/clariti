# Decisions

## 2026-11-11: Local FastAPI foundation

Use FastAPI, SQLite, static HTML/CSS/JavaScript, and a project-local virtual
environment. This avoids a Node build chain and supports local-only deployment.

## 2026-11-11: Manual Companion transport

Companion link opens only after a user action. Evidence upload and response
import remain manual because the link is a browser navigation URL, not a known
API endpoint or credential.

## 2026-11-11: Foundation before retrieval

Implement manual evidence before network retrieval. This preserves a usable,
low-risk workflow while SSRF, browser, and SiteOne controls are designed and
tested in later milestones.

## 2026-11-11: Immutable review snapshots and evidence

Each review stores its selected checklist IDs and full checklist JSON snapshot.
New checklist versions become active only for later reviews. Text evidence and
reviewer-confirmed PNG/JPEG uploads use generated IDs and immutable files;
application UI renders evidence with DOM text nodes, not HTML parsing.

## 2026-11-11: Local request defences

State-changing requests require the exact configured local Host, matching
Origin, and a random same-site CSRF cookie/header pair. This supports local
browser use without exposing a network API or enabling CORS.

## 2026-11-11: Strict manual Companion contract

Manual handoffs persist a batch manifest and schema generated from authoritative
Pydantic models. Response import accepts raw JSON or one JSON fence only,
rejects duplicate object keys before validation, and never repairs model output.
The application stores original output separately from draft findings.

## 2026-11-12: Constrained Playwright capture

Use Playwright Chromium for optional headless capture of the review website
only. Destination checks require HTTPS, the review host allowlist (including
www/apex twin), and public resolvable addresses. Capture scrolls for common
privacy/cookie/consent/newsletter indicators and stores local screenshots plus
a text summary. It does not follow off-host links or automate Companion chat.

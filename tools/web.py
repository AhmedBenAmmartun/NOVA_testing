"""Read-oriented web research tools for NOVA OS.

The tools deliberately operate on public HTTP(S) resources only, reject local
and private-network targets, cap response/download sizes, and treat webpage
content as untrusted data rather than instructions.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from ddgs import DDGS
from livekit.agents import RunContext, function_tool

from nova_policy import ActionPolicy, PermissionLevel, permission_engine

from .common import logger


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) NOVA/1.0"
)
MAX_PAGE_BYTES = 2_000_000
MAX_PAGE_TEXT = 16_000
MAX_DOWNLOAD_BYTES = 50_000_000
DOWNLOAD_DIR = Path.home() / "Downloads" / "NOVA Downloads"

permission_engine.register(
    ActionPolicy(
        name="web_download",
        level=PermissionLevel.REVERSIBLE,
        confirmation_message="",
        timeout_seconds=60,
    )
)


@dataclass(slots=True)
class ParsedPage:
    url: str
    title: str
    text: str
    links: list[tuple[str, str]]


class _ReadableHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = True
        if lowered == "a":
            href = dict(attrs).get("href")
            if href:
                self._link_href = urljoin(self.base_url, href)
                self._link_text = []
        if lowered in {"p", "div", "section", "article", "main", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg", "canvas"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if lowered == "title":
            self._in_title = False
        if lowered == "a" and self._link_href:
            text = _collapse_ws(" ".join(self._link_text)) or self._link_href
            self.links.append((text[:240], self._link_href))
            self._link_href = None
            self._link_text = []
        if lowered in {"p", "div", "section", "article", "main", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)
        if self._link_href:
            self._link_text.append(data)

    def page(self, final_url: str) -> ParsedPage:
        title = _collapse_ws(" ".join(self._title_parts))
        text = _normalize_page_text("".join(self._text_parts))
        return ParsedPage(
            url=final_url,
            title=title,
            text=text,
            links=self.links,
        )


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_page_text(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = _collapse_ws(raw_line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _clean_domain(value: str) -> str | None:
    raw = value.strip().lower()
    if not raw:
        return None
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    raw = raw.strip("./ ")
    if raw.startswith("www."):
        raw = raw[4:]
    if not re.fullmatch(r"[a-z0-9.-]+", raw) or "." not in raw:
        return None
    return raw


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_public_url_sync(raw_url: str) -> str:
    value = raw_url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only public http:// and https:// URLs are allowed.")
    if not parsed.hostname:
        raise ValueError("The URL is missing a hostname.")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local/private network URLs are not available to the web reader.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("The webpage hostname could not be resolved.") from exc

    addresses = {info[4][0] for info in infos}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise ValueError("Local/private network URLs are not available to the web reader.")
    return value


async def _validate_public_url(raw_url: str) -> str:
    return await asyncio.to_thread(_validate_public_url_sync, raw_url)


def _request_public_sync(url: str, *, max_bytes: int) -> tuple[requests.Response, bytes]:
    current = url
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/xhtml+xml,*/*;q=0.5"}

    for _ in range(6):
        _validate_public_url_sync(current)
        response = session.get(
            current,
            headers=headers,
            timeout=(5, 12),
            allow_redirects=False,
            stream=True,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("The server returned an invalid redirect.")
            current = urljoin(current, location)
            continue

        response.raise_for_status()
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > max_bytes:
                    response.close()
                    raise ValueError("The web resource is larger than NOVA's safety limit.")
            except ValueError as exc:
                if "larger" in str(exc):
                    raise

        data = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > max_bytes:
                response.close()
                raise ValueError("The web resource exceeded NOVA's safety limit.")
        return response, bytes(data)

    raise ValueError("The webpage redirected too many times.")


def _decode_text(response: requests.Response, data: bytes) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _fetch_page_sync(url: str) -> ParsedPage:
    response, data = _request_public_sync(url, max_bytes=MAX_PAGE_BYTES)
    final_url = response.url
    content_type = response.headers.get("Content-Type", "").lower()
    text = _decode_text(response, data)

    if "html" in content_type or "xhtml" in content_type or "<html" in text[:1000].lower():
        parser = _ReadableHTMLParser(final_url)
        parser.feed(text)
        parser.close()
        return parser.page(final_url)

    if content_type.startswith("text/") or not content_type:
        return ParsedPage(
            url=final_url,
            title="",
            text=_normalize_page_text(text),
            links=[],
        )

    raise ValueError(f"Unsupported webpage content type: {content_type or 'unknown'}")


async def _fetch_page(url: str) -> ParsedPage:
    validated = await _validate_public_url(url)
    return await asyncio.wait_for(asyncio.to_thread(_fetch_page_sync, validated), timeout=20)


def _search_sync(query: str, *, max_results: int = 6) -> list[dict]:
    """Run resilient public web search through DDGS metasearch."""
    attempts = (
        "auto",
        "bing, brave, duckduckgo, google",
    )
    last_error: Exception | None = None

    for backend in attempts:
        try:
            results = DDGS(timeout=8).text(
                query,
                region="us-en",
                safesearch="moderate",
                max_results=max_results,
                backend=backend,
            )
            normalized = list(results or [])
            if normalized:
                return normalized[:max_results]
        except Exception as exc:
            last_error = exc
            logger.warning(
                "web search backend failed backend=%s error=%s",
                backend,
                type(exc).__name__,
            )

    if last_error is not None:
        raise RuntimeError(
            "All configured public web-search backends failed or returned no results."
        ) from last_error

    return []
def _format_search_results(results: list[dict]) -> str:
    if not results:
        return "No web results were found."
    blocks: list[str] = []
    for index, result in enumerate(results, start=1):
        title = _collapse_ws(str(result.get("title", "Untitled result")))
        body = _collapse_ws(str(result.get("body", "")))
        href = str(result.get("href", "")).strip()
        blocks.append(f"{index}. {title}\n{body}\nSource: {href}")
    return "\n\n".join(blocks)


@function_tool()
async def web_search(context: RunContext, query: str, max_results: int = 6) -> str:
    """Search the public web and return titles, snippets, and source URLs."""
    del context
    cleaned = query.strip()
    if not cleaned:
        return "Tell me what you want to search for."
    limit = max(1, min(int(max_results), 10))
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(_search_sync, cleaned, max_results=limit),
            timeout=12,
        )
        return _format_search_results(results)
    except asyncio.TimeoutError:
        return "The web search timed out."
    except Exception:
        logger.exception("web_search failed")
        return "I could not complete the web search."


@function_tool()
async def web_search_site(
    context: RunContext,
    query: str,
    domain: str,
    max_results: int = 6,
) -> str:
    """Search the web but restrict results to one public domain, such as microsoft.com."""
    del context
    cleaned_domain = _clean_domain(domain)
    if cleaned_domain is None:
        return "Give me a valid public domain such as microsoft.com or docs.livekit.io."
    cleaned_query = query.strip()
    if not cleaned_query:
        return "Tell me what you want to search for on that site."
    limit = max(1, min(int(max_results), 10))
    search_query = f"site:{cleaned_domain} {cleaned_query}"
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(_search_sync, search_query, max_results=limit),
            timeout=12,
        )
        return _format_search_results(results)
    except asyncio.TimeoutError:
        return "The site-restricted search timed out."
    except Exception:
        logger.exception("web_search_site failed")
        return "I could not complete the site-restricted search."


@function_tool()
async def web_read_page(context: RunContext, url: str) -> str:
    """Read the main text of one public webpage without using screenshots."""
    del context
    try:
        page = await _fetch_page(url)
        text = page.text[:MAX_PAGE_TEXT]
        truncated = len(page.text) > MAX_PAGE_TEXT
        heading = f"Title: {page.title}\n" if page.title else ""
        suffix = "\n\n[Page text truncated by NOVA.]" if truncated else ""
        return f"{heading}URL: {page.url}\n\n{text}{suffix}"
    except asyncio.TimeoutError:
        return "The webpage took too long to load."
    except ValueError as exc:
        return f"I could not read that webpage: {exc}"
    except Exception:
        logger.exception("web_read_page failed")
        return "I could not read that webpage."


@function_tool()
async def web_find_on_page(
    context: RunContext,
    url: str,
    text: str,
    max_matches: int = 6,
) -> str:
    """Find a word or phrase in a public webpage and return nearby text."""
    del context
    needle = _collapse_ws(text)
    if not needle:
        return "Tell me what text to find on the page."
    try:
        page = await _fetch_page(url)
        haystack = page.text
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        matches = list(pattern.finditer(haystack))[: max(1, min(int(max_matches), 12))]
        if not matches:
            return f"I did not find '{needle}' on {page.url}."
        lines = [f"Matches for '{needle}' on {page.url}:"]
        for index, match in enumerate(matches, start=1):
            start = max(0, match.start() - 220)
            end = min(len(haystack), match.end() + 320)
            context_text = _collapse_ws(haystack[start:end])
            lines.append(f"{index}. ...{context_text}...")
        return "\n".join(lines)
    except asyncio.TimeoutError:
        return "The webpage took too long to load."
    except ValueError as exc:
        return f"I could not search that webpage: {exc}"
    except Exception:
        logger.exception("web_find_on_page failed")
        return "I could not search that webpage."


@function_tool()
async def web_list_links(
    context: RunContext,
    url: str,
    contains: str = "",
    max_links: int = 30,
) -> str:
    """List links from a public webpage, optionally filtering by link text or URL."""
    del context
    try:
        page = await _fetch_page(url)
        filter_text = contains.strip().lower()
        seen: set[str] = set()
        selected: list[tuple[str, str]] = []
        for label, href in page.links:
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue
            if filter_text and filter_text not in f"{label} {href}".lower():
                continue
            if href in seen:
                continue
            seen.add(href)
            selected.append((label, href))
            if len(selected) >= max(1, min(int(max_links), 50)):
                break
        if not selected:
            return "No matching public links were found on that page."
        lines = [f"Links from {page.url}:"]
        for index, (label, href) in enumerate(selected, start=1):
            lines.append(f"{index}. {label}\n{href}")
        return "\n".join(lines)
    except asyncio.TimeoutError:
        return "The webpage took too long to load."
    except ValueError as exc:
        return f"I could not inspect links on that webpage: {exc}"
    except Exception:
        logger.exception("web_list_links failed")
        return "I could not inspect links on that webpage."


@function_tool()
async def web_extract_text(
    context: RunContext,
    url: str,
    start_phrase: str = "",
    end_phrase: str = "",
    max_chars: int = 8000,
) -> str:
    """Extract webpage text, optionally between a start phrase and an end phrase."""
    del context
    try:
        page = await _fetch_page(url)
        value = page.text
        lower = value.lower()
        start = 0
        end = len(value)
        if start_phrase.strip():
            position = lower.find(start_phrase.strip().lower())
            if position < 0:
                return f"I could not find the start phrase '{start_phrase}' on the page."
            start = position
        if end_phrase.strip():
            position = lower.find(end_phrase.strip().lower(), start + 1)
            if position < 0:
                return f"I could not find the end phrase '{end_phrase}' after the start point."
            end = position + len(end_phrase.strip())
        limit = max(200, min(int(max_chars), 16_000))
        excerpt = value[start:end][:limit]
        suffix = "\n[Extract truncated by NOVA.]" if len(value[start:end]) > limit else ""
        return f"Extract from {page.url}:\n\n{excerpt}{suffix}"
    except asyncio.TimeoutError:
        return "The webpage took too long to load."
    except ValueError as exc:
        return f"I could not extract text from that webpage: {exc}"
    except Exception:
        logger.exception("web_extract_text failed")
        return "I could not extract text from that webpage."


def _safe_filename_from_url(url: str, content_disposition: str) -> str:
    match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', content_disposition, re.I)
    if match:
        candidate = unquote(match.group(1)).strip()
    else:
        candidate = unquote(Path(urlparse(url).path).name) or "download.bin"
    candidate = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", candidate).strip(" .")
    if not candidate or candidate.startswith(".env"):
        candidate = "download.bin"
    return candidate[:180]


def _unique_download_path(filename: str) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = DOWNLOAD_DIR / filename
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(1, 1000):
        candidate = DOWNLOAD_DIR / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError("NOVA could not choose a unique download filename.")


def _download_sync(url: str) -> tuple[Path, int, str, str]:
    response, data = _request_public_sync(url, max_bytes=MAX_DOWNLOAD_BYTES)
    filename = _safe_filename_from_url(
        response.url,
        response.headers.get("Content-Disposition", ""),
    )
    path = _unique_download_path(filename)
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    content_type = response.headers.get("Content-Type", "unknown")
    return path, len(data), digest, content_type


@function_tool()
async def web_download(context: RunContext, url: str) -> str:
    """Download one public URL into Downloads/NOVA Downloads without executing it."""
    del context

    async def executor() -> str:
        try:
            validated = await _validate_public_url(url)
            path, size, digest, content_type = await asyncio.wait_for(
                asyncio.to_thread(_download_sync, validated),
                timeout=45,
            )
            warning = ""
            if path.suffix.lower() in {".exe", ".msi", ".bat", ".cmd", ".ps1", ".scr", ".com"}:
                warning = " The file was downloaded only; NOVA did not execute it."
            return (
                f"Downloaded to: {path}\n"
                f"Size: {size} bytes\n"
                f"Content-Type: {content_type}\n"
                f"SHA-256: {digest}.{warning}"
            )
        except asyncio.TimeoutError:
            return "The download took too long and was stopped."
        except ValueError as exc:
            return f"I could not download that URL: {exc}"
        except Exception:
            logger.exception("web_download failed")
            return "I could not download that file."

    return await permission_engine.run(
        "web_download",
        f"Download a public web resource into {DOWNLOAD_DIR}",
        executor,
        session_id="voice",
    )


WEB_RESEARCH_TOOLS = (
    web_search,
    web_search_site,
    web_read_page,
    web_find_on_page,
    web_list_links,
    web_extract_text,
    web_download,
)

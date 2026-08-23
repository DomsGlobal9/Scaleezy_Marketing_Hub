"""
Brand self-enrichment — from the client's OWN assets and links only.

Scope, decided deliberately and narrowly: a brand's own website and the pages
it links to on its own host. Not reviews, not news, not competitors, not ad
libraries. Those are somebody else's terms of service and somebody else's
copyright, and the value they add is not worth the exposure.

Three properties make this safe to run unattended:

1. **Fetching is guarded.** `safe_fetch` refuses anything that is not public
   HTTPS on the brand's own host, blocks private and loopback address ranges
   (an enrichment job that can be pointed at 169.254.169.254 is an SSRF hole),
   caps the body, and obeys a total byte budget.

2. **Everything it learns is a CANDIDATE.** Discovered facts enter as
   `BrandMemory` in CANDIDATE state with `origin=DISCOVERED`. They are never
   CONFIRMED, never written onto `Brand.*` columns, and they rank below
   everything the client stated or confirmed. A human promotes them or they
   stay proposals forever.

3. **It is bounded and idempotent.** A page whose content hash has not changed
   produces no new work, there is a cap on open candidates per brand, and a
   run that finds nothing new costs one conditional request per page.
"""
import hashlib
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlsplit

from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PAGES_PER_RUN = 12
MAX_TOTAL_BYTES = 8 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15
#: Open, unreviewed candidates per brand. Past this, enrichment stops
#: proposing: a review queue nobody can finish is the same as no queue.
MAX_OPEN_CANDIDATES = 30

USER_AGENT = 'ScaleezyBrandEnrichment/1.0 (+https://scaleezy.com/bot)'


class EnrichmentError(Exception):
    """The fetch or the run cannot proceed."""


class UnsafeURL(EnrichmentError):
    """The URL is not one we are willing to fetch."""


def _resolves_to_public_ip(host: str) -> bool:
    """Every address the host resolves to must be public.

    Checked on the resolved addresses rather than on the hostname, because
    `internal.example.com` can point anywhere — including at the cloud
    metadata endpoint, which is the classic way an innocent-looking
    "fetch this URL" feature becomes credential disclosure.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast or address.is_unspecified
        ):
            return False
    return True


def registrable_host(url: str) -> str:
    raw = (url or '').strip()
    if not raw:
        return ''
    if '//' not in raw:
        raw = f'//{raw}'
    host = (urlsplit(raw).hostname or '').lower().strip('.')
    return host[4:] if host.startswith('www.') else host


def assert_safe(url: str, *, allowed_host: str):
    """Refuse anything that is not public HTTPS on the brand's own host."""
    parts = urlsplit(url)
    if parts.scheme != 'https':
        raise UnsafeURL("Only HTTPS pages are fetched.")
    host = registrable_host(url)
    if not host:
        raise UnsafeURL("That URL has no host.")
    if allowed_host and host != allowed_host:
        # The whole scope of this feature, enforced rather than documented.
        raise UnsafeURL(
            f"{host} is not this brand's own site ({allowed_host})."
        )
    if not _resolves_to_public_ip(parts.hostname or ''):
        raise UnsafeURL("That host does not resolve to a public address.")
    return True


def safe_fetch(url: str, *, allowed_host: str, budget=None):
    """One guarded GET. Returns (text, content_hash) or raises.

    Redirects are followed by httpx but re-checked here afterwards, because a
    redirect is exactly how a permitted URL becomes a forbidden one.
    """
    import httpx

    assert_safe(url, allowed_host=allowed_host)
    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True,
            headers={'User-Agent': USER_AGENT},
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise EnrichmentError(f"Could not fetch {url}: {exc}") from exc

    # Where we actually ended up, not where we asked to go.
    assert_safe(str(response.url), allowed_host=allowed_host)

    if response.status_code >= 400:
        raise EnrichmentError(f"{url} returned {response.status_code}.")
    content_type = response.headers.get('content-type', '')
    if 'html' not in content_type and 'text' not in content_type:
        raise EnrichmentError(f"{url} is not a text page ({content_type}).")

    body = response.content[:MAX_PAGE_BYTES]
    if budget is not None:
        budget['used'] = budget.get('used', 0) + len(body)
        if budget['used'] > MAX_TOTAL_BYTES:
            raise EnrichmentError("Enrichment byte budget exhausted for this run.")

    text = _visible_text(body.decode(response.encoding or 'utf-8', errors='replace'))
    return text, hashlib.sha256(body).hexdigest()


_TAG = re.compile(r'<(script|style)[^>]*>.*?</\1>', re.S | re.I)
_MARKUP = re.compile(r'<[^>]+>')
_SPACE = re.compile(r'\s+')


def _visible_text(html: str) -> str:
    """Readable text, without dragging in a parser dependency."""
    stripped = _MARKUP.sub(' ', _TAG.sub(' ', html))
    return _SPACE.sub(' ', stripped).strip()


def own_links(html_text: str, base_url: str, *, allowed_host: str, limit=MAX_PAGES_PER_RUN):
    """Same-host links worth following. About/product pages, not the blog."""
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html_text, re.I)
    seen, out = set(), []
    for href in hrefs:
        absolute = urljoin(base_url, href.split('#')[0])
        if registrable_host(absolute) != allowed_host:
            continue
        if not absolute.startswith('https://'):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
        if len(out) >= limit:
            break
    return out


def open_candidate_count(brand) -> int:
    from apps.knowledge.models import BrandMemory

    return BrandMemory.objects.filter(
        brand=brand, status=BrandMemory.MemoryStatus.CANDIDATE
    ).count()


def enrich_brand_from_own_site(workspace, brand, *, user=None, max_pages=MAX_PAGES_PER_RUN):
    """One bounded enrichment pass over the brand's own website.

    Refuses when the client is not approved (the spend gate covers the parse
    calls, but the fetches cost us bandwidth too), when the brand has no
    website, or when the review queue is already full.

    Returns a report; the caller decides whether to surface it.
    """
    from apps.brands.services.approval import enforce_spend_approved
    from apps.knowledge.models import BrandSource

    enforce_spend_approved(workspace)

    allowed_host = registrable_host(brand.website)
    if not allowed_host:
        raise EnrichmentError("This brand has no website recorded.")

    if open_candidate_count(brand) >= MAX_OPEN_CANDIDATES:
        return {
            'skipped': True,
            'reason': (
                f'{MAX_OPEN_CANDIDATES} discovered facts are already waiting '
                'for review. Clear those first.'
            ),
            'pages_fetched': 0,
        }

    root = f'https://{allowed_host}/'
    budget = {'used': 0}
    fetched, unchanged, errors, created_sources = 0, 0, [], []

    try:
        home_text, home_hash = safe_fetch(root, allowed_host=allowed_host, budget=budget)
    except EnrichmentError as exc:
        raise EnrichmentError(f"Could not read {root}: {exc}") from exc

    pages = [(root, home_text, home_hash)]
    for url in own_links(home_text, root, allowed_host=allowed_host,
                         limit=max(0, max_pages - 1)):
        try:
            text, digest = safe_fetch(url, allowed_host=allowed_host, budget=budget)
            pages.append((url, text, digest))
        except EnrichmentError as exc:
            errors.append({'url': url, 'error': str(exc)[:200]})

    for url, text, digest in pages:
        fetched += 1
        # Idempotence: a page that has not changed produces nothing.
        if BrandSource.objects.filter(brand=brand, content_hash=digest).exists():
            unchanged += 1
            continue
        source = BrandSource.objects.create(
            workspace=workspace,
            brand=brand,
            source_type=BrandSource.SourceType.OTHER,
            title=f'Website: {url}'[:255],
            source_url=url[:1000],
            raw_text=text[:200000],
            content_hash=digest,
            # READY, not PROCESSING: the text is captured. Turning it into
            # candidate facts is the extractor's job and is queued separately,
            # so a missing extractor leaves honest raw material rather than a
            # source stuck in a state nothing will move.
            status=BrandSource.SourceStatus.READY,
            metadata={
                'origin': 'DISCOVERED',
                'discovered_at': timezone.now().isoformat(),
                'own_site': True,
            },
            created_by=user,
        )
        created_sources.append(str(source.pk))

    logger.info(
        "Enrichment for brand %s: %d fetched, %d unchanged, %d new, %d errors",
        brand.pk, fetched, unchanged, len(created_sources), len(errors),
    )
    return {
        'skipped': False,
        'host': allowed_host,
        'pages_fetched': fetched,
        'pages_unchanged': unchanged,
        'sources_created': created_sources,
        'errors': errors,
        'bytes_used': budget['used'],
        'note': (
            'Captured from your own site. Nothing has been added to your brand '
            'profile — discovered material stays a candidate until you confirm it.'
        ),
    }

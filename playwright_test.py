"""Playwright product collectors for Flipkart, Amazon India and Myntra."""

import json
import os
import re
import sys
import time
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

# ============================================================
# RENDER / PLAYWRIGHT CONFIGURATION
# ============================================================

if os.name != "nt":
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        "/opt/render/project/src/ms-playwright",
    )

import requests
from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

MAX_RESULTS = 2

# Reduced from 60. We only need enough cards to find the top 2
# relevant products and avoid spending time inspecting dozens of links.
FLIPKART_MAX_LINKS = 15
AMAZON_MAX_CARDS = 25

PAGE_TIMEOUT_MS = 25000

# Reduced from 1500 ms. domcontentloaded already waits for the page
# document; a short settling delay is enough for the product cards.
WAIT_AFTER_LOAD_MS = 500


# ============================================================
# SEARCH HELPERS
# ============================================================

GENERIC_SEARCH_TERMS = {
    "and",
    "bluetooth",
    "earbud",
    "earbuds",
    "earphone",
    "earphones",
    "headphone",
    "headphones",
    "phone",
    "phones",
    "smartphone",
    "smartphones",
    "tws",
    "wireless",
    "for",
    "the",
    "with",
    "of",
}


def _search_tokens(text: str) -> list[str]:
    text = str(text or "").lower()

    text = text.replace("u.s.", "us")
    text = text.replace("u.s", "us")
    text = text.replace("u s", "us")

    text = re.sub(r"\bmen['’]s\b", "men", text)
    text = re.sub(r"\bwomen['’]s\b", "women", text)

    text = re.sub(r"[^a-z0-9]+", " ", text)

    tokens = []

    for token in text.split():

        if not token:
            continue

        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"

        elif len(token) > 4 and token.endswith(
            ("ches", "shes", "xes", "zes", "ses")
        ):
            token = token[:-2]

        elif len(token) > 4 and token.endswith("s"):
            token = token[:-1]

        tokens.append(token)

    return tokens


def _normalized_product_name(name: str) -> str:
    return " ".join(_search_tokens(name))


def _token_matches(
    query_token: str,
    name_tokens: set[str],
) -> bool:

    if query_token in name_tokens:
        return True

    gender_aliases = {
        "men": {"men", "mens", "male", "man"},
        "women": {"women", "womens", "female", "woman"},
    }

    if query_token in gender_aliases:

        if name_tokens & gender_aliases[query_token]:
            return True

    for name_token in name_tokens:

        if (
            len(query_token) >= 4
            and name_token.startswith(query_token)
        ):
            return True

        if (
            len(name_token) >= 4
            and query_token.startswith(name_token)
        ):
            return True

    return False


# ============================================================
# RANKING
# ============================================================

def _rank_results(
    search_term: str,
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:

    query_tokens = _search_tokens(search_term)

    search_keywords = [
        token
        for token in query_tokens
        if token not in GENERIC_SEARCH_TERMS
    ]

    if not search_keywords:
        search_keywords = query_tokens

    ranked = []

    for position, result in enumerate(candidates):

        product_name = result.get(
            "product_name",
            "",
        )

        name_tokens = set(
            _search_tokens(product_name)
        )

        if not name_tokens:
            continue

        matched_keywords = 0
        score = 0

        for query_token in search_keywords:

            if _token_matches(
                query_token,
                name_tokens,
            ):

                matched_keywords += 1

                if query_token in name_tokens:
                    score += 100
                else:
                    score += 70

        if matched_keywords == 0:
            continue

        score += matched_keywords * 1000

        # Strongly prefer products matching all meaningful words.
        if matched_keywords == len(search_keywords):
            score += 10000

        score -= position

        ranked.append(
            (
                score,
                -position,
                result,
            )
        )

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
        ),
        reverse=True,
    )

    results = []
    seen_names = set()

    for _, _, result in ranked:

        normalized_name = _normalized_product_name(
            result.get(
                "product_name",
                "",
            )
        )

        if not normalized_name:
            continue

        if normalized_name in seen_names:
            continue

        seen_names.add(normalized_name)

        results.append(result)

        if len(results) >= MAX_RESULTS:
            break

    return results


def _fallback_results(
    search_term: str,
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:

    important_tokens = {
        token
        for token in _search_tokens(search_term)
        if token not in GENERIC_SEARCH_TERMS
    }

    if not important_tokens:
        important_tokens = set(
            _search_tokens(search_term)
        )

    fallback = []

    for position, candidate in enumerate(candidates):

        name_tokens = set(
            _search_tokens(
                candidate.get(
                    "product_name",
                    "",
                )
            )
        )

        if not name_tokens:
            continue

        if all(
            _token_matches(
                query_token,
                name_tokens,
            )
            for query_token in important_tokens
        ):

            fallback.append(
                (
                    -position,
                    candidate,
                )
            )

    fallback.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        candidate
        for _, candidate in fallback
    ]


# ============================================================
# COMMON HELPERS
# ============================================================

def _clean_text(text: str) -> str:
    return " ".join(
        str(text or "").split()
    )


def _extract_price(text: str) -> str:

    if not text:
        return "Not displayed"

    # Handles:
    # ₹1,299
    # ₹ 1,299
    # ₹1,299.00
    match = re.search(
        r"₹\s*[\d,]+(?:\.\d{1,2})?",
        text,
    )

    if not match:
        return "Not displayed"

    return (
        match.group()
        .replace("₹ ", "₹")
        .strip()
    )


def _launch_browser(playwright):

    print(
        "[PLAYWRIGHT] Browsers path = "
        + os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH",
            "default",
        ),
        flush=True,
    )

    return playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-features=Translate,BackForwardCache",
        ],
    )


def _new_page(browser):

    context = browser.new_context(
        viewport={
            "width": 1280,
            "height": 720,
        },
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 "
            "Safari/537.36"
        ),
        locale="en-IN",
    )

    page = context.new_page()

    page.set_default_timeout(
        6000
    )

    return context, page


def _raise_if_restricted(page):

    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=3000
        ).lower()

    except Exception:

        return

    if re.search(
        r"captcha|robot check|"
        r"enter the characters you see below|"
        r"access denied|unusual traffic",
        text,
    ):

        raise RuntimeError(
            "The storefront presented an access restriction; "
            "no bypass was attempted."
        )


# ============================================================
# FLIPKART
# ============================================================

def _extract_product_name(text: str) -> str:

    rating_pattern = re.compile(
        r"^\s*"
        r"\d(?:\.\d)?"
        r"\s*"
        r"(?:"
        r"\([\d,]+\)"
        r"|"
        r"[\d,]+\s+ratings?\s*&\s*[\d,]+\s+reviews?"
        r")"
        r"\s*$",
        re.IGNORECASE,
    )

    offer_pattern = re.compile(
        r"^(?:"
        r"bank offer"
        r"|hot deal"
        r"|only few left"
        r"|upto\s+.*"
        r"|.*\d+%\s+off.*"
        r"|.*exchange.*"
        r")$",
        re.IGNORECASE,
    )

    specification_pattern = re.compile(
        r"^\s*"
        r"\d+(?:\.\d+)?\s*"
        r"(?:gb|tb|mp|mah|inch|inches|cm)"
        r".*$"
        r"|"
        r"^\s*\d+\s*gb\s+(?:ram|rom).*$",
        re.IGNORECASE,
    )

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        lower = line.lower()

        if lower in {
            "add to compare",
            "currently unavailable",
            "out of stock",
            "add to cart",
            "buy now",
        }:
            continue

        if line.startswith("₹"):
            continue

        if rating_pattern.match(line):
            continue

        if offer_pattern.match(line):
            continue

        if specification_pattern.match(line):
            continue

        return line

    return "Not displayed"


def _flipkart_card(link):

    """
    Fast Flipkart card lookup.

    Instead of trying several ancestors with long individual
    timeouts, use the first product-card ancestor directly.
    """

    try:

        card = link.locator(
            "xpath=ancestor::div[.//a[contains(@href,'/p/')]][1]"
        )

        text = card.inner_text(
            timeout=700
        )

        if text:
            return card

    except Exception:
        pass

    return link


def _flipkart_extract_card(
    link,
) -> dict[str, str] | None:

    try:

        if not link.is_visible(
            timeout=300
        ):
            return None

        href = (
            link.get_attribute(
                "href"
            )
            or ""
        )

        link_text = _clean_text(
            link.inner_text(
                timeout=700
            )
        )

    except Exception:

        return None

    if not href or not link_text:
        return None

    path = href.split(
        "?",
        1,
    )[0]

    if "/p/" not in path:
        return None

    card = _flipkart_card(
        link
    )

    try:

        card_text = card.inner_text(
            timeout=700
        )

    except Exception:

        card_text = link_text

    # Sometimes the card itself doesn't expose all text.
    # Combine link + card text so price isn't lost.
    rendered = (
        card_text
        + "\n"
        + link_text
    )

    product_name = _extract_product_name(
        link_text
    )

    if product_name == "Not displayed":

        product_name = _extract_product_name(
            card_text
        )

    if product_name == "Not displayed":
        return None

    rating_match = re.search(
        r"(?m)^\s*"
        r"(\d(?:\.\d)?)"
        r"\s*"
        r"(?:"
        r"\(([\d,]+)\)"
        r"|"
        r"([\d,]+)\s+Ratings?\s*&\s*"
        r"([\d,]+)\s+Reviews?"
        r")"
        r"\s*$",
        rendered,
        re.IGNORECASE,
    )

    rating = (
        rating_match.group(1)
        if rating_match
        else "Not displayed"
    )

    review_count = "Not displayed"

    if rating_match:

        review_count = (
            rating_match.group(4)
            or rating_match.group(2)
            or "Not displayed"
        )

    price = _extract_price(
        rendered
    )

    return {
        "product_name": product_name,
        "product_url": urljoin(
            "https://www.flipkart.com",
            path,
        ),
        "current_selling_price": price,
        "rating": rating,
        "review_count": review_count,
    }


def main(
    search_term: str,
) -> list[dict[str, str]]:

    print(
        f"[FLIPKART] Starting search: {search_term}",
        flush=True,
    )

    with sync_playwright() as playwright:

        browser = _launch_browser(
            playwright
        )

        context = None

        try:

            context, page = _new_page(
                browser
            )

            search_url = (
                "https://www.flipkart.com/search?q="
                f"{quote_plus(search_term)}"
            )

            print(
                f"[FLIPKART] URL: {search_url}",
                flush=True,
            )

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )

            page.wait_for_timeout(
                WAIT_AFTER_LOAD_MS
            )

            _raise_if_restricted(
                page
            )

            links = page.locator(
                'a[href*="/p/"]'
            )

            total_links = links.count()

            inspect_count = min(
                total_links,
                FLIPKART_MAX_LINKS,
            )

            print(
                "[FLIPKART] Product links found: "
                f"{total_links}",
                flush=True,
            )

            print(
                "[FLIPKART] Inspecting: "
                f"{inspect_count}",
                flush=True,
            )

            candidates = []
            seen_urls = set()

            for index in range(
                inspect_count
            ):

                result = _flipkart_extract_card(
                    links.nth(index)
                )

                if not result:
                    continue

                product_url = result[
                    "product_url"
                ]

                if product_url in seen_urls:
                    continue

                seen_urls.add(
                    product_url
                )

                candidates.append(
                    result
                )

            print(
                "[FLIPKART] Extracted candidates: "
                f"{len(candidates)}",
                flush=True,
            )

            results = _rank_results(
                search_term,
                candidates,
            )

            if len(results) < MAX_RESULTS:

                fallback = _fallback_results(
                    search_term,
                    candidates,
                )

                existing_urls = {
                    result.get(
                        "product_url"
                    )
                    for result in results
                }

                for candidate in fallback:

                    candidate_url = candidate.get(
                        "product_url"
                    )

                    if candidate_url in existing_urls:
                        continue

                    results.append(
                        candidate
                    )

                    existing_urls.add(
                        candidate_url
                    )

                    if len(results) >= MAX_RESULTS:
                        break

            if not results:

                raise RuntimeError(
                    "No visible relevant Flipkart "
                    "product was found."
                )

            results = results[
                :MAX_RESULTS
            ]

            print(
                "[FLIPKART] Found "
                f"{len(results)} products",
                flush=True,
            )

            for number, result in enumerate(
                results,
                start=1,
            ):

                print(
                    f"[FLIPKART] Product {number}: "
                    f"{result['product_name']} | "
                    f"{result['current_selling_price']}",
                    flush=True,
                )

            return results

        except Exception as error:

            print(
                f"[FLIPKART] ERROR: {error!r}",
                flush=True,
            )

            raise

        finally:

            if context is not None:

                try:
                    context.close()
                except Exception:
                    pass

            try:
                browser.close()

            except Exception:
                pass


# ============================================================
# AMAZON
# ============================================================

def _amazon_product_url(
    href: str,
) -> str | None:

    if not href:
        return None

    parsed = urlparse(
        href
    )

    if "/sspa/click" in parsed.path:

        href = unquote(
            parse_qs(
                parsed.query
            ).get(
                "url",
                [""],
            )[0]
        )

    match = re.search(
        r"(/[^?#]*/dp/[A-Z0-9]{10})(?:/|$)",
        href,
        re.IGNORECASE,
    )

    if not match:

        match = re.search(
            r"(/dp/[A-Z0-9]{10})(?:/|$)",
            href,
            re.IGNORECASE,
        )

    if not match:
        return None

    return urljoin(
        "https://www.amazon.in",
        match.group(1),
    )


def _amazon_relevance_name(
    title: str,
) -> str:

    identity = " ".join(
        title.split()
    ).split(
        ":",
        1,
    )[0]

    identity = re.sub(
        r"\s+\d+\s*(?:GB|TB)\s*$",
        "",
        identity,
        flags=re.IGNORECASE,
    )

    return identity.strip(
        " ,|-"
    )


def _amazon_title_link(card):

    selectors = (
        'a[href*="/dp/"] h2',
        'a[href*="/sspa/click"] h2',
        'a.a-link-normal[href*="/dp/"]',
        'a.a-link-normal[href*="/sspa/click"]',
    )

    for selector in selectors:

        matches = card.locator(
            selector
        )

        for index in range(
            matches.count()
        ):

            element = matches.nth(
                index
            )

            try:

                text = _clean_text(
                    element.inner_text(
                        timeout=800
                    )
                )

            except Exception:

                continue

            if not text:
                continue

            if text.startswith("₹"):
                continue

            try:

                tag_name = element.evaluate(
                    "node => node.tagName"
                )

            except Exception:

                tag_name = ""

            if tag_name == "H2":

                return element.locator(
                    "xpath=ancestor::a[1]"
                )

            return element

    return None


def amazon_search(
    search_term: str,
) -> list[dict[str, str]]:

    print(
        f"[AMAZON] Starting search: {search_term}",
        flush=True,
    )

    with sync_playwright() as playwright:

        browser = _launch_browser(
            playwright
        )

        context = None

        try:

            context, page = _new_page(
                browser
            )

            search_url = (
                "https://www.amazon.in/s?k="
                f"{quote_plus(search_term)}"
            )

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=PAGE_TIMEOUT_MS,
            )

            page.wait_for_timeout(
                1800
            )

            _raise_if_restricted(
                page
            )

            cards = page.locator(
                '[data-component-type="s-search-result"]'
            )

            if cards.count() == 0:

                cards = page.locator(
                    "div.s-result-item[data-asin]"
                )

            total_cards = cards.count()

            inspect_count = min(
                total_cards,
                AMAZON_MAX_CARDS,
            )

            print(
                "[AMAZON] Search result cards: "
                f"{total_cards}",
                flush=True,
            )

            candidates = []
            seen_urls = set()

            for index in range(
                inspect_count
            ):

                card = cards.nth(
                    index
                )

                try:

                    if not card.is_visible(
                        timeout=800
                    ):
                        continue

                    title_link = _amazon_title_link(
                        card
                    )

                    if title_link is None:
                        continue

                    raw_title = _clean_text(
                        title_link.inner_text(
                            timeout=1200
                        )
                    )

                    href = (
                        title_link.get_attribute(
                            "href"
                        )
                        or ""
                    )

                except Exception:

                    continue

                if not raw_title:
                    continue

                product_identity = (
                    _amazon_relevance_name(
                        raw_title
                    )
                )

                product_url = (
                    _amazon_product_url(
                        href
                    )
                )

                if (
                    not product_identity
                    or not product_url
                    or product_url in seen_urls
                ):
                    continue

                seen_urls.add(
                    product_url
                )

                try:

                    price_element = (
                        card.locator(
                            ".a-price .a-offscreen"
                        ).first
                    )

                    price = (
                        _clean_text(
                            price_element.inner_text(
                                timeout=800
                            )
                        )
                        if price_element.count()
                        else "Not displayed"
                    )

                except Exception:

                    price = "Not displayed"

                try:

                    rating_text = _clean_text(
                        card.locator(
                            "span.a-icon-alt"
                        ).first.inner_text(
                            timeout=700
                        )
                    )

                except Exception:

                    rating_text = ""

                rating_match = re.search(
                    r"(\d(?:\.\d+)?)\s+out of",
                    rating_text,
                    re.IGNORECASE,
                )

                try:

                    review_text = _clean_text(
                        card.locator(
                            'a[href*="customerReviews"]'
                        ).first.inner_text(
                            timeout=700
                        )
                    ).strip("() ")

                except Exception:

                    review_text = ""

                candidates.append(
                    {
                        "product_name":
                            product_identity,

                        "display_name":
                            raw_title,

                        "product_url":
                            product_url,

                        "current_selling_price":
                            price,

                        "rating":
                            (
                                rating_match.group(1)
                                if rating_match
                                else "Not displayed"
                            ),

                        "review_count":
                            (
                                review_text
                                if review_text
                                else "Not displayed"
                            ),
                    }
                )

            print(
                "[AMAZON] Extracted candidates: "
                f"{len(candidates)}",
                flush=True,
            )

            results = _rank_results(
                search_term,
                candidates,
            )

            if len(results) < MAX_RESULTS:

                fallback = _fallback_results(
                    search_term,
                    candidates,
                )

                existing_urls = {
                    result.get(
                        "product_url"
                    )
                    for result in results
                }

                for candidate in fallback:

                    candidate_url = candidate.get(
                        "product_url"
                    )

                    if candidate_url in existing_urls:
                        continue

                    results.append(
                        candidate
                    )

                    existing_urls.add(
                        candidate_url
                    )

                    if len(results) >= MAX_RESULTS:
                        break

            if not results:

                raise RuntimeError(
                    "No visible relevant Amazon "
                    "product was found."
                )

            for result in results:

                result["product_name"] = (
                    result.pop(
                        "display_name",
                        result["product_name"],
                    )
                )

            return results[
                :MAX_RESULTS
            ]

        finally:

            if context is not None:

                try:
                    context.close()
                except Exception:
                    pass

            try:
                browser.close()

            except Exception:
                pass


# ============================================================
# MYNTRA
# ============================================================

def myntra_search(
    search_term: str,
) -> list[dict[str, str]]:

    print(
        f"[MYNTRA] Starting search: {search_term}",
        flush=True,
    )

    search_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        search_term.lower(),
    ).strip("-")

    encoded_term = (
        quote_plus(search_term)
        .replace("+", "%20")
    )

    search_url = (
        "https://www.myntra.com/"
        f"{search_slug}?rawQuery={encoded_term}"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 "
            "Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:

        response = requests.get(
            search_url,
            headers=headers,
            timeout=20,
        )

    except requests.RequestException as error:

        print(
            f"[MYNTRA] ERROR: {error!r}",
            flush=True,
        )

        raise RuntimeError(
            "Myntra temporarily unavailable"
        ) from error

    if response.status_code != 200:

        raise RuntimeError(
            "Myntra temporarily unavailable"
        )

    html = response.text

    marker = re.search(
        r'"products"\s*:\s*\[',
        html,
    )

    if not marker:

        raise RuntimeError(
            "No visible relevant Myntra "
            "product was found."
        )

    start = html.find(
        "[",
        marker.start(),
    )

    depth = 0
    in_string = False
    escaped = False
    end = None

    for position in range(
        start,
        len(html),
    ):

        character = html[position]

        if in_string:

            if escaped:
                escaped = False

            elif character == "\\":
                escaped = True

            elif character == '"':
                in_string = False

        elif character == '"':

            in_string = True

        elif character == "[":

            depth += 1

        elif character == "]":

            depth -= 1

            if depth == 0:

                end = position + 1

                break

    if end is None:

        raise RuntimeError(
            "No visible relevant Myntra "
            "product was found."
        )

    try:

        products = json.loads(
            html[start:end]
        )

    except json.JSONDecodeError as error:

        raise RuntimeError(
            "Myntra temporarily unavailable"
        ) from error

    candidates = []
    seen_urls = set()

    for product in products:

        if not isinstance(
            product,
            dict,
        ):
            continue

        name = str(
            product.get(
                "productName"
            )
            or product.get(
                "product"
            )
            or ""
        ).strip()

        landing_url = str(
            product.get(
                "landingPageUrl"
            )
            or ""
        ).strip()

        if not name or not landing_url:
            continue

        product_url = (
            landing_url
            if landing_url.startswith("http")
            else urljoin(
                "https://www.myntra.com/",
                landing_url,
            )
        )

        if product_url in seen_urls:
            continue

        seen_urls.add(
            product_url
        )

        price_value = (
            product.get("price")
            or product.get("mrp")
        )

        rating_value = product.get(
            "rating"
        )

        review_value = product.get(
            "ratingCount"
        )

        if (
            isinstance(
                price_value,
                (int, float),
            )
            and price_value
        ):

            price = (
                f"₹{price_value:,.0f}"
            )

        else:

            price = "Not displayed"

        if (
            isinstance(
                rating_value,
                (int, float),
            )
            and rating_value
        ):

            rating = (
                f"{float(rating_value):.1f}"
            )

        else:

            rating = "Not displayed"

        review_count = (
            str(review_value)
            if review_value is not None
            else "Not displayed"
        )

        candidates.append(
            {
                "product_name":
                    name,

                "product_url":
                    product_url,

                "current_selling_price":
                    price,

                "rating":
                    rating,

                "review_count":
                    review_count,
            }
        )

    print(
        "[MYNTRA] Extracted candidates: "
        f"{len(candidates)}",
        flush=True,
    )

    results = _rank_results(
        search_term,
        candidates,
    )

    if len(results) < MAX_RESULTS:

        fallback = _fallback_results(
            search_term,
            candidates,
        )

        existing_urls = {
            result.get(
                "product_url"
            )
            for result in results
        }

        for candidate in fallback:

            candidate_url = candidate.get(
                "product_url"
            )

            if candidate_url in existing_urls:
                continue

            results.append(
                candidate
            )

            existing_urls.add(
                candidate_url
            )

            if len(results) >= MAX_RESULTS:
                break

    if not results:

        raise RuntimeError(
            "No visible relevant Myntra "
            "product was found."
        )

    return results[
        :MAX_RESULTS
    ]


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    if (
        len(sys.argv) != 2
        or not sys.argv[1].strip()
    ):

        raise SystemExit(
            'Usage: python playwright_test.py "search term"'
        )

    term = sys.argv[1].strip()

    print("=" * 70)

    print(
        f'[TEST] SEARCH TERM: "{term}"'
    )

    print("=" * 70)

    print("\nFLIPKART:")
    print("-" * 70)

    try:

        flipkart_results = main(
            term
        )

        for result in flipkart_results:
            print(result)

    except Exception as error:

        print(
            f"Flipkart error: {error}"
        )

    print("\nAMAZON:")
    print("-" * 70)

    try:

        amazon_results = amazon_search(
            term
        )

        for result in amazon_results:
            print(result)

    except Exception as error:

        print(
            f"Amazon error: {error}"
        )

    print("\nMYNTRA:")
    print("-" * 70)

    try:

        myntra_results = myntra_search(
            term
        )

        for result in myntra_results:
            print(result)

    except Exception as error:

        print(
            f"Myntra error: {error}"
        )

    print(
        "\n" + "=" * 70
    )

    print(
        "[TEST] SEARCH COMPLETE"
    )

    print(
        "=" * 70
    )
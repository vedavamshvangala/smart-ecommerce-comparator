"""Playwright product collectors for Flipkart, Amazon India and Myntra."""

import json
import re
import sys
import time
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from playwright.sync_api import sync_playwright


# ============================================================
# SEARCH / RANKING HELPERS
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
    """Convert text into normalized search tokens."""

    text = str(text or "").lower()

    text = text.replace("u.s.", "us")
    text = text.replace("u.s", "us")
    text = text.replace("u s", "us")

    text = re.sub(r"\bmen['’]s\b", "men", text)
    text = re.sub(r"\bwomen['’]s\b", "women", text)

    text = re.sub(r"[^a-z0-9]+", " ", text)

    raw_tokens = text.split()

    tokens = []

    for token in raw_tokens:

        if not token:
            continue

        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"

        elif len(token) > 4 and token.endswith("ches"):
            token = token[:-2]

        elif len(token) > 4 and token.endswith("shes"):
            token = token[:-2]

        elif len(token) > 4 and token.endswith("xes"):
            token = token[:-2]

        elif len(token) > 4 and token.endswith("zes"):
            token = token[:-2]

        elif len(token) > 4 and token.endswith("ses"):
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

    gender_aliases = {
        "men": {"men", "mens", "male", "man"},
        "mens": {"men", "mens", "male", "man"},
        "male": {"men", "mens", "male", "man"},
        "man": {"men", "mens", "male", "man"},

        "women": {"women", "womens", "female", "woman"},
        "womens": {"women", "womens", "female", "woman"},
        "female": {"women", "womens", "female", "woman"},
        "woman": {"women", "womens", "female", "woman"},
    }

    all_gender_tokens = {
        "men",
        "mens",
        "male",
        "man",
        "women",
        "womens",
        "female",
        "woman",
    }

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

        score = 0
        matched_keywords = 0

        product_gender_tokens = (
            name_tokens & all_gender_tokens
        )

        for query_token in search_keywords:

            if query_token in gender_aliases:

                if product_gender_tokens:

                    if any(
                        gender in gender_aliases[query_token]
                        for gender in product_gender_tokens
                    ):
                        matched_keywords += 1
                        score += 100
                    else:
                        continue

                else:
                    continue

                continue

            if query_token in name_tokens:

                matched_keywords += 1
                score += 100
                continue

            matching_tokens = [
                name_token
                for name_token in name_tokens
                if (
                    len(query_token) >= 4
                    and name_token.startswith(query_token)
                )
                or (
                    len(name_token) >= 4
                    and query_token.startswith(name_token)
                )
            ]

            if matching_tokens:

                matched_keywords += 1
                score += 70

                score += max(
                    len(token)
                    for token in matching_tokens
                )

        if not search_keywords:
            continue

        if matched_keywords == 0:
            continue

        coverage_score = matched_keywords * 1000

        score += coverage_score

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

        if len(results) == 2:
            break

    return results


# ============================================================
# COMMON PLAYWRIGHT HELPERS
# ============================================================

def _launch_browser(playwright):

    return playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )


def _raise_if_restricted(page) -> None:

    try:
        text = page.locator(
            "body"
        ).inner_text().lower()
    except Exception:
        return

    if re.search(
        r"captcha|robot check|"
        r"enter the characters you see below|"
        r"access denied|"
        r"unusual traffic",
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
        r"^\s*\d(?:\.\d)?\s*"
        r"(?:[\d,]+\s+ratings?\s*&\s*"
        r"[\d,]+\s+reviews?|\([\d,]+\))"
        r"\s*$",
        re.IGNORECASE,
    )

    offer_pattern = re.compile(
        r"^(?:bank offer|hot deal|only few left|"
        r"upto\s+.*|.*\d+%\s+off.*|.*exchange.*)$",
        re.IGNORECASE,
    )

    specification_pattern = re.compile(
        r"^\s*\d+(?:\.\d+)?\s*"
        r"(?:gb|tb|mp|mah|inch|inches|cm)\s*$|"
        r"^\s*\d+\s*gb\s+"
        r"(?:ram|rom).*$",
        re.IGNORECASE,
    )

    for raw_line in text.splitlines():

        line = raw_line.strip()
        lower = line.lower()

        if not line:
            continue

        if lower in {
            "add to compare",
            "currently unavailable",
            "out of stock",
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


def _flipkart_fallback_results(
    search_term: str,
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:

    """
    Fallback ranking for Flipkart.

    The normal ranking can occasionally return only one result
    because Flipkart's rendered text varies between page loads.

    This fallback requires the important search terms to match,
    but does not require every generic word such as "for".
    """

    query_tokens = _search_tokens(search_term)

    important_tokens = {
        token
        for token in query_tokens
        if token not in GENERIC_SEARCH_TERMS
    }

    if not important_tokens:
        important_tokens = set(query_tokens)

    fallback = []

    for position, candidate in enumerate(candidates):

        product_name = candidate.get(
            "product_name",
            "",
        )

        name_tokens = set(
            _search_tokens(product_name)
        )

        if not name_tokens:
            continue

        matched = 0

        for query_token in important_tokens:

            if _token_matches(
                query_token,
                name_tokens,
            ):
                matched += 1

        if matched == len(important_tokens):

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


def main(
    search_term: str,
) -> list[dict[str, str]]:
    """
    Collect up to two relevant Flipkart products.
    """

    print(
        f"[FLIPKART] Starting search: {search_term}",
        flush=True,
    )

    with sync_playwright() as playwright:

        browser = _launch_browser(playwright)
        page = browser.new_page()

        try:

            search_url = (
                "https://www.flipkart.com/search?q="
                f"{quote_plus(search_term)}"
            )

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            page.wait_for_timeout(1500)

            _raise_if_restricted(page)

            links = page.locator(
                'a[href*="/p/"]'
            )

            candidates = []
            seen_urls = set()

            count = links.count()

            print(
                f"[FLIPKART] Product links found: {count}",
                flush=True,
            )

            for index in range(count):

                link = links.nth(index)

                try:
                    if not link.is_visible():
                        continue
                except Exception:
                    continue

                try:
                    text = link.inner_text().strip()
                except Exception:
                    continue

                href = link.get_attribute(
                    "href"
                )

                if not text or not href:
                    continue

                if text.startswith("₹"):
                    continue

                path = href.split(
                    "?",
                    1,
                )[0]

                if path in seen_urls:
                    continue

                seen_urls.add(path)

                try:

                    parent_text = (
                        link
                        .locator("xpath=..")
                        .inner_text()
                    )

                except Exception:

                    parent_text = ""

                rendered = (
                    f"{parent_text}\n{text}"
                )

                # --------------------------------------------
                # PRICE
                # --------------------------------------------

                price_match = re.search(
                    r"₹[\d,]+",
                    rendered,
                )

                # --------------------------------------------
                # RATING / REVIEWS
                # --------------------------------------------

                match = re.search(
                    r"^\s*(\d(?:\.\d)?)\s*"
                    r"([\d,]+)\s+Ratings?\s*&\s*"
                    r"([\d,]+)\s+Reviews?\s*$",
                    rendered,
                    re.IGNORECASE |
                    re.MULTILINE,
                )

                if not match:

                    match = re.search(
                        r"(?m)^\s*(\d(?:\.\d)?)\s*"
                        r"\(([\d,]+)\)\s*$",
                        rendered,
                    )

                candidate = {
                    "product_name":
                        _extract_product_name(text),

                    "product_url":
                        urljoin(
                            "https://www.flipkart.com",
                            path,
                        ),

                    "current_selling_price":
                        (
                            price_match.group()
                            if price_match
                            else "Not displayed"
                        ),

                    "rating":
                        (
                            match.group(1)
                            if match
                            else "Not displayed"
                        ),

                    "review_count":
                        (
                            match.group(3)
                            if match and match.lastindex == 3
                            else (
                                match.group(2)
                                if match
                                else "Not displayed"
                            )
                        ),
                }

                # Only retain useful product names.
                if (
                    candidate["product_name"]
                    and candidate["product_name"]
                    != "Not displayed"
                ):

                    candidates.append(candidate)

            print(
                f"[FLIPKART] Extracted "
                f"{len(candidates)} candidates",
                flush=True,
            )

            # ------------------------------------------------
            # NORMAL RANKING
            # ------------------------------------------------

            results = _rank_results(
                search_term,
                candidates,
            )

            # ------------------------------------------------
            # FALLBACK
            #
            # If normal ranking gives fewer than two products,
            # use the Flipkart-specific fallback.
            # ------------------------------------------------

            if len(results) < 2:

                fallback_results = (
                    _flipkart_fallback_results(
                        search_term,
                        candidates,
                    )
                )

                existing_urls = {
                    result.get("product_url")
                    for result in results
                }

                for candidate in fallback_results:

                    candidate_url = candidate.get(
                        "product_url"
                    )

                    if candidate_url in existing_urls:
                        continue

                    results.append(candidate)

                    existing_urls.add(
                        candidate_url
                    )

                    if len(results) >= 2:
                        break

            # ------------------------------------------------
            # FINAL FALLBACK
            #
            # If Flipkart has candidates but the relevance
            # matcher was too strict, use the first two
            # actual visible product candidates.
            #
            # This is deliberately only used when we have
            # candidates and normal matching produced fewer
            # than two.
            # ------------------------------------------------

            if len(results) < 2:

                existing_urls = {
                    result.get("product_url")
                    for result in results
                }

                for candidate in candidates:

                    candidate_url = candidate.get(
                        "product_url"
                    )

                    if candidate_url in existing_urls:
                        continue

                    results.append(candidate)

                    existing_urls.add(
                        candidate_url
                    )

                    if len(results) >= 2:
                        break

            if not results:

                raise RuntimeError(
                    "No visible relevant Flipkart "
                    "product was found."
                )

            results = results[:2]

            print(
                f"[FLIPKART] Found {len(results)} products",
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

            browser.close()


# ============================================================
# AMAZON
# ============================================================

def _amazon_product_url(
    href: str,
) -> str | None:

    if not href:
        return None

    parsed = urlparse(href)

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

            element = matches.nth(index)

            try:

                text = " ".join(
                    element.inner_text().split()
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

    product_links = card.locator(
        'a[href*="/dp/"], '
        'a[href*="/sspa/click"]'
    )

    candidates = []

    for index in range(
        product_links.count()
    ):

        link = product_links.nth(index)

        href = (
            link.get_attribute("href")
            or ""
        )

        try:

            text = " ".join(
                link.inner_text().split()
            )

        except Exception:

            continue

        if not text:
            continue

        if text.startswith("₹"):
            continue

        if "customerReviews" in href:
            continue

        candidates.append(
            (
                len(text),
                link,
            )
        )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: item[0],
    )[1]


def amazon_search(
    search_term: str,
) -> list[dict[str, str]]:

    print(
        f"[AMAZON] Starting search: {search_term}",
        flush=True,
    )

    with sync_playwright() as playwright:

        browser = _launch_browser(playwright)
        page = browser.new_page()

        try:

            search_url = (
                "https://www.amazon.in/s?k="
                f"{quote_plus(search_term)}"
            )

            cards = None
            usable = False

            for attempt in range(3):

                try:

                    page.goto(
                        search_url,
                        wait_until="commit",
                        timeout=30000,
                    )

                    page.wait_for_timeout(2500)

                except Exception as error:

                    print(
                        f"[AMAZON] Navigation attempt "
                        f"{attempt + 1} failed: {error}",
                        flush=True,
                    )

                    if attempt == 2:
                        raise

                    time.sleep(2)
                    continue

                _raise_if_restricted(page)

                cards = page.locator(
                    '[data-component-type="s-search-result"]'
                )

                card_count = cards.count()

                print(
                    f"[AMAZON] Search result cards: "
                    f"{card_count}",
                    flush=True,
                )

                usable = False

                for index in range(
                    card_count
                ):

                    card = cards.nth(index)

                    try:

                        if not card.is_visible():
                            continue

                        title_link = _amazon_title_link(
                            card
                        )

                        if title_link is not None:

                            usable = True
                            break

                    except Exception:

                        continue

                if usable:
                    break

                if attempt < 2:
                    time.sleep(2)

            if cards is None or not usable:

                alternative_cards = page.locator(
                    "div.s-result-item[data-asin]"
                )

                if alternative_cards.count() > 0:

                    print(
                        "[AMAZON] Using alternative "
                        "result-card selector",
                        flush=True,
                    )

                    cards = alternative_cards

                    usable = False

                    for index in range(
                        cards.count()
                    ):

                        card = cards.nth(index)

                        try:

                            if not card.is_visible():
                                continue

                            title_link = _amazon_title_link(
                                card
                            )

                            if title_link is not None:

                                usable = True
                                break

                        except Exception:

                            continue

            if cards is None or not usable:

                raise RuntimeError(
                    "No visible relevant Amazon "
                    "product was found."
                )

            candidates = []
            seen_urls = set()

            for index in range(
                cards.count()
            ):

                card = cards.nth(index)

                try:

                    if not card.is_visible():
                        continue

                except Exception:

                    continue

                title_link = _amazon_title_link(
                    card
                )

                if title_link is None:
                    continue

                try:

                    raw_title = " ".join(
                        title_link.inner_text().split()
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

                try:

                    href = (
                        title_link.get_attribute(
                            "href"
                        )
                        or ""
                    )

                except Exception:

                    href = ""

                product_url = _amazon_product_url(
                    href
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

                price_element = card.locator(
                    ".a-price .a-offscreen"
                ).first

                rating_element = card.locator(
                    "span.a-icon-alt"
                ).first

                review_element = card.locator(
                    'a[href*="customerReviews"]'
                ).first

                try:

                    price = (
                        price_element
                        .inner_text()
                        .strip()
                        if price_element.count()
                        else "Not displayed"
                    )

                except Exception:

                    price = "Not displayed"

                try:

                    rating_text = (
                        rating_element
                        .inner_text()
                        .strip()
                        if rating_element.count()
                        else ""
                    )

                except Exception:

                    rating_text = ""

                rating_match = re.search(
                    r"(\d(?:\.\d+)?)\s+out of",
                    rating_text,
                    re.IGNORECASE,
                )

                try:

                    review_text = (
                        review_element
                        .inner_text()
                        .strip("() ")
                        if review_element.count()
                        else ""
                    )

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
                f"[AMAZON] Extracted "
                f"{len(candidates)} candidates",
                flush=True,
            )

            results = _rank_results(
                search_term,
                candidates,
            )

            if not results:

                raise RuntimeError(
                    "No visible relevant Amazon "
                    "product was found."
                )

            for result in results:

                result["product_name"] = result.pop(
                    "display_name",
                    result["product_name"],
                )

            print(
                f"[AMAZON] Found {len(results)} products",
                flush=True,
            )

            return results

        except Exception as error:

            print(
                f"[AMAZON] ERROR: {error!r}",
                flush=True,
            )

            raise

        finally:

            browser.close()


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
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    import requests

    try:

        response = requests.get(
            search_url,
            headers=headers,
            timeout=30,
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

        if not isinstance(product, dict):
            continue

        name = str(
            product.get("productName")
            or product.get("product")
            or ""
        ).strip()

        landing_url = str(
            product.get("landingPageUrl")
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

    results = _rank_results(
        search_term,
        candidates,
    )

    if not results:

        raise RuntimeError(
            "No visible relevant Myntra "
            "product was found."
        )

    print(
        f"[MYNTRA] Found {len(results)} products",
        flush=True,
    )

    return results


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
    print(f'[TEST] SEARCH TERM: "{term}"')
    print("=" * 70)

    print("\nFLIPKART:")
    print("-" * 70)

    try:

        flipkart_results = main(term)

        for result in flipkart_results:
            print(result)

    except Exception as error:

        print(
            f"Flipkart error: {error}"
        )

    print("\nAMAZON:")
    print("-" * 70)

    try:

        amazon_results = amazon_search(term)

        for result in amazon_results:
            print(result)

    except Exception as error:

        print(
            f"Amazon error: {error}"
        )

    print("\nMYNTRA:")
    print("-" * 70)

    try:

        myntra_results = myntra_search(term)

        for result in myntra_results:
            print(result)

    except Exception as error:

        print(
            f"Myntra error: {error}"
        )

    print("\n" + "=" * 70)
    print("[TEST] SEARCH COMPLETE")
    print("=" * 70)
    
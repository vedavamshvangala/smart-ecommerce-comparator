"""Playwright product collectors for Flipkart and Amazon India."""

import re
import sys
import time
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from playwright.sync_api import sync_playwright

GENERIC_SEARCH_TERMS = {
    "and", "bluetooth", "earbud", "earbuds", "earphone", "earphones",
    "headphone", "headphones", "phone", "phones", "smartphone",
    "smartphones", "tws", "wireless","for","the","and","with","of",
}


def _search_tokens(text: str) -> list[str]:
    """
    Convert search/product text into normalized keyword tokens.

    Examples:
        "Nike Men's Shoes"       -> ["nike", "men", "shoe"]
        "Nike shoes for men"     -> ["nike", "shoe", "men"]
        "U.S. Polo Assn."        -> ["us", "polo", "assn"]
        "kurtis for women"       -> ["kurti", "women"]
    """

    text = str(text or "").lower()

    # ---------------------------------------------------------
    # Normalize brand/punctuation variations
    # ---------------------------------------------------------

    text = text.replace("u.s.", "us")
    text = text.replace("u.s", "us")
    text = text.replace("u s", "us")

    # ---------------------------------------------------------
    # Normalize possessives
    # ---------------------------------------------------------

    text = re.sub(
        r"\bmen['’]s\b",
        "men",
        text
    )

    text = re.sub(
        r"\bwomen['’]s\b",
        "women",
        text
    )

    # ---------------------------------------------------------
    # Treat punctuation as separators
    # ---------------------------------------------------------

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text
    )

    raw_tokens = text.split()

    tokens = []

    for token in raw_tokens:

        if not token:
            continue

        # -----------------------------------------------------
        # Normalize common plural forms.
        #
        # This allows:
        # shoe <-> shoes
        # shirt <-> shirts
        # kurti <-> kurtis
        # watch <-> watches
        # -----------------------------------------------------

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

    # Exact match.
    if query_token in name_tokens:
        return True

    # Gender aliases.
    gender_aliases = {
        "men": {"men", "mens", "male", "man"},
        "women": {"women", "womens", "female", "woman"},
    }

    if query_token in gender_aliases:
        if name_tokens & gender_aliases[query_token]:
            return True

    # Prefix matching.
    for name_token in name_tokens:

        # Query -> product prefix.
        if (
            len(query_token) >= 4
            and name_token.startswith(query_token)
        ):
            return True

        # Product -> query prefix.
        if (
            len(name_token) >= 4
            and query_token.startswith(name_token)
        ):
            return True

    return False

def _rank_results(
    search_term: str,
    candidates: list[dict[str, str]]
) -> list[dict[str, str]]:

    query_tokens = _search_tokens(search_term)

    # Remove stop/generic words.
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
        "men", "mens", "male", "man",
        "women", "womens", "female", "woman"
    }

    ranked = []

    for position, result in enumerate(candidates):

        product_name = result.get("product_name", "")

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

        # -------------------------------------------------
        # Match SEARCH keywords against PRODUCT keywords.
        #
        # IMPORTANT:
        # We only care about the user's search keywords.
        # Extra words in the product name are allowed.
        # -------------------------------------------------

        for query_token in search_keywords:

            # -----------------------------
            # Gender
            # -----------------------------

            if query_token in gender_aliases:

                if product_gender_tokens:

                    if any(
                        gender in gender_aliases[query_token]
                        for gender in product_gender_tokens
                    ):
                        matched_keywords += 1
                        score += 100
                    else:
                        # Explicit opposite gender.
                        continue

                else:
                    # Product doesn't specify gender.
                    # Allow it.
                    continue

                continue

            # -----------------------------
            # Exact token
            # -----------------------------

            if query_token in name_tokens:

                matched_keywords += 1

                # Exact match gets highest priority.
                score += 100

                continue

            # -----------------------------
            # Prefix / singular-plural match
            # -----------------------------

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

                # Partial match.
                score += 70

                # Prefer longer matching words.
                score += max(
                    len(token)
                    for token in matching_tokens
                )

                continue

            # -------------------------------------------------
            # IMPORTANT:
            # DO NOT reject the product.
            #
            # The product can contain extra words and the
            # search can contain words that aren't explicitly
            # present because of naming differences.
            # -------------------------------------------------

        # -------------------------------------------------
        # Product must match at least ONE meaningful keyword.
        # -------------------------------------------------

        if not search_keywords:
            continue

        if matched_keywords == 0:
            continue

        # -------------------------------------------------
        # Strong priority for keyword coverage.
        #
        # Products matching MORE search keywords rank higher.
        # -------------------------------------------------

        coverage_score = (
            matched_keywords * 1000
        )

        score += coverage_score

        # Small position tie-breaker.
        score -= position

        ranked.append(
            (
                score,
                -position,
                result
            )
        )

    # Highest score first.
    ranked.sort(
        key=lambda item: (item[0], item[1]),
        reverse=True
    )

    # -------------------------------------------------
    # Remove duplicate product names.
    # -------------------------------------------------

    results = []
    seen_names = set()

    for _, _, result in ranked:

        normalized_name = _normalized_product_name(
            result.get("product_name", "")
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

def _raise_if_restricted(page) -> None:
    text = page.locator("body").inner_text().lower()
    if re.search(
        r"captcha|robot check|enter the characters you see below|access denied|unusual traffic",
        text,
    ):
        raise RuntimeError("The storefront presented an access restriction; no bypass was attempted.")


def _extract_product_name(text: str) -> str:
    rating_pattern = re.compile(
        r"^\s*\d(?:\.\d)?\s*(?:[\d,]+\s+ratings?.*&\s*[\d,]+\s+reviews?|\([\d,]+\))\s*$",
        re.IGNORECASE,
    )
    offer_pattern = re.compile(
        r"^(?:bank offer|hot deal|only few left|upto\s+.*|.*\d+%\s+off.*|.*exchange.*)$",
        re.IGNORECASE,
    )
    specification_pattern = re.compile(
        r"^\s*\d+(?:\.\d+)?\s*(?:gb|tb|mp|mah|inch|inches|cm)\s*$|"
        r"^\s*\d+\s*gb\s+(?:ram|rom).*$",
        re.IGNORECASE,
    )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line or lower in {"add to compare", "currently unavailable", "out of stock"}:
            continue
        if line.startswith("₹") or rating_pattern.match(line):
            continue
        if offer_pattern.match(line) or specification_pattern.match(line):
            continue
        return line
    return "Not displayed"


def main(search_term: str) -> list[dict[str, str]]:
    """Collect up to two relevant Flipkart products."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f"https://www.flipkart.com/search?q={quote_plus(search_term)}", wait_until="domcontentloaded", timeout=30000)
            _raise_if_restricted(page)
            links = page.locator('a[href*="/p/"]')
            candidates = []
            seen_urls = set()
            for index in range(links.count()):
                link = links.nth(index)
                if not link.is_visible():
                    continue
                text = link.inner_text().strip()
                href = link.get_attribute("href")
                if not text or not href or text.startswith("₹"):
                    continue
                path = href.split("?", 1)[0]
                if path in seen_urls:
                    continue
                seen_urls.add(path)
                rendered = f"{link.locator('xpath=..').inner_text()}\n{text}"
                rating_element = link.locator("span").filter(has_text="Ratings").first
                rating_text = rating_element.locator("xpath=..").inner_text() if rating_element.count() else rendered
                match = re.search(r"^\s*(\d(?:\.\d)?)([\d,]+)\s+Ratings?\s*&\s*([\d,]+)\s+Reviews?\s*$", rating_text)
                if not match:
                    match = re.search(r"(?m)^\s*(\d(?:\.\d)?)\s*\(([\d,]+)\)\s*$", rating_text)
                price_match = re.search(r"₹[\d,]+", rendered)
                candidates.append({
                    "product_name": _extract_product_name(text),
                    "product_url": urljoin("https://www.flipkart.com", path),
                    "current_selling_price": price_match.group() if price_match else "Not displayed",
                    "rating": match.group(1) if match else "Not displayed",
                    "review_count": match.group(3) if match and match.lastindex == 3 else match.group(2) if match else "Not displayed",
                })
            results = _rank_results(search_term, candidates)
            if not results:
                raise RuntimeError("No visible relevant Flipkart product was found.")
            return results
        finally:
            browser.close()


def _amazon_product_url(href: str) -> str | None:
    parsed = urlparse(href)
    if "/sspa/click" in parsed.path:
        href = unquote(parse_qs(parsed.query).get("url", [""])[0])
    match = re.search(r"(/[^?#]*?/dp/[A-Z0-9]{10})(?:/|$)", href, re.IGNORECASE)
    if not match:
        match = re.search(r"(/dp/[A-Z0-9]{10})(?:/|$)", href, re.IGNORECASE)
    return urljoin("https://www.amazon.in", match.group(1)) if match else None


def _amazon_relevance_name(title: str) -> str:
    identity = " ".join(title.split()).split(":", 1)[0]
    identity = re.sub(r"\s+\d+\s*(?:GB|TB)\s*$", "", identity, flags=re.IGNORECASE)
    return identity.strip(" ,|-")


def _amazon_title_link(card):
    selectors = (
        'a[href*="/dp/"] h2',
        'a[href*="/sspa/click"] h2',
        'a.a-link-normal[href*="/dp/"]',
        'a.a-link-normal[href*="/sspa/click"]',
    )
    for selector in selectors:
        matches = card.locator(selector)
        for index in range(matches.count()):
            element = matches.nth(index)
            text = " ".join(element.inner_text().split())
            if not text or text.startswith("₹"):
                continue
            if element.evaluate("node => node.tagName") == "H2":
                return element.locator("xpath=ancestor::a[1]")
            return element

    product_links = card.locator('a[href*="/dp/"], a[href*="/sspa/click"]')
    candidates = []
    for index in range(product_links.count()):
        link = product_links.nth(index)
        href = link.get_attribute("href") or ""
        text = " ".join(link.inner_text().split())
        if not text or text.startswith("₹") or "customerReviews" in href:
            continue
        candidates.append((len(text), link))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def amazon_search(search_term: str) -> list[dict[str, str]]:
    """Collect up to two relevant Amazon India products."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            search_url = f"https://www.amazon.in/s?k={quote_plus(search_term)}"
            cards = None
            usable = False
            for attempt in range(2):
                response = page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                _raise_if_restricted(page)
                cards = page.locator('[data-component-type="s-search-result"]')
                usable = any(
                    cards.nth(index).is_visible()
                    and _amazon_title_link(cards.nth(index)) is not None
                    for index in range(cards.count())
                )
                if response and response.status != 503 and usable:
                    break
                if attempt == 0:
                    time.sleep(1)

            if cards is None or not usable:
                raise RuntimeError("No visible relevant Amazon product was found.")

            candidates: list[dict[str, str]] = []
            seen_urls: set[str] = set()
            for index in range(cards.count()):
                card = cards.nth(index)
                if not card.is_visible():
                    continue
                title_link = _amazon_title_link(card)
                if title_link is None:
                    continue
                raw_title = " ".join(title_link.inner_text().split())
                product_identity = _amazon_relevance_name(raw_title)
                product_url = _amazon_product_url(title_link.get_attribute("href") or "")
                if not product_identity or not product_url or product_url in seen_urls:
                    continue
                seen_urls.add(product_url)
                price_element = card.locator(".a-price .a-offscreen").first
                rating_element = card.locator("span.a-icon-alt").first
                review_element = card.locator('a[href*="customerReviews"]').first
                rating_match = re.search(
                    r"(\d(?:\.\d+)?)\s+out of",
                    rating_element.inner_text() if rating_element.count() else "",
                    re.IGNORECASE,
                )
                review_text = review_element.inner_text().strip("() ") if review_element.count() else ""
                candidates.append({
                    "product_name": product_identity,
                    "display_name": raw_title,
                    "product_url": product_url,
                    "current_selling_price": price_element.inner_text().strip() if price_element.count() else "Not displayed",
                    "rating": rating_match.group(1) if rating_match else "Not displayed",
                    "review_count": review_text or "Not displayed",
                })

            results = _rank_results(search_term, candidates)
            if not results:
                raise RuntimeError("No visible relevant Amazon product was found.")
            for result in results:
                result["product_name"] = result.pop("display_name", result["product_name"])
            return results
        finally:
            browser.close()


def _legacy_myntra_search(search_term: str) -> list[dict[str, str]]:
    """Collect up to two relevant Myntra products using the public HTML response."""
    import json
    import requests

    search_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        search_term.lower()
    ).strip("-")

    encoded_term = quote_plus(search_term).replace("+", "%20")

    search_url = (
        f"https://www.myntra.com/"
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
            "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = requests.get(
            search_url,
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            "Myntra temporarily unavailable"
        ) from error

    if response.status_code != 200:
        raise RuntimeError(
            "Myntra temporarily unavailable"
        )

    html = response.text

    if not html:
        raise RuntimeError(
            "Myntra temporarily unavailable"
        )

    # Myntra exposes product information in JSON-LD.
    json_ld_blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>'
        r'(.*?)'
        r'</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    products = []

    for block in json_ld_blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        if not isinstance(data, dict):
            continue

        if data.get("@type") != "ItemList":
            continue

        items = data.get("itemListElement", [])

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()

            if not name or not url:
                continue

            if "/buy" not in url:
                continue

            products.append({
                "product_name": re.sub(r"\s+", " ", name),
                "product_url": url,
            })

    # Remove duplicate products.
    unique_products = []
    seen_urls = set()

    for product in products:
        url = product["product_url"]

        if url in seen_urls:
            continue

        seen_urls.add(url)
        unique_products.append(product)

    if not unique_products:
        raise RuntimeError(
            "No visible relevant Myntra product was found."
        )

    # Extract additional product information from the HTML.
    #
    # Myntra embeds product objects in its page source. We look for
    # product URLs and then inspect nearby JSON/text for price data.
    candidates = []

    for product in unique_products:
        product_name = product["product_name"]
        product_url = product["product_url"]

        candidates.append({
            "product_name": product_name,
            "product_url": product_url,
            "current_selling_price": "Not displayed",
            "rating": "Not displayed",
            "review_count": "Not displayed",
        })

    # Existing relevance/ranking logic decides which products are valid.
    results = _rank_results(search_term, candidates)

    if not results:
        raise RuntimeError(
            "No visible relevant Myntra product was found."
        )

    return results[:2]


def myntra_search(search_term: str) -> list[dict[str, str]]:
    """Collect relevant Myntra products from embedded HTML data."""
    import json
    import requests

    search_slug = re.sub(r"[^a-z0-9]+", "-", search_term.lower()).strip("-")
    encoded_term = quote_plus(search_term).replace("+", "%20")
    search_url = f"https://www.myntra.com/{search_slug}?rawQuery={encoded_term}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        response = requests.get(search_url, headers=headers, timeout=30)
    except requests.RequestException as error:
        raise RuntimeError("Myntra temporarily unavailable") from error
    if response.status_code != 200:
        raise RuntimeError("Myntra temporarily unavailable")

    html = response.text
    marker = re.search(r'"products"\s*:\s*\[', html)
    if not marker:
        raise RuntimeError("No visible relevant Myntra product was found.")
    start = html.find("[", marker.start())
    depth = 0
    in_string = False
    escaped = False
    end = None
    for position in range(start, len(html)):
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
        raise RuntimeError("No visible relevant Myntra product was found.")
    try:
        products = json.loads(html[start:end])
    except json.JSONDecodeError as error:
        raise RuntimeError("Myntra temporarily unavailable") from error

    candidates = []
    seen_urls = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        name = str(product.get("productName") or product.get("product") or "").strip()
        landing_url = str(product.get("landingPageUrl") or "").strip()
        if not name or not landing_url:
            continue
        product_url = landing_url if landing_url.startswith("http") else urljoin("https://www.myntra.com/", landing_url)
        if product_url in seen_urls:
            continue
        seen_urls.add(product_url)
        price_value = product.get("price") or product.get("mrp")
        rating_value = product.get("rating")
        review_value = product.get("ratingCount")
        candidates.append({
            "product_name": name,
            "product_url": product_url,
            "current_selling_price": f"₹{price_value:,.0f}" if isinstance(price_value, (int, float)) and price_value else "Not displayed",
            "rating": f"{float(rating_value):.1f}" if isinstance(rating_value, (int, float)) and rating_value else "Not displayed",
            "review_count": str(review_value) if review_value is not None else "Not displayed",
        })
    results = _rank_results(search_term, candidates)
    if not results:
        raise RuntimeError("No visible relevant Myntra product was found.")
    return results


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit('Usage: python playwright_test.py "search term"')
    term = sys.argv[1].strip()
    print("FLIPKART:")
    try:
        for result in main(term):
            print(result)
    except RuntimeError as error:
        print(error)
    print("\nAMAZON:")
    try:
        for result in amazon_search(term):
            print(result)
    except RuntimeError as error:
        print(error)

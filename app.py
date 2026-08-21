from flask import Flask, render_template, request
import os
import sys
import traceback
from datetime import datetime

app = Flask(__name__)


def print_separator():
    print("=" * 70, flush=True)


@app.route("/", methods=["GET"])
def home():
    print_separator()
    print("[APP] HOME REQUEST RECEIVED", flush=True)
    print_separator()

    return render_template(
        "index.html",
        search_term="",
        results=None,
        flipkart_status=None,
        amazon_status=None,
        myntra_status=None,
    )


@app.route("/search", methods=["GET", "POST"])
def search():
    print_separator()
    print("[APP] SEARCH REQUEST RECEIVED", flush=True)

    # Support both GET (?q=...) and POST (search_term=...)
    search_term = (
        request.args.get("q", "").strip()
        or request.form.get("search_term", "").strip()
    )

    print(f"[APP] QUERY = {search_term}", flush=True)
    print(
        f"[APP] TIME = {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        flush=True,
    )
    print_separator()

    if not search_term:
        print("[APP] Empty search query", flush=True)

        return render_template(
            "index.html",
            search_term="",
            results=None,
            flipkart_status=None,
            amazon_status=None,
            myntra_status=None,
        )

    results = []

    flipkart_status = None
    amazon_status = None
    myntra_status = None

    # Import the collector module only when a search happens.
    try:
        import playwright_test

        print(
            f"[APP] Loaded playwright_test from: "
            f"{playwright_test.__file__}",
            flush=True,
        )

    except Exception as error:
        print(
            f"[APP] ERROR importing playwright_test: {error!r}",
            flush=True,
        )
        traceback.print_exc()

        return render_template(
            "index.html",
            search_term=search_term,
            results=[],
            flipkart_status=f"Collector import failed: {error}",
            amazon_status=f"Collector import failed: {error}",
            myntra_status=f"Collector import failed: {error}",
        )

    # ==========================================================
    # FLIPKART
    # ==========================================================

    print_separator()
    print(f"[APP] STARTING FLIPKART SEARCH: {search_term}", flush=True)
    print_separator()

    try:
        flipkart_results = playwright_test.main(search_term)

        print(
            f"[APP] FLIPKART RETURNED "
            f"{len(flipkart_results or [])} PRODUCTS",
            flush=True,
        )

        for product in flipkart_results or []:
            print(
                f"[APP] FLIPKART PRODUCT: "
                f"{product.get('product_name')}",
                flush=True,
            )

            product = dict(product)
            product["store"] = "Flipkart"
            results.append(product)

        if not flipkart_results:
            flipkart_status = "No matching Flipkart products found"

    except Exception as error:
        print(
            f"[APP] FLIPKART ERROR: {error!r}",
            flush=True,
        )
        traceback.print_exc()

        flipkart_status = (
            f"Unable to fetch Flipkart results: "
            f"{type(error).__name__}: {error}"
        )

    # ==========================================================
    # AMAZON
    # ==========================================================

    print_separator()
    print(f"[APP] STARTING AMAZON SEARCH: {search_term}", flush=True)
    print_separator()

    try:
        amazon_results = playwright_test.amazon_search(search_term)

        print(
            f"[APP] AMAZON RETURNED "
            f"{len(amazon_results or [])} PRODUCTS",
            flush=True,
        )

        for product in amazon_results or []:
            print(
                f"[APP] AMAZON PRODUCT: "
                f"{product.get('product_name')}",
                flush=True,
            )

            product = dict(product)
            product["store"] = "Amazon"
            results.append(product)

        if not amazon_results:
            amazon_status = "No matching Amazon products found"

    except Exception as error:
        print(
            f"[APP] AMAZON ERROR: {error!r}",
            flush=True,
        )
        traceback.print_exc()

        amazon_status = (
            f"Unable to fetch Amazon results: "
            f"{type(error).__name__}: {error}"
        )

    # ==========================================================
    # MYNTRA
    # ==========================================================

    print_separator()
    print(f"[APP] STARTING MYNTRA SEARCH: {search_term}", flush=True)
    print_separator()

    try:
        myntra_results = playwright_test.myntra_search(search_term)

        print(
            f"[APP] MYNTRA RETURNED "
            f"{len(myntra_results or [])} PRODUCTS",
            flush=True,
        )

        for product in myntra_results or []:
            print(
                f"[APP] MYNTRA PRODUCT: "
                f"{product.get('product_name')}",
                flush=True,
            )

            product = dict(product)
            product["store"] = "Myntra"
            results.append(product)

        if not myntra_results:
            myntra_status = "No matching Myntra products found"

    except Exception as error:
        print(
            f"[APP] MYNTRA ERROR: {error!r}",
            flush=True,
        )
        traceback.print_exc()

        myntra_status = (
            f"Unable to fetch Myntra results: "
            f"{type(error).__name__}: {error}"
        )

    # ==========================================================
    # FINAL RESULTS
    # ==========================================================

    print_separator()
    print("[APP] SEARCH FINISHED", flush=True)
    print(f"[APP] TOTAL RESULTS = {len(results)}", flush=True)

    flipkart_count = sum(
        1 for item in results
        if item.get("store") == "Flipkart"
    )

    amazon_count = sum(
        1 for item in results
        if item.get("store") == "Amazon"
    )

    myntra_count = sum(
        1 for item in results
        if item.get("store") == "Myntra"
    )

    print(
        f"[APP] FLIPKART = {flipkart_count}",
        flush=True,
    )
    print(
        f"[APP] AMAZON   = {amazon_count}",
        flush=True,
    )
    print(
        f"[APP] MYNTRA   = {myntra_count}",
        flush=True,
    )

    for number, item in enumerate(results, start=1):
        print(
            f"[APP] RESULT {number}: "
            f"[{item.get('store')}] "
            f"{item.get('product_name')} | "
            f"{item.get('current_selling_price')}",
            flush=True,
        )

    print_separator()

    return render_template(
        "index.html",
        search_term=search_term,
        results=results,
        flipkart_status=flipkart_status,
        amazon_status=amazon_status,
        myntra_status=myntra_status,
    )


# ==============================================================
# ERROR HANDLERS
# ==============================================================

@app.errorhandler(Exception)
def handle_exception(error):
    print_separator()
    print("[APP] UNHANDLED FLASK ERROR", flush=True)
    print(f"[APP] ERROR = {error!r}", flush=True)
    traceback.print_exc()
    print_separator()

    return render_template(
        "index.html",
        search_term=request.args.get("q", ""),
        results=[],
        flipkart_status=f"Application error: {error}",
        amazon_status=None,
        myntra_status=None,
    ), 500


# ==============================================================
# START APPLICATION
# ==============================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    print()
    print("=" * 70)
    print("[APP] QUICKSHOP STARTING")
    print(f"[APP] Port: {port}")
    print(f"[APP] Python: {sys.executable}")
    print(f"[APP] Working directory: {os.getcwd()}")

    try:
        import playwright_test

        print(
            f"[APP] playwright_test: "
            f"{playwright_test.__file__}"
        )

        print("[APP] Collector functions:")
        print(
            f"       Flipkart = "
            f"{hasattr(playwright_test, 'main')}"
        )
        print(
            f"       Amazon   = "
            f"{hasattr(playwright_test, 'amazon_search')}"
        )
        print(
            f"       Myntra   = "
            f"{hasattr(playwright_test, 'myntra_search')}"
        )

    except Exception as error:
        print(
            f"[APP] WARNING: Could not load playwright_test: "
            f"{error!r}"
        )

    print("=" * 70)
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=False,
    )
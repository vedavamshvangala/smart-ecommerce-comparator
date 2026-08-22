from flask import Flask, render_template, request
import os
import sys
import traceback
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

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

    # ----------------------------------------------------------
    # LOAD COLLECTOR
    # ----------------------------------------------------------

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
    # STORE SEARCH FUNCTIONS
    # ==========================================================

    def search_flipkart():
        start_time = time.perf_counter()

        print_separator()
        print(
            f"[APP] STARTING FLIPKART SEARCH: {search_term}",
            flush=True,
        )

        try:
            data = playwright_test.main(search_term)

            elapsed = time.perf_counter() - start_time

            print(
                f"[APP] FLIPKART SEARCH FINISHED "
                f"IN {elapsed:.2f} SECONDS",
                flush=True,
            )

            return {
                "store": "Flipkart",
                "results": data or [],
                "error": None,
                "time": elapsed,
            }

        except Exception as error:
            elapsed = time.perf_counter() - start_time

            print(
                f"[APP] FLIPKART ERROR AFTER "
                f"{elapsed:.2f} SECONDS: {error!r}",
                flush=True,
            )
            traceback.print_exc()

            return {
                "store": "Flipkart",
                "results": [],
                "error": error,
                "time": elapsed,
            }

    def search_amazon():
        start_time = time.perf_counter()

        print_separator()
        print(
            f"[APP] STARTING AMAZON SEARCH: {search_term}",
            flush=True,
        )

        try:
            data = playwright_test.amazon_search(search_term)

            elapsed = time.perf_counter() - start_time

            print(
                f"[APP] AMAZON SEARCH FINISHED "
                f"IN {elapsed:.2f} SECONDS",
                flush=True,
            )

            return {
                "store": "Amazon",
                "results": data or [],
                "error": None,
                "time": elapsed,
            }

        except Exception as error:
            elapsed = time.perf_counter() - start_time

            print(
                f"[APP] AMAZON ERROR AFTER "
                f"{elapsed:.2f} SECONDS: {error!r}",
                flush=True,
            )
            traceback.print_exc()

            return {
                "store": "Amazon",
                "results": [],
                "error": error,
                "time": elapsed,
            }

    def search_myntra():
        start_time = time.perf_counter()

        print_separator()
        print(
            f"[APP] STARTING MYNTRA SEARCH: {search_term}",
            flush=True,
        )

        try:
            data = playwright_test.myntra_search(search_term)

            elapsed = time.perf_counter() - start_time

            print(
                f"[APP] MYNTRA SEARCH FINISHED "
                f"IN {elapsed:.2f} SECONDS",
                flush=True,
            )

            return {
                "store": "Myntra",
                "results": data or [],
                "error": None,
                "time": elapsed,
            }

        except Exception as error:
            elapsed = time.perf_counter() - start_time

            print(
                f"[APP] MYNTRA ERROR AFTER "
                f"{elapsed:.2f} SECONDS: {error!r}",
                flush=True,
            )
            traceback.print_exc()

            return {
                "store": "Myntra",
                "results": [],
                "error": error,
                "time": elapsed,
            }

    # ==========================================================
    # PARALLEL SEARCH
    # ==========================================================

    print_separator()
    print(
        "[APP] STARTING ALL STORE SEARCHES IN PARALLEL",
        flush=True,
    )
    print(
        f"[APP] QUERY = {search_term}",
        flush=True,
    )
    print_separator()

    overall_start = time.perf_counter()

    search_functions = {
        "Flipkart": search_flipkart,
        "Amazon": search_amazon,
        "Myntra": search_myntra,
    }

    completed_results = {}

    with ThreadPoolExecutor(max_workers=3) as executor:

        future_map = {
            executor.submit(function): store
            for store, function in search_functions.items()
        }

        for future in as_completed(future_map):

            store = future_map[future]

            try:
                result = future.result()
                completed_results[store] = result

            except Exception as error:
                print(
                    f"[APP] UNEXPECTED {store} THREAD ERROR: "
                    f"{error!r}",
                    flush=True,
                )
                traceback.print_exc()

                completed_results[store] = {
                    "store": store,
                    "results": [],
                    "error": error,
                    "time": 0,
                }

    # ==========================================================
    # PROCESS RESULTS
    # ==========================================================

    # Keep the output order:
    # Flipkart -> Amazon -> Myntra

    store_order = [
        "Flipkart",
        "Amazon",
        "Myntra",
    ]

    for store in store_order:

        result_data = completed_results.get(
            store,
            {
                "store": store,
                "results": [],
                "error": None,
                "time": 0,
            },
        )

        store_results = result_data["results"]
        error = result_data["error"]
        elapsed = result_data["time"]

        print(
            f"[APP] {store.upper()} RETURNED "
            f"{len(store_results)} PRODUCTS",
            flush=True,
        )

        if error is not None:

            status_message = (
                f"Unable to fetch {store} results: "
                f"{type(error).__name__}: {error}"
            )

            if store == "Flipkart":
                flipkart_status = status_message

            elif store == "Amazon":
                amazon_status = status_message

            elif store == "Myntra":
                myntra_status = status_message

            continue

        if not store_results:

            status_message = (
                f"No matching {store} products found"
            )

            if store == "Flipkart":
                flipkart_status = status_message

            elif store == "Amazon":
                amazon_status = status_message

            elif store == "Myntra":
                myntra_status = status_message

        for product in store_results:

            print(
                f"[APP] {store.upper()} PRODUCT: "
                f"{product.get('product_name')}",
                flush=True,
            )

            product = dict(product)
            product["store"] = store
            results.append(product)

    # ==========================================================
    # TIMING SUMMARY
    # ==========================================================

    total_elapsed = time.perf_counter() - overall_start

    print_separator()
    print("[APP] SEARCH FINISHED", flush=True)

    print(
        f"[APP] FLIPKART TIME = "
        f"{completed_results.get('Flipkart', {}).get('time', 0):.2f} SECONDS",
        flush=True,
    )

    print(
        f"[APP] AMAZON TIME   = "
        f"{completed_results.get('Amazon', {}).get('time', 0):.2f} SECONDS",
        flush=True,
    )

    print(
        f"[APP] MYNTRA TIME   = "
        f"{completed_results.get('Myntra', {}).get('time', 0):.2f} SECONDS",
        flush=True,
    )

    print(
        f"[APP] TOTAL PARALLEL TIME = "
        f"{total_elapsed:.2f} SECONDS",
        flush=True,
    )

    print_separator()

    # ==========================================================
    # RESULT COUNTS
    # ==========================================================

    print(
        f"[APP] TOTAL RESULTS = {len(results)}",
        flush=True,
    )

    flipkart_count = sum(
        1
        for item in results
        if item.get("store") == "Flipkart"
    )

    amazon_count = sum(
        1
        for item in results
        if item.get("store") == "Amazon"
    )

    myntra_count = sum(
        1
        for item in results
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

    for number, item in enumerate(
        results,
        start=1,
    ):
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
    print(
        "[APP] UNHANDLED FLASK ERROR",
        flush=True,
    )
    print(
        f"[APP] ERROR = {error!r}",
        flush=True,
    )

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

    port = int(
        os.environ.get(
            "PORT",
            5000,
        )
    )

    print()
    print("=" * 70)
    print("[APP] QUICKSHOP STARTING")
    print(f"[APP] Port: {port}")
    print(f"[APP] Python: {sys.executable}")
    print(
        f"[APP] Working directory: "
        f"{os.getcwd()}"
    )

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
            f"[APP] WARNING: Could not load "
            f"playwright_test: {error!r}"
        )

    print("=" * 70)
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=False,
    )
    
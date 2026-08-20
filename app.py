from flask import Flask, render_template, request
import os

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
@app.route("/search", methods=["GET", "POST"])
def home():
    search_term = (
        request.form.get("search_term", "").strip()
        or request.args.get("q", "").strip()
    )

    results = None
    flipkart_status = None
    amazon_status = None
    myntra_status = None

    if search_term:
        results = []

        from playwright_test import amazon_search, main, myntra_search

        # --------------------------------------------------
        # Flipkart
        # --------------------------------------------------
        try:
            flipkart_results = main(search_term)

            print("FLIPKART RESULTS:", flipkart_results)

            results.extend(
                {**result, "store": "Flipkart"}
                for result in flipkart_results
            )

            if not flipkart_results:
                flipkart_status = "No matching Flipkart products found"

        except Exception as error:
            print("FLIPKART ERROR:", repr(error))
            flipkart_status = "Flipkart temporarily unavailable"

        # --------------------------------------------------
        # Amazon
        # --------------------------------------------------
        try:
            amazon_results = amazon_search(search_term)

            print("AMAZON RESULTS:", amazon_results)

            results.extend(
                {**result, "store": "Amazon"}
                for result in amazon_results
            )

            if not amazon_results:
                amazon_status = "No matching Amazon products found"

        except Exception as error:
            print("AMAZON ERROR:", repr(error))

            if "No visible relevant Amazon product was found." in str(error):
                amazon_status = "No matching Amazon products found"
            else:
                amazon_status = "Amazon temporarily unavailable"

        # --------------------------------------------------
        # Myntra
        # --------------------------------------------------
        try:
            myntra_results = myntra_search(search_term)

            print("MYNTRA RESULTS:", myntra_results)

            results.extend(
                {**result, "store": "Myntra"}
                for result in myntra_results
            )

            if not myntra_results:
                myntra_status = "No matching Myntra products found"

        except Exception as error:
            print("MYNTRA ERROR:", repr(error))
            myntra_status = f"Myntra temporarily unavailable"

    return render_template(
        "index.html",
        search_term=search_term,
        results=results,
        flipkart_status=flipkart_status,
        amazon_status=amazon_status,
        myntra_status=myntra_status,
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
    )
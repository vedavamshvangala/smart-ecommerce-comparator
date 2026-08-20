from flask import Flask, render_template, request

app = Flask(__name__)

DUMMY_RESULTS = [
    {
        "product_name": "Amazon",
        "current_selling_price": "₹1,499",
        "rating": "4.3",
        "review_count": "Not displayed",
    },
    {
        "product_name": "Flipkart",
        "current_selling_price": "₹1,529",
        "rating": "4.2",
        "review_count": "Not displayed",
    },
    {
        "product_name": "Croma",
        "current_selling_price": "₹1,599",
        "rating": "4.1",
        "review_count": "Not displayed",
    },
]


@app.route("/", methods=["GET", "POST"])
@app.route("/search", methods=["GET", "POST"])
def home():
    search_term = request.form.get("search_term", "").strip() or request.args.get("q", "").strip()
    results = None
    amazon_status = None
    myntra_status = None

    if search_term:
        results = []
        from playwright_test import amazon_search, main, myntra_search

        try:
            flipkart_results = main(search_term)
            results.extend({**result, "store": "Flipkart"} for result in flipkart_results)
        except Exception:
            results.extend({**result, "store": "Flipkart"} for result in DUMMY_RESULTS)

        try:
            amazon_results = amazon_search(search_term)
            results.extend({**result, "store": "Amazon"} for result in amazon_results)
        except Exception as error:
            if "No visible relevant Amazon product was found." in str(error):
                amazon_status = "No matching Amazon products found"
            else:
                amazon_status = "Amazon temporarily unavailable"

        try:
            myntra_results = myntra_search(search_term)
            print("MYNTRA RESULTS:", myntra_results)
            results.extend({**result, "store": "Myntra"} for result in myntra_results)
        except Exception as error:
            print("MYNTRA ERROR:", repr(error))
            myntra_status = f"Myntra error: {error}"
    return render_template(
        "index.html",
        search_term=search_term,
        results=results,
        amazon_status=amazon_status,
        myntra_status=myntra_status,
    )


if __name__ == "__main__":
    app.run(debug=True)
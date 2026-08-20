import playwright_test as p

candidates = [
    {
        "product_name": "Nike Revolution 7 Mens Lace-Ups Road Running Shoes",
        "product_url": "x",
        "current_selling_price": "₹3695",
        "rating": "4.8",
        "review_count": "33",
    },
    {
        "product_name": "Nike MC Trainer 3 Mens Workout Shoes",
        "product_url": "y",
        "current_selling_price": "₹5695",
        "rating": "4.5",
        "review_count": "85",
    },
]

result = p._rank_results("Nike shoes for men", candidates)

print("RANKING RESULT:")
print(result)

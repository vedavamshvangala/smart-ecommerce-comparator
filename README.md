# 🛍️ Smart E-Commerce Comparator

A smart product comparison web application that searches multiple e-commerce platforms and displays products, prices, ratings, reviews, and direct product links in one place.

## 🚀 Overview

**Smart E-Commerce Comparator** helps users compare products across multiple online shopping platforms without manually searching each website.

The application accepts a natural-language product search such as:

- `Nike shoes for men`
- `US polo shirts for men`
- `kurtis for women`
- `jeans for women`
- `running shoes`

It searches supported e-commerce platforms, matches relevant products using keyword/token-based search logic, ranks the results, and displays the best matching products.

## ✨ Features

- 🔎 Natural-language product search
- 🛒 Multi-store product comparison
- 💰 Compare product prices
- ⭐ Display product ratings
- 💬 Display review counts
- 🔗 Direct "View Product" links
- 🧠 Token-based product matching
- 👨 Men's / 👩 Women's gender-aware matching
- 🔤 Singular/plural matching
- 🏷️ Brand and product keyword matching
- 🚫 Generic search-word filtering
- 📊 Product ranking
- ♻️ Duplicate product removal
- 🌐 Web-based user interface

## 🏪 Supported Platforms

The project currently searches products from:

- Flipkart
- Amazon
- Myntra

## 🧠 Smart Search Matching

Instead of requiring the complete search phrase to appear in a product name, the application extracts meaningful search tokens and compares them with product tokens.

For example:

```text
Search:
kurtis for women

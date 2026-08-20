document.addEventListener("DOMContentLoaded", function () {
    console.log("QUICKSHOP loaded");

    const productLinks = document.querySelectorAll(".product-button");

    productLinks.forEach(function (link) {
        link.addEventListener("click", function () {
            console.log("Opening product:", link.href);
        });
    });
});
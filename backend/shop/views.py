from django.shortcuts import get_object_or_404, render
from .models import Product


def home(request):
    return render(request, "shop/home.html")


def product_list(request):
    products = (
        Product.objects.filter(is_active=True)
        .prefetch_related("variants")
        .select_related("category")
        .order_by("name")
    )
    return render(request, "shop/product_list.html", {"products": products})


def product_detail(request, slug: str):
    product = get_object_or_404(
        Product.objects.prefetch_related("variants").select_related("category"),
        slug=slug,
        is_active=True,
    )
    return render(request, "shop/product_detail.html", {"product": product})

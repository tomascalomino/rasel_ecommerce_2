from django.db.models import Min, Exists, OuterRef, Q, Prefetch
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Product, Variant


def product_list(request):
    query = (request.GET.get("q") or "").strip()
    in_stock_only = (request.GET.get("in_stock") or "") in {"1", "true", "on"}
    sort = (request.GET.get("sort") or "name_asc").strip()

    products = Product.objects.filter(is_active=True)

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(short_description__icontains=query)
        )

    # Basic ordering
    if sort == "price_asc":
        # Note: this will need annotations back later, but making it simple first
        products = products.order_by("name")
    else:
        products = products.order_by("name")

    paginator = Paginator(products, 9)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "shop/product_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "in_stock_only": in_stock_only,
            "sort": sort,
        },
    )


def product_detail(request, slug: str):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related(
            Prefetch("variants", queryset=Variant.objects.filter(is_active=True))
        ),
        slug=slug,
        is_active=True,
    )
    return render(request, "shop/product_detail.html", {"product": product})

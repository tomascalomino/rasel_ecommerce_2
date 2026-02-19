from django.db.models import Min, Exists, OuterRef, Q, Prefetch
from django.shortcuts import get_object_or_404, render

from .models import Product, Variant


def product_list(request):
    active_variants = Variant.objects.filter(is_active=True)

    products = (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related(Prefetch("variants", queryset=active_variants))
        .annotate(
            min_price_ars=Min(
                "variants__price_ars",
                filter=Q(variants__is_active=True),
            ),
            in_stock=Exists(
                Variant.objects.filter(
                    product_id=OuterRef("pk"),
                    is_active=True,
                    stock_qty__gt=0,
                )
            ),
        )
        .order_by("name")
    )

    return render(request, "shop/product_list.html", {"products": products})


def product_detail(request, slug: str):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related(
            Prefetch("variants", queryset=Variant.objects.filter(is_active=True))
        ),
        slug=slug,
        is_active=True,
    )
    return render(request, "shop/product_detail.html", {"product": product})

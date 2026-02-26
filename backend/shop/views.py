from django.db.models import Min, Exists, OuterRef, Q, Prefetch
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from .models import Product, Variant


def product_list(request):
    query = (request.GET.get("q") or "").strip()
    in_stock_only = (request.GET.get("in_stock") or "") in {"1", "true", "on"}
    sort = (request.GET.get("sort") or "name_asc").strip()

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
    )

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(short_description__icontains=query)
            | Q(description__icontains=query)
        )

    if in_stock_only:
        products = products.filter(in_stock=True)

    if sort == "name_desc":
        products = products.order_by("-name")
    elif sort == "price_asc":
        products = products.order_by("min_price_ars", "name")
    elif sort == "price_desc":
        products = products.order_by("-min_price_ars", "name")
    else:
        sort = "name_asc"
        products = products.order_by("name")

    paginator = Paginator(products, 9)
    page_obj = paginator.get_page(request.GET.get("page"))

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()

    return render(
        request,
        "shop/product_list.html",
        {
            "products": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
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

from django.db.models import Min, Exists, OuterRef, Q, Prefetch
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.html import escape

from .models import Product, Variant


def healthz(request):
    """Health-check liviano para el ping de keep-alive (no toca la base)."""
    return HttpResponse("ok", content_type="text/plain")


def robots_txt(request):
    sitemap_url = request.build_absolute_uri("/sitemap.xml")
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /cart/",
        "Disallow: /orders/",
        "Disallow: /payments/",
        "Disallow: /healthz",
        f"Sitemap: {sitemap_url}",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    urls = [request.build_absolute_uri(reverse(name)) for name in (
        "home", "about", "contact", "terms", "privacy", "returns", "regret",
        "shop:product_list",
    )]
    for product in Product.objects.filter(is_active=True):
        urls.append(request.build_absolute_uri(reverse("shop:product_detail", args=[product.slug])))

    items = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</urlset>"
    )
    return HttpResponse(xml, content_type="application/xml")


def product_list(request):
    query = (request.GET.get("q") or "").strip()
    in_stock_only = (request.GET.get("in_stock") or "") in {"1", "true", "on"}
    sort = (request.GET.get("sort") or "name_asc").strip()

    # 1. Fetch all products and their variants to memory (safe for small/medium boutique catalogs)
    all_products = list(Product.objects.filter(is_active=True).prefetch_related("variants"))

    # 2. Attach properties statically to avoid DB annotation errors in Postgres
    for p in all_products:
        active_vars = [v for v in p.variants.all() if v.is_active]
        if active_vars:
            p.min_price_ars = min(v.price_ars for v in active_vars)
            p.in_stock = any(v.stock_qty > 0 for v in active_vars)
        else:
            p.min_price_ars = None
            p.in_stock = False

    # 3. Apply filters
    filtered_products = []
    query_lower = query.lower()
    for p in all_products:
        text_match = True
        if query_lower:
            name_lower = (p.name or "").lower()
            desc_lower = (p.short_description or "").lower()
            text_match = (query_lower in name_lower) or (query_lower in desc_lower)
            
        stock_match = True
        if in_stock_only:
            stock_match = p.in_stock
            
        if text_match and stock_match:
            filtered_products.append(p)

    # 4. Apply sorting
    if sort == "price_asc":
        filtered_products.sort(key=lambda p: (p.min_price_ars if p.min_price_ars is not None else 99999999, p.name))
    elif sort == "price_desc":
        filtered_products.sort(key=lambda p: (p.min_price_ars if p.min_price_ars is not None else -1, p.name), reverse=True)
    elif sort == "name_desc":
        filtered_products.sort(key=lambda p: p.name, reverse=True)
    else:
        filtered_products.sort(key=lambda p: p.name)

    # 5. Paginate the resulting list
    paginator = Paginator(filtered_products, 9)
    page_obj = paginator.get_page(request.GET.get("page"))
    
    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()

    return render(
        request,
        "shop/product_list.html",
        {
            "page_obj": page_obj,
            "query_string": query_string,
            "query": query,
            "in_stock_only": in_stock_only,
            "sort": sort,
            "total_products": len(all_products),
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

    active_vars = list(product.variants.all())
    product.min_price_ars = min((v.price_ars for v in active_vars), default=None)
    product.in_stock = any(v.stock_qty > 0 for v in active_vars)

    # "También te puede gustar": otros productos activos con su precio mínimo.
    related = list(
        Product.objects.filter(is_active=True)
        .exclude(pk=product.pk)
        .prefetch_related("variants")[:3]
    )
    for p in related:
        rel_vars = [v for v in p.variants.all() if v.is_active]
        p.min_price_ars = min((v.price_ars for v in rel_vars), default=None)
        p.in_stock = any(v.stock_qty > 0 for v in rel_vars)

    return render(
        request,
        "shop/product_detail.html",
        {"product": product, "related_products": related},
    )

from django.utils.cache import patch_cache_control


class PromotionCacheMiddleware:
    """Time-sensitive public HTML must reach Django, including cached back visits."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        name = request.resolver_match.view_name if request.resolver_match else ""
        if name in {
            "home",
            "shop:product_list",
            "shop:product_detail",
            "cart:detail",
            "orders:checkout",
            "shipping_info",
            "shipping_promotion",
            "terms",
        }:
            patch_cache_control(
                response,
                private=True,
                no_store=True,
                no_cache=True,
                must_revalidate=True,
            )
        return response

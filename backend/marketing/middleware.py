from django.utils.cache import patch_cache_control

from .tracking import enabled, public_page


class MarketingPrivacyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if enabled() and public_page(request):
            patch_cache_control(response, private=True, no_store=True, no_cache=True)
        return response

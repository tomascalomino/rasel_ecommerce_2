from .cart import Cart

def cart(request):
    # request.session existe si SessionMiddleware está habilitado (lo tenés).
    return {"cart": Cart(request.session)}

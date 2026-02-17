# https://stackoverflow.com/a/47888695
class DisableCSRFMiddleware(object):
    """
    DisableCSRFMiddleware is a custom middleware that disables CSRF checks for all requests. This is useful for APIs that are not accessed via a browser and do not need CSRF protection.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setattr(request, "_dont_enforce_csrf_checks", True)
        response = self.get_response(request)
        return response

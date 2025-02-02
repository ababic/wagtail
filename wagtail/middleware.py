from wagtail.local import local_cache_enabled


class EnableLocalCacheMiddleware:
    """
    A middleware class that enables Wagtail's internal local cache, which allows certain
    values to be cached and re-accessed for the duration of a thread, without requiring
    direct access to the current `HttpRequest` or a request-level object, such as the
    `Page` currently being rendered.

    We conditionally enable this behaviour via middleware because:

    -   Background-workers that run management commands and other tasks often run in long-lived
        threads, which would use the cache values for longer than intended. Middleware only runs
        as part of Django's typical request/response cycle, so reduces the risk of unintional caching.
    -   The local-caching approach is quite new, and it's impossible to know all the wierd and
        wonderful things people are doing on their projects that might mean things don't work as
        intended (e.g. alternative Python compilations, modded versions of Django, or even
        infrastructure with unique approaches to memory management). If that is the case, the
        middleware can simply be disabled by removing "wagtail.middleware.EnableLocalCacheMiddleware"`
        from the `MIDDLEWARE` setting.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with local_cache_enabled():
            return self.get_response(request)

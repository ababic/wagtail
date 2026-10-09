import hashlib
import json

from django.http import HttpResponse, JsonResponse
from django.utils.cache import patch_cache_control


def respond_with_http_cache(
    request,
    data,
    *,
    max_age=300,
    s_maxage=300,
    stale_while_revalidate=600,
):
    """
    Return a JSON response with weak ETag and shared HTTP cache headers.

    Responds with ``304 Not Modified`` when ``If-None-Match`` matches the ETag.
    """
    body = json.dumps(data, sort_keys=True, separators=(",", ":"))
    etag = f'W/"{hashlib.sha256(body.encode()).hexdigest()[:32]}"'

    if request.META.get("HTTP_IF_NONE_MATCH") == etag:
        response = HttpResponse(status=304)
    else:
        response = JsonResponse(data)

    response["ETag"] = etag
    patch_cache_control(
        response,
        public=True,
        max_age=max_age,
        s_maxage=s_maxage,
        stale_while_revalidate=stale_while_revalidate,
    )
    response["Vary"] = "Accept-Encoding"
    return response

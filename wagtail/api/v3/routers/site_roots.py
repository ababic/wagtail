from django.http import HttpRequest
from ninja import Router

from wagtail.api.v3.auth import AllowAnonymous, BearerTokenAuth
from wagtail.api.v3.http_cache import respond_with_http_cache
from wagtail.api.v3.schemas.sites import SiteRootsListSchema
from wagtail.api.v3.site_roots import build_site_roots_list

router = Router(tags=["site-roots"], auth=[BearerTokenAuth(), AllowAnonymous()])


@router.get(
    "/",
    response={200: SiteRootsListSchema, 304: None},
    url_name="list_site_roots",
    summary="List site roots",
    operation_id="site_roots_list",
)
def list_site_roots(request: HttpRequest):
    return respond_with_http_cache(request, build_site_roots_list(request))

from collections import namedtuple

import swapper

from wagtail.models import Site

Page = swapper.load_model("wagtailcore", "Page")

LiveSiteRoot = namedtuple("LiveSiteRoot", "site_root_path page")


def live_site_roots(site_root_paths):
    """
    Return live ``SiteRootPath`` rows paired with their page instances.

    ``Site.get_site_root_paths()`` includes draft translations; this public
    endpoint must not expose them.
    """
    if not site_root_paths:
        return []

    live_pages = {
        (page.url_path, page.locale.language_code): page
        for page in Page.objects.filter(
            url_path__in={site_root_path.root_path for site_root_path in site_root_paths},
            live=True,
        )
        .select_related("locale")
        .specific(defer=True)
    }
    return [
        LiveSiteRoot(
            site_root_path,
            live_pages[(site_root_path.root_path, site_root_path.language_code)],
        )
        for site_root_path in site_root_paths
        if (site_root_path.root_path, site_root_path.language_code) in live_pages
    ]


def build_site_roots_list(request):
    """
    Assemble the site-roots API payload from ``Site.get_site_root_paths()``.

    Site metadata comes from a light queryset; locale URLs reuse the cached
    ``SiteRootPath`` rows and ``Page.get_full_url()``. Only live root pages
    are included.
    """
    live_roots = live_site_roots(Site.get_site_root_paths(request=request))

    site_order = []
    roots_by_site = {}
    for live_root in live_roots:
        site_id = live_root.site_root_path.site_id
        if site_id not in roots_by_site:
            site_order.append(site_id)
            roots_by_site[site_id] = []
        roots_by_site[site_id].append(live_root)

    sites_by_id = {
        site.id: site
        for site in Site.objects.filter(pk__in=site_order).only(
            "id",
            "hostname",
            "port",
            "site_name",
            "is_default_site",
        )
    }

    items = []
    for site_id in site_order:
        site = sites_by_id[site_id]
        items.append(
            {
                "id": site.id,
                "hostname": site.hostname,
                "port": site.port,
                "site_name": site.site_name,
                "is_default_site": site.is_default_site,
                "urls": [
                    {
                        "language_code": live_root.site_root_path.language_code,
                        "page_id": live_root.page.pk,
                        "html_url": live_root.page.get_full_url(request=request),
                    }
                    for live_root in roots_by_site[site_id]
                ],
            }
        )

    return {"count": len(items), "items": items}

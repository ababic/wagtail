(api_v3_site_roots)=

# Site roots

Site roots are exposed at `/api/v3/site-roots/` as a public read-only endpoint for headless routing. Anonymous requests are allowed, like redirects and public page reads. See [](api_v3_authentication) for how tokens map to permissions.

- `GET /site-roots/`: list all sites with their homepage URLs grouped by locale.

The response is not paginated. Each site includes `id`, `hostname`, `port`, `site_name`, `is_default_site`, and a `urls` array. Each URL entry has `language_code`, `page_id`, and `html_url` for that site's live homepage in that locale.

```json
{
  "count": 1,
  "items": [
    {
      "id": 1,
      "hostname": "localhost",
      "port": 80,
      "site_name": "",
      "is_default_site": true,
      "urls": [
        {
          "language_code": "en",
          "page_id": 2,
          "html_url": "http://localhost/"
        }
      ]
    }
  ]
}
```

When internationalisation is enabled, a site may have multiple `urls` entries (one per live root page translation). Draft or unpublished root pages are excluded. The ordering of sites and locales matches `Site.get_site_root_paths()` for the live roots that remain.

This endpoint is separate from `/api/v3/sites/`, which is permission-gated CRUD for site administration. Site roots expose only the URL-resolution data needed by frontends.

## Caching

The endpoint reuses Wagtail's existing `Site.get_site_root_paths()` cache and invalidation (site saves/deletes and site root page changes). The HTTP response also includes:

- `Cache-Control: public, max-age=300, s-maxage=300, stale-while-revalidate=600`
- A weak `ETag` for conditional requests (`If-None-Match`)
- `Vary: Accept-Encoding`

`html_url` is resolved via ``Page.get_full_url()``, so headless projects can override ``Page.get_url_parts()`` to return custom URLs. It is `null` when the page is not routable (for example when `wagtail_serve` is not registered).

## Example: list site roots

```sh
curl "https://example.com/api/v3/site-roots/"
```

## Site roots API reference

We document the full generated OpenAPI reference for every site-roots endpoint from Wagtail's own OpenAPI snapshot, see [](api_v3_reference).

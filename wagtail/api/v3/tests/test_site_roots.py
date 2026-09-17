from django.test import TestCase, override_settings
from django.urls import reverse

from wagtail.api.v3.site_roots import build_site_roots_list, live_site_roots
from wagtail.api.v3.tests.base import TestV3Base
from wagtail.models import Locale, Site
from wagtail.test.utils import Page, PageFixturesMixin, WagtailTestUtils

SITE_ROOT_FIELDS = {
    "id",
    "hostname",
    "port",
    "site_name",
    "is_default_site",
    "urls",
}
SITE_ROOT_URL_FIELDS = {"language_code", "page_id", "html_url"}


class TestV3SiteRootsListing(
    PageFixturesMixin, TestV3Base, WagtailTestUtils, TestCase
):
    fixtures = ["demosite.json"]

    def get_response(self, **params):
        return self.client.get(reverse("wagtailapi_v3:list_site_roots"), params)

    def test_anonymous_can_list_site_roots(self):
        response = self.get_response()
        self.assertEqual(response.status_code, 200)
        content = response.json()
        self.assertEqual(content["count"], Site.objects.count())

    def test_authenticated_returns_200(self):
        self.login()
        response = self.get_response()
        self.assertEqual(response.status_code, 200)

    def test_response_fields(self):
        content = self.get_response().json()
        self.assertIn("count", content)
        self.assertIn("items", content)
        for site in content["items"]:
            self.assertEqual(set(site.keys()), SITE_ROOT_FIELDS)
            self.assertTrue(site["urls"])
            for url in site["urls"]:
                self.assertEqual(set(url.keys()), SITE_ROOT_URL_FIELDS)

    def test_count_matches_database(self):
        content = self.get_response().json()
        self.assertEqual(content["count"], Site.objects.count())

    def test_page_id_and_html_url_match_homepage(self):
        content = self.get_response().json()
        default_site = Site.objects.get(is_default_site=True)
        site_json = next(item for item in content["items"] if item["id"] == default_site.id)
        self.assertEqual(len(site_json["urls"]), 1)
        self.assertEqual(site_json["urls"][0]["page_id"], default_site.root_page_id)
        self.assertEqual(
            site_json["urls"][0]["html_url"],
            default_site.root_page.full_url,
        )

    def test_ordering_matches_get_site_root_paths(self):
        content = self.get_response().json()
        site_ids_from_api = [item["id"] for item in content["items"]]
        site_ids_from_model = []
        for live_root in live_site_roots(Site.get_site_root_paths()):
            site_id = live_root.site_root_path.site_id
            if site_id not in site_ids_from_model:
                site_ids_from_model.append(site_id)
        self.assertEqual(site_ids_from_api, site_ids_from_model)

    def test_http_cache_headers(self):
        response = self.get_response()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["ETag"].startswith('W/"'))
        self.assertIn("public", response["Cache-Control"])
        self.assertIn("max-age=300", response["Cache-Control"])
        self.assertIn("s-maxage=300", response["Cache-Control"])
        self.assertIn("stale-while-revalidate=600", response["Cache-Control"])
        self.assertIn("Accept-Encoding", response["Vary"])

    def test_etag_returns_304(self):
        first_response = self.get_response()
        etag = first_response["ETag"]
        second_response = self.client.get(
            reverse("wagtailapi_v3:list_site_roots"),
            HTTP_IF_NONE_MATCH=etag,
        )
        self.assertEqual(second_response.status_code, 304)
        self.assertEqual(second_response["ETag"], etag)

    def test_build_site_roots_list_matches_endpoint(self):
        response = self.get_response()
        self.assertEqual(
            response.json(),
            build_site_roots_list(response.wsgi_request),
        )


@override_settings(WAGTAIL_I18N_ENABLED=True)
class TestV3SiteRootsI18n(PageFixturesMixin, TestV3Base, WagtailTestUtils, TestCase):
    fixtures = ["demosite.json"]

    def setUp(self):
        super().setUp()
        Site.clear_site_root_paths_cache()
        self.default_site = Site.objects.get(is_default_site=True)
        self.french = Locale.objects.create(language_code="fr")
        french_homepage = self.default_site.root_page.copy_for_translation(self.french)
        french_homepage.get_latest_revision().publish()

    def get_response(self):
        return self.client.get(reverse("wagtailapi_v3:list_site_roots"))

    def test_multiple_locale_urls_per_site(self):
        content = self.get_response().json()
        site_json = next(
            item for item in content["items"] if item["id"] == self.default_site.id
        )
        language_codes = {url["language_code"] for url in site_json["urls"]}
        self.assertEqual(language_codes, {"en", "fr"})

    def test_locale_urls_match_homepage_full_urls(self):
        content = self.get_response().json()
        site_json = next(
            item for item in content["items"] if item["id"] == self.default_site.id
        )
        urls_by_language = {
            url["language_code"]: url for url in site_json["urls"]
        }
        for root_page in (
            self.default_site.root_page.get_translations(inclusive=True)
            .filter(live=True)
            .select_related("locale")
        ):
            url = urls_by_language[root_page.locale.language_code]
            self.assertEqual(url["page_id"], root_page.pk)
            self.assertEqual(url["html_url"], root_page.full_url)


@override_settings(WAGTAIL_I18N_ENABLED=True)
class TestV3SiteRootsDraftExclusion(
    PageFixturesMixin, TestV3Base, WagtailTestUtils, TestCase
):
    fixtures = ["demosite.json"]

    def setUp(self):
        super().setUp()
        Site.clear_site_root_paths_cache()
        self.default_site = Site.objects.get(is_default_site=True)
        self.french = Locale.objects.create(language_code="fr")
        self.draft_french_homepage = self.default_site.root_page.copy_for_translation(
            self.french
        )
        self.assertFalse(self.draft_french_homepage.live)

    def get_response(self):
        return self.client.get(reverse("wagtailapi_v3:list_site_roots"))

    def test_draft_translation_root_is_excluded(self):
        content = self.get_response().json()
        site_json = next(
            item for item in content["items"] if item["id"] == self.default_site.id
        )
        language_codes = {url["language_code"] for url in site_json["urls"]}
        self.assertEqual(language_codes, {"en"})

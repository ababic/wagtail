from ninja import Field, Schema


class SiteRootUrlSchema(Schema):
    language_code: str
    page_id: int
    html_url: str | None


class SiteRootSchema(Schema):
    id: int
    hostname: str
    port: int
    site_name: str
    is_default_site: bool
    urls: list[SiteRootUrlSchema]


class SiteRootsListSchema(Schema):
    count: int
    items: list[SiteRootSchema]


class SiteSchema(Schema):
    id: int
    hostname: str
    port: int
    site_name: str
    root_page_id: int
    is_default_site: bool


class SiteInputSchema(Schema):
    hostname: str
    port: int = 80
    site_name: str = ""
    # Accept root_page_id in the input schema for consistency with the output,
    # but use root_page so it can be accepted by ModelForm.
    root_page: int = Field(..., alias="root_page_id")
    is_default_site: bool = False

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WagtailMultitenancyAppConfig(AppConfig):
    name = "wagtail.multitenancy"
    label = "wagtailmultitenancy"
    verbose_name = _("Wagtail multitenancy")
    default_auto_field = "django.db.models.AutoField"

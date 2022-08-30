import logging

from django.contrib.auth.models import Group
from django.db.models.signals import post_save

from wagtail.users.models import WagtailGroup

logger = logging.getLogger("wagtail")


def create_wagtailgroup(instance, **kwargs):
    try:
        instance.wagtailgroup
    except WagtailGroup.DoesNotExist:
        WagtailGroup.objects.create(group=instance)


def register_signal_handlers():
    post_save.connect(create_wagtailgroup, sender=Group)

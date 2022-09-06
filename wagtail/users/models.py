import os
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from wagtail.models import Tenant, TenantMember
from wagtail.multitenancy.query import TenantMemberQuerySet


def upload_avatar_to(instance, filename):
    filename, ext = os.path.splitext(filename)
    return os.path.join(
        "avatar_images",
        "avatar_{uuid}_{filename}{ext}".format(
            uuid=uuid.uuid4(), filename=filename, ext=ext
        ),
    )


class UserProfile(TenantMember):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wagtail_userprofile",
    )

    submitted_notifications = models.BooleanField(
        verbose_name=_("submitted notifications"),
        default=True,
        help_text=_("Receive notification when a page is submitted for moderation"),
    )

    approved_notifications = models.BooleanField(
        verbose_name=_("approved notifications"),
        default=True,
        help_text=_("Receive notification when your page edit is approved"),
    )

    rejected_notifications = models.BooleanField(
        verbose_name=_("rejected notifications"),
        default=True,
        help_text=_("Receive notification when your page edit is rejected"),
    )

    updated_comments_notifications = models.BooleanField(
        verbose_name=_("updated comments notifications"),
        default=True,
        help_text=_(
            "Receive notification when comments have been created, resolved, or deleted on a page that you have subscribed to receive comment notifications on"
        ),
    )

    preferred_language = models.CharField(
        verbose_name=_("preferred language"),
        max_length=10,
        help_text=_("Select language for the admin"),
        default="",
    )

    current_time_zone = models.CharField(
        verbose_name=_("current time zone"),
        max_length=40,
        help_text=_("Select your current time zone"),
        default="",
    )

    avatar = models.ImageField(
        verbose_name=_("profile picture"),
        upload_to=upload_avatar_to,
        blank=True,
    )

    @classmethod
    def get_for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]

    def grant_access_to_tenant(self, tenant, **kwargs):
        self.user.secondary_tenants.add(tenant, **kwargs)

    def get_preferred_language(self):
        return self.preferred_language or get_language()

    def get_current_time_zone(self):
        return self.current_time_zone or settings.TIME_ZONE

    def __str__(self):
        return self.user.get_username()

    class Meta:
        verbose_name = _("user profile")
        verbose_name_plural = _("user profiles")


class UserSecondaryTenantAccess(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="secondary_tenants",
    )
    tenant = models.ForeignKey(
        "wagtailcore.Tenant",
        on_delete=models.CASCADE,
        related_name="secondary_user_access",
    )

    class Meta:
        unique_together = ("user", "tenant")


class WagtailGroupQuerySet(TenantMemberQuerySet):
    def shared_with_tenant_q(self, tenant: Tenant) -> Q:
        return Q(is_global=True)


class WagtailGroup(TenantMember):

    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="wagtailgroup",
        primary_key=True,
    )

    is_global = models.BooleanField(default=False)

    objects = WagtailGroupQuerySet.as_manager()

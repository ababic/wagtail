import uuid

from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from wagtail.multitenancy import get_active_tenant, get_default_tenant_id
from wagtail.multitenancy.query import (
    TenantManager,
    TenantMemberQuerySet,
    TenantQuerySet,
)


class Tenant(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    label = models.CharField(
        verbose_name=_("label"),
        help_text=_("Human-readable name for the tenant."),
        max_length=200,
        unique=True,
    )
    hostname = models.CharField(
        verbose_name=_("hostname"),
        max_length=255,
        db_index=True,
        blank=True,
        help_text=_(
            "Optional. Set this to automatically activate the tenant based on "
            "the hostname used to acess the Wagtail admin."
        ),
    )
    port = models.IntegerField(
        verbose_name=_("port"),
        default=80,
        help_text=_(
            "Set this to something other than 80 if you need the tenant to be "
            "recognised over others when using a different port number in URLs "
            "(e.g. 8001)."
        ),
    )
    is_open = models.BooleanField(
        verbose_name=_("is open"),
        default=False,
        help_text=_(
            "Allow all Wagtail users to access this tenant without the need for "
            "explicit approval."
        ),
    )
    created = models.DateTimeField(auto_now_add=True)
    objects = TenantManager.from_queryset(TenantQuerySet)()

    class Meta:
        verbose_name = _("tenant")
        verbose_name_plural = _("tenants")
        get_latest_by = ["created"]

    @classmethod
    def get_default(cls) -> "Tenant":
        return cls.objects.get_default()

    @classmethod
    def find_for_request(cls, request: HttpRequest) -> "Tenant":
        return cls.objects.get_for_request(request)

    @property
    def is_default(self) -> bool:
        return self.id == get_default_tenant_id()

    def __str__(self) -> str:
        return self.label + (" ({})".format(_("default")) if self.is_default else "")

    def clean(self):
        super().clean()
        errors = {}

        # if the hostname is specified, the hostname and port combination must
        # be unique
        if self.hostname:
            try:
                existing = Tenant.objects.get(hostname=self.hostname, port=self.port)
            except Tenant.DoesNotExist:
                pass
            else:
                errors["hostname"] = [
                    _(
                        "%(existing)s is already using this hostname and port "
                        "combination. When specified, the combination must be "
                        "unique for each tenant."
                    )
                    % {"existing": existing}
                ]

        if errors:
            raise ValidationError(errors)

    def save(self, clean=True, *args, **kwargs):
        # Apply custom validation to help prevent misconfiguration
        # when saving outside of views (e.g. via the shell).
        if clean:
            self.full_clean()
        super().save(*args, **kwargs)

    @property
    def url(self) -> str:
        if self.port == 80:
            return f"http://{self.hostname}"
        elif self.port == 443:
            return f"https://{self.hostname}"
        return f"http://{self.hostname}:{self.port}"


class TenantMember(models.Model):
    """
    Base class for models that are grouped by Tenant
    """

    native_tenant = models.ForeignKey(
        Tenant,
        default=get_default_tenant_id,
        verbose_name=_("native tenant"),
        on_delete=models.CASCADE,
        related_name="+",
        editable=False,
    )
    tenant_shares = GenericRelation("wagtailcore.SharedTenantMember")
    objects = TenantMemberQuerySet.as_manager()

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "native_tenant" not in kwargs:
            self.native_tenant = get_active_tenant()

    def share_with_tenant(self, recipient: Tenant, **kwargs) -> "SharedTenantMember":
        return self.tenant_shares.create(
            sender=self.native_tenant, recipient=recipient, **kwargs
        )


class SharedTenantMember(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    sender = models.ForeignKey(
        Tenant, related_name="items_shared", on_delete=models.CASCADE
    )
    recipient = models.ForeignKey(
        Tenant, related_name="items_shared_with", on_delete=models.CASCADE
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=36)
    object = GenericForeignKey("content_type", "object_id")

    class Meta:
        get_latest_by = ["created"]
        unique_together = ["recipient", "content_type", "object_id"]

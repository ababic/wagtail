# Generated by Django 4.0.7 on 2022-08-28 16:05

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("wagtailcore", "0076_modellogentry_revision"),
    ]

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, primary_key=True, serialize=False
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        help_text="Human-readable name for the tenant.",
                        max_length=200,
                        unique=True,
                        verbose_name="label",
                    ),
                ),
                (
                    "hostname",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="Optional. Set this to automatically activate the tenant based on the hostname used to acess the Wagtail admin.",
                        max_length=255,
                        verbose_name="hostname",
                    ),
                ),
                (
                    "port",
                    models.IntegerField(
                        default=80,
                        help_text="Set this to something other than 80 if you need the tenant to be recognised over others when using a different port number in URLs (e.g. 8001).",
                        verbose_name="port",
                    ),
                ),
                (
                    "is_default",
                    models.BooleanField(
                        default=False,
                        help_text="Use this tenant when a more suitable one cannot be identified for a request (or, when no request is available), and as the default 'native tenant' value for multi-tenancy compatible models.",
                        verbose_name="is default tenant",
                    ),
                ),
                (
                    "is_open",
                    models.BooleanField(
                        default=False,
                        help_text="Allow all Wagtail users to access this tenant without the need for explicit approval.",
                        verbose_name="is open",
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "tenant",
                "verbose_name_plural": "tenants",
                "get_latest_by": ["created"],
            },
        ),
        migrations.CreateModel(
            name="SharedTenantMember",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("object_id", models.CharField(max_length=36)),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items_shared_with",
                        to="wagtailcore.tenant",
                    ),
                ),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items_shared",
                        to="wagtailcore.tenant",
                    ),
                ),
            ],
            options={
                "get_latest_by": ["created"],
                "unique_together": {("recipient", "content_type", "object_id")},
            },
        ),
    ]

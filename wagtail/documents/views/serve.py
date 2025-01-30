from typing import TYPE_CHECKING
from warnings import warn

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.http import quote_etag, url_has_allowed_host_and_scheme
from django.views.generic import View

from wagtail import hooks
from wagtail.documents import get_document_model
from wagtail.documents.models import document_served
from wagtail.forms import PasswordViewRestrictionForm
from wagtail.models import CollectionViewRestriction
from wagtail.utils import sendfile_streaming_backend
from wagtail.utils.deprecation import RemovedInWagtail70Warning
from wagtail.utils.sendfile import sendfile

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponseBase
    from django.http.response import HttpResponseRedirectBase

    from wagtail.documents.models import AbstractDocument


class ServeView(View):
    model = get_document_model()
    sendfile_cache_control_headers = {
        "max_age": 3600,
        "s_maxage": 3600,
        "public": True,
    }
    serve_cache_control_headers = {
        "max_age": 3600,
        "s_maxage": 3600,
        "public": True,
    }
    redirect_cache_control_headers = {
        "max_age": 3600,
        "s_maxage": 3600,
        "public": True,
    }

    def get(
        self, request: "HttpRequest", document_id: str, document_filename: str
    ) -> "HttpResponse":
        doc = self.get_document(document_id, document_filename)

        for fn in hooks.get_hooks("before_serve_document"):
            result = fn(doc, request)
            if isinstance(result, HttpResponse):
                return result

        return self.get_success_response(doc)

    def get_document(
        self, document_id: str, document_filename: str
    ) -> "AbstractDocument":
        obj = get_object_or_404(self.model, id=document_id)
        # We want to ensure that the document filename provided in the URL matches the one associated with the considered
        # document_id. If not we can't be sure that the document the user wants to access is the one corresponding to the
        # <document_id, document_filename> pair.
        if obj.filename != document_filename:
            raise Http404("Document does not match the given filename.")
        return obj

    def get_success_response(self, document: "AbstractDocument") -> "HttpResponseBase":
        # Send document_served signal
        document_served.send(sender=self.model, instance=document, request=self.request)

        # Identify the serve method to use
        method_name = self.get_serve_method(document)

        # Return a response from the relevant serve method
        return getattr(self, method_name)(document)

    def get_serve_method(self, document: "AbstractDocument") -> str:
        serve_method = getattr(settings, "WAGTAILDOCS_SERVE_METHOD", None)
        valid_methods = ("redirect", "sendfile", "serve")
        if serve_method:
            if serve_method not in valid_methods:
                raise ImproperlyConfigured(
                    f"Invalid serve method: '{serve_method}'. Valid values for the WAGTAILDOCS_SERVE_METHOD setting are: {valid_methods}"
                )
            return serve_method

        # If no serve method has been specified, select an appropriate default for the storage backend:
        # redirect for remote storages (i.e. ones that provide a url but not a local path) and
        # serve_view for all other cases
        try:
            local_path = document.file.path
        except NotImplementedError:
            local_path = None

        try:
            direct_url = document.file.url
        except NotImplementedError:
            direct_url = None

        if direct_url and not local_path:
            return "redirect"
        if local_path:
            return "sendfile"
        return "serve"

    def redirect(self, document: "AbstractDocument") -> "HttpResponseRedirectBase":
        response = redirect(document.file.url)
        response["Content-Disposition"] = document.content_disposition
        if self.redirect_cache_control_headers:
            patch_cache_control(response, **self.redirect_cache_control_headers)
        return response

    @property
    def prevent_inline_execution(self) -> bool:
        return bool(getattr(settings, "WAGTAILDOCS_BLOCK_EMBEDDED_CONTENT", True))

    def sendfile(self, document: "AbstractDocument") -> HttpResponse:
        sendfile_opts = {
            "attachment": document.content_disposition != "inline",
            "attachment_filename": document.filename,
            "mimetype": document.content_type,
        }
        if not hasattr(settings, "SENDFILE_BACKEND"):
            # Fallback to streaming backend if user hasn't specified SENDFILE_BACKEND
            sendfile_opts["backend"] = sendfile_streaming_backend.sendfile

        response = sendfile(self.request, document.file.path, **sendfile_opts)

        if self.prevent_inline_execution:
            # Add a CSP header to prevent inline execution
            response["Content-Security-Policy"] = "default-src 'none'"

        # Prevent browsers from auto-detecting the content-type of a document
        response["X-Content-Type-Options"] = "nosniff"

        response["Etag"] = quote_etag(document.file_hash)

        if self.sendfile_cache_control_headers:
            patch_cache_control(response, **self.sendfile_cache_control_headers)

        return response

    def serve(self, document: "AbstractDocument") -> FileResponse:
        document.file.open("rb")
        response = FileResponse(document.file, document.content_type)

        # Set Content-Length header from populated model field
        response["Content-Length"] = document.file_size

        # set filename and filename* to handle non-ascii characters in filename
        # see https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Disposition
        response["Content-Disposition"] = document.content_disposition

        if self.prevent_inline_execution:
            # Add a CSP header to prevent inline execution
            response["Content-Security-Policy"] = "default-src 'none'"

        # Prevent browsers from auto-detecting the content-type of a document
        response["X-Content-Type-Options"] = "nosniff"

        response["Etag"] = quote_etag(document.file_hash)

        if self.serve_cache_control_headers:
            patch_cache_control(response, **self.serve_cache_control_headers)

        return response


serve = ServeView.as_view()


def authenticate_with_password(request, restriction_id):
    """
    Handle a submission of PasswordViewRestrictionForm to grant view access over a
    subtree that is protected by a PageViewRestriction
    """
    restriction = get_object_or_404(CollectionViewRestriction, id=restriction_id)

    if request.method == "POST":
        form = PasswordViewRestrictionForm(request.POST, instance=restriction)
        if form.is_valid():
            return_url = form.cleaned_data["return_url"]

            if not url_has_allowed_host_and_scheme(
                return_url, request.get_host(), request.is_secure()
            ):
                return_url = settings.LOGIN_REDIRECT_URL

            restriction.mark_as_passed(request)
            return redirect(return_url)
    else:
        form = PasswordViewRestrictionForm(instance=restriction)

    action_url = reverse(
        "wagtaildocs_authenticate_with_password", args=[restriction.id]
    )

    password_required_template = getattr(
        settings,
        "WAGTAILDOCS_PASSWORD_REQUIRED_TEMPLATE",
        "wagtaildocs/password_required.html",
    )

    if hasattr(settings, "DOCUMENT_PASSWORD_REQUIRED_TEMPLATE"):
        warn(
            "The `DOCUMENT_PASSWORD_REQUIRED_TEMPLATE` setting is deprecated - use `WAGTAILDOCS_PASSWORD_REQUIRED_TEMPLATE` instead.",
            category=RemovedInWagtail70Warning,
        )

        password_required_template = getattr(
            settings,
            "DOCUMENT_PASSWORD_REQUIRED_TEMPLATE",
            password_required_template,
        )

    context = {"form": form, "action_url": action_url}
    return TemplateResponse(request, password_required_template, context)

"""Django email backend that takes SMTP credentials from PlatformSettings."""
import logging

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

log = logging.getLogger("servora.messaging")


class PlatformEmailBackend(SMTPBackend):
    def __init__(self, fail_silently=False, **kwargs):
        from .models import get_settings

        ps = get_settings()
        self.configured = bool(ps.email_enabled and ps.email_host)
        kwargs.setdefault("host", ps.email_host or "localhost")
        kwargs.setdefault("port", ps.email_port)
        kwargs.setdefault("username", ps.email_username)
        kwargs.setdefault("password", ps.email_password)
        kwargs.setdefault("use_ssl", ps.email_use_ssl)
        kwargs.setdefault("use_tls", ps.email_use_tls and not kwargs["use_ssl"])
        kwargs.setdefault("timeout", 10)
        super().__init__(fail_silently=fail_silently, **kwargs)

    def send_messages(self, email_messages):
        if not self.configured:
            log.info("Email not configured in platform settings; %d message(s) skipped", len(email_messages or []))
            return 0
        return super().send_messages(email_messages)

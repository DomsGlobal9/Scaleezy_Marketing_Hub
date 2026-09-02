"""
Signup alerts — how Scaleezy hears about a new client without opening the
console.

Runs in the worker (apps.users.tasks), never in the signup request. Best
effort by design: a channel that is not configured is skipped silently, and a
channel that fails is logged and reported in the task's return value — it can
never fail the signup or reveal anything to the signing-up client. The
in-console notification needs none of this: the pending count badge reads the
approval queue directly.
"""
import logging

import httpx
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"


def _alert_text(brand) -> str:
    owner = brand.created_by
    lines = [f"New Scaleezy signup: {brand.name}"]
    if brand.legal_name and brand.legal_name != brand.name:
        lines.append(f"Legal name: {brand.legal_name}")
    detail = " · ".join(filter(None, [brand.industry, brand.location]))
    if detail:
        lines.append(detail)
    if brand.website:
        lines.append(brand.website)
    contact = " · ".join(
        filter(None, [brand.contact_person, brand.contact_phone,
                      owner.email if owner else ""])
    )
    if contact:
        lines.append(f"Contact: {contact}")
    if settings.PLATFORM_URL:
        lines.append(f"Review: {settings.PLATFORM_URL.rstrip('/')}/platform/signups")
    return "\n".join(lines)


def _send_email(text: str, brand_name: str) -> str:
    if not settings.SIGNUP_ALERT_EMAILS:
        return 'skipped: SIGNUP_ALERT_EMAILS not set'
    if not settings.EMAIL_HOST:
        return 'skipped: EMAIL_HOST not set'
    try:
        sent = send_mail(
            subject=f"New client signup: {brand_name}",
            message=text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=settings.SIGNUP_ALERT_EMAILS,
        )
        if not sent:
            return 'failed: mail backend reported nothing sent'
        return f"sent to {', '.join(settings.SIGNUP_ALERT_EMAILS)}"
    except Exception as exc:
        logger.error("Signup alert email failed: %s", exc)
        return f'failed: {exc}'


def _send_whatsapp(text: str) -> list[str]:
    """One Cloud API text message per configured recipient.

    A free-form text only reaches a number that has messaged the business in
    the last 24 hours; outside that window Meta answers 131047 and the fix is
    to message the business number once from the recipient's phone (or move
    to an approved template). The full API error is logged so that case is
    diagnosable from the task record, not a mystery.
    """
    if not (settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
        return ['skipped: WhatsApp credentials not set']
    if not settings.SIGNUP_ALERT_WHATSAPP_TO:
        return ['skipped: SIGNUP_ALERT_WHATSAPP_TO not set']

    url = (
        f"{GRAPH_URL}/{settings.META_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    results = []
    for recipient in settings.SIGNUP_ALERT_WHATSAPP_TO:
        try:
            response = httpx.post(
                url,
                headers={'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}'},
                json={
                    'messaging_product': 'whatsapp',
                    'to': recipient,
                    'type': 'text',
                    'text': {'body': text},
                },
                timeout=15.0,
            )
            if response.is_success:
                results.append(f'{recipient}: sent')
            else:
                logger.error(
                    "Signup alert WhatsApp to %s refused: %s", recipient, response.text
                )
                results.append(f'{recipient}: refused ({response.status_code})')
        except Exception as exc:
            logger.error("Signup alert WhatsApp to %s failed: %s", recipient, exc)
            results.append(f'{recipient}: failed ({exc})')
    return results


def send_signup_alerts(brand_id: str) -> dict:
    from apps.brands.models import Brand

    brand = Brand.objects.select_related('created_by').filter(pk=brand_id).first()
    if brand is None:
        # The signup rolled back or the brand is gone; nothing to announce.
        return {'skipped': 'brand not found'}

    text = _alert_text(brand)
    return {
        'email': _send_email(text, brand.name),
        'whatsapp': _send_whatsapp(text),
    }

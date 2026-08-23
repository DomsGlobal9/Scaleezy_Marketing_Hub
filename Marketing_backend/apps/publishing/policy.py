"""Server-side enforcement for the settings shown on social accounts."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from apps.social_accounts.models import SocialAccountSettings


class PublishingPolicyError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _settings_for(connection):
    try:
        return connection.settings
    except SocialAccountSettings.DoesNotExist:
        return None


def _zone(name: str):
    try:
        return ZoneInfo(name or 'UTC')
    except ZoneInfoNotFoundError:
        return ZoneInfo('UTC')


def _inside_window(value: time, start: time | None, end: time | None) -> bool:
    if start is None or end is None or start == end:
        return True
    if start < end:
        return start <= value <= end
    return value >= start or value <= end


def enforce_connection_policy(connection, *, at=None, check_daily_limit=True):
    """Raise with a stable code when this account may not publish at ``at``."""
    settings = _settings_for(connection)
    if settings is None:
        return

    if settings.publishing_paused:
        raise PublishingPolicyError(
            'PUBLISHING_PAUSED',
            f'Publishing is paused for {connection.account_name}.',
        )

    instant = at or timezone.now()
    local = timezone.localtime(instant, _zone(settings.timezone))
    if not _inside_window(local.time(), settings.allowed_start_time, settings.allowed_end_time):
        raise PublishingPolicyError(
            'OUTSIDE_PUBLISHING_WINDOW',
            f'{connection.account_name} is outside its allowed publishing window.',
        )

    if not check_daily_limit:
        return
    limit = max(0, int(settings.daily_post_limit))
    local_start = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
    local_end = local_start + timedelta(days=1)
    published = connection.publishing_job_items.filter(
        status='PUBLISHED',
        published_at__gte=local_start.astimezone(ZoneInfo('UTC')),
        published_at__lt=local_end.astimezone(ZoneInfo('UTC')),
    ).count()
    if published >= limit:
        raise PublishingPolicyError(
            'DAILY_POST_LIMIT_REACHED',
            f'{connection.account_name} has reached its daily post limit ({limit}).',
        )


def automatic_retry_enabled(connection) -> bool:
    settings = _settings_for(connection)
    # Automatic retries are an operator-controlled behaviour. Connections
    # created before settings existed keep their historical one-shot publish
    # semantics until an explicit settings row enables retries.
    return bool(settings and settings.automatic_retry_enabled)

"""Durable social inbox sync, provider-neutral drafting and honest replies."""
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.ai.models import Capability
from apps.ai.router import AIRouter
from apps.context.services.context_gateway import TaskType, build_generation_context, context_as_brief
from apps.social_accounts.integrations.x import XAdapter
from apps.social_accounts.integrations.youtube.youtube import YouTubeAdapter
from apps.social_accounts.models import SocialConnection
from apps.social_accounts.utils.encryption import decrypt_token

from .models import EngagementItem, EngagementSyncRun


class EngagementError(Exception):
    pass


def _adapter_for(platform):
    if platform == SocialConnection.Platform.X:
        return XAdapter()
    if platform == SocialConnection.Platform.YOUTUBE:
        return YouTubeAdapter()
    return None


def sync_inbox(run_id):
    run = EngagementSyncRun.objects.select_related(
        'workspace', 'brand', 'social_connection'
    ).get(pk=run_id)
    if run.status not in (EngagementSyncRun.Status.QUEUED, EngagementSyncRun.Status.FAILED):
        return {'status': run.status, 'imported': run.imported_count}
    run.status = EngagementSyncRun.Status.PROCESSING
    run.started_at = timezone.now()
    run.completed_at = None
    run.error = ''
    run.save(update_fields=['status', 'started_at', 'completed_at', 'error', 'updated_at'])

    try:
        connection = run.social_connection
        if connection.status != SocialConnection.Status.CONNECTED:
            raise EngagementError('The social account must be connected before inbox sync.')
        adapter = _adapter_for(connection.platform)
        if adapter is None:
            raise EngagementError(
                f'Inbox sync for {connection.get_platform_display()} is not available yet.'
            )
        token = decrypt_token(connection.access_token_encrypted)
        if not token:
            raise EngagementError('The social account must be reconnected.')

        if connection.platform == SocialConnection.Platform.X:
            payload = adapter.fetch_mentions(
                token, connection.external_account_id, cursor=run.cursor
            )
        else:
            payload = adapter.fetch_comments(
                token, connection.external_account_id, cursor=run.cursor
            )

        created = 0
        rows = payload.get('items') if isinstance(payload, dict) else []
        for row in rows[:100] if isinstance(rows, list) else []:
            external_id = str(row.get('external_id') or '')[:255]
            body = str(row.get('body') or '')[:10000]
            if not external_id or not body:
                continue
            occurred_at = parse_datetime(str(row.get('occurred_at') or '')) or timezone.now()
            _, was_created = EngagementItem.objects.get_or_create(
                social_connection=connection,
                external_id=external_id,
                defaults={
                    'workspace': run.workspace,
                    'brand': run.brand,
                    'platform': connection.platform,
                    'kind': row.get('kind') or EngagementItem.Kind.COMMENT,
                    'thread_id': str(row.get('thread_id') or '')[:255],
                    'author_name': str(row.get('author_name') or '')[:255],
                    'author_handle': str(row.get('author_handle') or '')[:255],
                    'body': body,
                    'source_url': str(row.get('source_url') or '')[:1000],
                    'occurred_at': occurred_at,
                    'source_payload': row.get('source_payload') if isinstance(row.get('source_payload'), dict) else {},
                },
            )
            created += int(was_created)

        run.status = EngagementSyncRun.Status.COMPLETED
        run.cursor = str(payload.get('cursor') or '')[:500]
        run.imported_count = created
        run.seen_count = len(rows) if isinstance(rows, list) else 0
        run.completed_at = timezone.now()
        run.save(update_fields=[
            'status', 'cursor', 'imported_count', 'seen_count',
            'completed_at', 'updated_at',
        ])
        return {'status': run.status, 'imported': created, 'seen': run.seen_count}
    except Exception as exc:
        run.status = EngagementSyncRun.Status.FAILED
        run.error = str(exc)[:1000]
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
        raise


def draft_reply(item_id):
    item = EngagementItem.objects.select_related('workspace', 'brand').get(pk=item_id)
    if item.status in (EngagementItem.Status.RESOLVED, EngagementItem.Status.IGNORED):
        raise EngagementError('Closed engagement cannot receive a new draft.')
    item.draft_status = EngagementItem.DraftStatus.PROCESSING
    item.last_error = ''
    item.save(update_fields=['draft_status', 'last_error', 'updated_at'])
    try:
        context = context_as_brief(
            build_generation_context(item.workspace, item.brand, TaskType.COPY)
        )
        result = AIRouter(item.workspace).dispatch(
            Capability.ENGAGEMENT_RESPONSE,
            {
                'task': 'DRAFT_SOCIAL_RESPONSE',
                'brand_context': context,
                'platform': item.platform,
                'kind': item.kind,
                'author': item.author_handle or item.author_name,
                'message': item.body,
                'requirements': [
                    'Do not invent facts or commitments.',
                    'Escalate legal, safety, refund and crisis risk.',
                    'Return a draft only; a human decides whether to send it.',
                ],
            },
        )
        sentiment = str(result.get('sentiment') or '').upper()
        urgency = str(result.get('urgency') or '').upper()
        item.ai_draft = str(result.get('reply') or '')[:5000]
        if not item.ai_draft:
            raise EngagementError('The provider returned no reply draft.')
        item.ai_provider_key = str(result.get('provider') or '')[:100]
        item.ai_provider_name = str(result.get('provider_name') or '')[:100]
        item.ai_risk_flags = [str(v)[:255] for v in (result.get('risk_flags') or [])[:12]]
        if sentiment in EngagementItem.Sentiment.values:
            item.sentiment = sentiment
        if urgency in EngagementItem.Urgency.values:
            item.urgency = urgency
        item.draft_status = EngagementItem.DraftStatus.READY
        item.status = EngagementItem.Status.AWAITING_APPROVAL
        item.save(update_fields=[
            'ai_draft', 'ai_provider_key', 'ai_provider_name', 'ai_risk_flags',
            'sentiment', 'urgency', 'draft_status', 'status', 'updated_at',
        ])
        return {'status': item.draft_status, 'item_id': str(item.pk)}
    except Exception as exc:
        item.draft_status = EngagementItem.DraftStatus.FAILED
        item.last_error = str(exc)[:1000]
        item.save(update_fields=['draft_status', 'last_error', 'updated_at'])
        raise


def send_approved_reply(item):
    if item.status not in (
        EngagementItem.Status.APPROVED, EngagementItem.Status.SENDING
    ) or not item.approved_response.strip():
        raise EngagementError('Only an approved response can be sent.')
    connection = item.social_connection
    if connection.status != SocialConnection.Status.CONNECTED:
        raise EngagementError('The social account must be reconnected before replying.')
    adapter = _adapter_for(connection.platform)
    if adapter is None:
        raise EngagementError(f'Replies for {connection.get_platform_display()} are not available yet.')
    token = decrypt_token(connection.access_token_encrypted)
    if not token:
        raise EngagementError('The social account must be reconnected before replying.')
    if connection.platform == SocialConnection.Platform.X:
        result = adapter.reply_to_post(token, item.external_id, item.approved_response)
    else:
        result = adapter.reply_to_comment(token, item.external_id, item.approved_response)
    if not isinstance(result, dict) or not str(result.get('id') or '').strip():
        raise EngagementError(
            'The platform did not confirm the reply. Nothing was marked sent.'
        )
    return result

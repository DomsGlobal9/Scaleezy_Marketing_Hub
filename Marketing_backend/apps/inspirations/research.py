"""Provider-neutral public-web discovery with verified source lineage."""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.ai.models import Capability
from apps.ai.router import AIRouter
from apps.context.services.context_gateway import TaskType, build_generation_context, context_as_brief
from apps.universal.enrichment import assert_safe, registrable_host, safe_fetch

from .models import ResearchFinding, ResearchRun


MAX_FINDINGS = 16
ALLOWED_KINDS = set(ResearchFinding.Kind.values)


class ResearchError(Exception):
    pass


def _normalized_url(value):
    raw = str(value or '').strip()
    parts = urlsplit(raw)
    if parts.scheme != 'https' or not parts.hostname:
        return ''
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))


def _rows(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    rows = payload.get('findings') if isinstance(payload, dict) else None
    return rows[:MAX_FINDINGS] if isinstance(rows, list) else []


def execute_research(run_id):
    run = ResearchRun.objects.select_related('workspace', 'brand').get(pk=run_id)
    if run.status not in (ResearchRun.Status.QUEUED, ResearchRun.Status.FAILED):
        return {'status': run.status, 'findings': run.result_count}

    run.status = ResearchRun.Status.PROCESSING
    run.started_at = timezone.now()
    run.completed_at = None
    run.error = ''
    run.save(update_fields=['status', 'started_at', 'completed_at', 'error', 'updated_at'])

    try:
        brand_context = context_as_brief(
            build_generation_context(run.workspace, run.brand, TaskType.COPY)
        )
        result = AIRouter(run.workspace).dispatch(
            Capability.RESEARCH,
            {
                'task': 'PUBLIC_CREATIVE_RESEARCH',
                'query': run.query,
                'objectives': run.objectives,
                'preferred_sources': run.sources,
                'brand_context': brand_context,
                'max_findings': MAX_FINDINGS,
                'requirements': [
                    'Every finding must cite a public HTTPS source URL.',
                    'Return references, not copied assets.',
                    'Do not infer or grant usage rights.',
                ],
            },
        )

        created = 0
        for row in _rows(result):
            if not isinstance(row, dict):
                continue
            source_url = _normalized_url(row.get('source_url'))
            title = ' '.join(str(row.get('title') or '').split())[:255]
            if not source_url or not title:
                continue
            dedupe_key = hashlib.sha256(source_url.casefold().encode('utf-8')).hexdigest()
            host = registrable_host(source_url)
            verification = ResearchFinding.VerificationStatus.VERIFIED
            verification_error = ''
            content_hash = ''
            try:
                _text, content_hash = safe_fetch(source_url, allowed_host=host)
            except Exception as exc:
                verification = ResearchFinding.VerificationStatus.FAILED
                verification_error = str(exc)[:500]

            preview_url = _normalized_url(row.get('preview_url'))
            if preview_url:
                try:
                    assert_safe(preview_url, allowed_host=registrable_host(preview_url))
                except Exception:
                    preview_url = ''

            kind = str(row.get('kind') or '').upper()
            if kind not in ALLOWED_KINDS:
                kind = ResearchFinding.Kind.OTHER
            observed_at = parse_datetime(str(row.get('observed_at') or ''))
            _, was_created = ResearchFinding.objects.get_or_create(
                run=run,
                dedupe_key=dedupe_key,
                defaults={
                    'workspace': run.workspace,
                    'brand': run.brand,
                    'kind': kind,
                    'title': title,
                    'source_url': source_url,
                    'preview_url': preview_url,
                    'source_name': ' '.join(str(row.get('source_name') or '').split())[:255],
                    'platform': ' '.join(str(row.get('platform') or '').split())[:100],
                    'excerpt': ' '.join(str(row.get('excerpt') or '').split())[:2000],
                    'observed_at': observed_at,
                    'rights_status': ResearchFinding.RightsStatus.UNKNOWN,
                    'verification_status': verification,
                    'verification_error': verification_error,
                    'source_content_hash': content_hash,
                    'metadata': {'provider_metadata': result.get('raw') or {}},
                },
            )
            created += int(was_created)

        total = run.findings.count()
        verified = run.findings.filter(
            verification_status=ResearchFinding.VerificationStatus.VERIFIED
        ).count()
        run.status = (
            ResearchRun.Status.NEEDS_REVIEW if verified else ResearchRun.Status.COMPLETED
        )
        run.result_count = total
        run.provider_key = str(result.get('provider') or '')[:100]
        run.provider_name = str(result.get('provider_name') or '')[:100]
        run.completed_at = timezone.now()
        run.save(update_fields=[
            'status', 'result_count', 'provider_key', 'provider_name',
            'completed_at', 'updated_at',
        ])
        return {'status': run.status, 'findings': total, 'created': created}
    except Exception as exc:
        run.status = ResearchRun.Status.FAILED
        run.error = str(exc)[:1000]
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'error', 'completed_at', 'updated_at'])
        raise


KIND_TO_INSPIRATION = {
    ResearchFinding.Kind.POSTER: 'IMAGE',
    ResearchFinding.Kind.SOCIAL_POST: 'POST',
    ResearchFinding.Kind.VIDEO: 'VIDEO',
    ResearchFinding.Kind.CAMPAIGN: 'AD',
    ResearchFinding.Kind.COMPETITOR: 'COMPETITOR',
    ResearchFinding.Kind.TREND: 'REFERENCE',
    ResearchFinding.Kind.HOOK: 'TEXT',
    ResearchFinding.Kind.OTHER: 'REFERENCE',
}


@transaction.atomic
def adopt_finding(finding, *, user, annotation='', usage_scope='FULL_REFERENCE', focus_areas=None):
    from .models import BrandInspiration

    finding = ResearchFinding.objects.select_for_update().select_related(
        'run', 'workspace', 'brand', 'adopted_inspiration'
    ).get(pk=finding.pk)
    if finding.adopted_inspiration_id:
        return finding.adopted_inspiration, False
    if finding.verification_status != ResearchFinding.VerificationStatus.VERIFIED:
        raise ResearchError('Only a verified public source can be adopted.')
    if finding.rights_status == ResearchFinding.RightsStatus.RESTRICTED:
        raise ResearchError('This source is marked restricted and cannot be adopted.')

    inspiration = BrandInspiration.objects.create(
        workspace=finding.workspace,
        brand=finding.brand,
        inspiration_type=KIND_TO_INSPIRATION.get(
            finding.kind, BrandInspiration.InspirationType.REFERENCE
        ),
        title=finding.title,
        annotation=str(annotation or finding.excerpt)[:4000],
        reference_url=finding.source_url,
        external_platform=finding.platform,
        usage_scope=usage_scope,
        focus_areas=focus_areas or [],
        metadata={
            'research_finding_id': str(finding.pk),
            'research_run_id': str(finding.run_id),
            'source_name': finding.source_name,
            'rights_status': finding.rights_status,
            'source_content_hash': finding.source_content_hash,
            'observed_at': finding.observed_at.isoformat() if finding.observed_at else None,
        },
        created_by=user,
    )
    finding.adopted_inspiration = inspiration
    finding.adopted_by = user
    finding.adopted_at = timezone.now()
    finding.save(update_fields=['adopted_inspiration', 'adopted_by', 'adopted_at', 'updated_at'])
    return inspiration, True

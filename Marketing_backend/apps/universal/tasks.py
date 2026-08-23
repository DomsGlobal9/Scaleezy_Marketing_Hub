from datetime import timedelta

from django.contrib.auth import get_user_model
from django.tasks import task
from django.utils import timezone

from apps.audit.models import record_platform_event

from .aggregation import compile_learned_patterns


@task
def compile_learned_patterns_task(actor_id=None):
    result = compile_learned_patterns()
    actor = get_user_model().objects.filter(pk=actor_id).first() if actor_id else None
    record_platform_event(
        actor=actor,
        action='LEARNED_PATTERNS_COMPILED',
        target=f"pattern-version:{result['pattern_version']}",
        detail=result,
    )
    return result


@task
def refresh_brand_site_task(brand_id: str):
    """Fetch one approved client's own site and queue changed pages for extraction."""
    from apps.brands.models import Brand
    from apps.knowledge.tasks import process_source_task
    from apps.workspaces.models import MarketingWorkspace
    from .enrichment import enrich_brand_from_own_site

    brand = Brand.objects.select_related('workspace').get(pk=brand_id)
    if (
        brand.status != Brand.Status.ACTIVE
        or brand.workspace.status != MarketingWorkspace.Status.ACTIVE
        or brand.workspace.kind != MarketingWorkspace.Kind.CLIENT
        or brand.workspace.approval_status != MarketingWorkspace.Approval.APPROVED
        or not brand.website
    ):
        return {'brand': str(brand.pk), 'skipped': 'INELIGIBLE'}
    report = enrich_brand_from_own_site(brand.workspace, brand)
    for source_id in report.get('sources_created') or []:
        process_source_task.enqueue(str(source_id))
    return {'brand': str(brand.pk), **report}


@task
def refresh_due_brands_task():
    """Queue one bounded refresh per brand when no own-site capture ran this week."""
    from apps.brands.models import Brand
    from apps.workspaces.models import MarketingWorkspace

    cutoff = timezone.now() - timedelta(days=7)
    queued = 0
    brands = Brand.objects.select_related('workspace').filter(
        status=Brand.Status.ACTIVE,
        workspace__status=MarketingWorkspace.Status.ACTIVE,
        workspace__kind=MarketingWorkspace.Kind.CLIENT,
        workspace__approval_status=MarketingWorkspace.Approval.APPROVED,
    ).exclude(website='')
    for brand in brands.iterator():
        recently_captured = brand.knowledge_sources.filter(
            metadata__origin='DISCOVERED', created_at__gte=cutoff
        ).exists()
        if recently_captured:
            continue
        refresh_brand_site_task.enqueue(str(brand.pk))
        queued += 1
    return {'queued': queued}


def enqueue_due_enrichment(now=None):
    """At most one platform-wide enrichment sweep per day."""
    from apps.brands.models import Brand
    from apps.jobs.models import TaskRun
    from apps.workspaces.models import MarketingWorkspace

    now = now or timezone.now()
    eligible = Brand.objects.filter(
        status=Brand.Status.ACTIVE,
        workspace__status=MarketingWorkspace.Status.ACTIVE,
        workspace__kind=MarketingWorkspace.Kind.CLIENT,
        workspace__approval_status=MarketingWorkspace.Approval.APPROVED,
    ).exclude(website='').exists()
    if not eligible:
        return 0
    path = 'apps.universal.tasks.refresh_due_brands_task'
    if TaskRun.objects.filter(
        task_path=path, enqueued_at__gte=now - timedelta(days=1)
    ).exists():
        return 0
    refresh_due_brands_task.enqueue()
    return 1

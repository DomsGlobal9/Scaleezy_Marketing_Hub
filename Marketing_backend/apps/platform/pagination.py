"""Opt-in bounded pages for console lists; legacy response shapes stay intact."""
from django.db.models import Count


def wants_page(request):
    return 'page' in request.query_params or 'page_size' in request.query_params


def _integer(value, default, maximum):
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError, OverflowError):
        return default


def page_rows(request, queryset, *, legacy_limit=500):
    if not wants_page(request):
        return list(queryset[:legacy_limit]), {}
    page = _integer(request.query_params.get('page'), 1, 1_000_000)
    size = _integer(request.query_params.get('page_size'), 25, 200)
    total = queryset.count()
    pages = (total + size - 1) // size
    offset = (page - 1) * size
    return list(queryset[offset:offset + size]), {
        'page': page, 'page_size': size, 'total': total, 'total_pages': pages,
        'next_page': page + 1 if page < pages else None,
        'previous_page': page - 1 if page > 1 else None,
    }


def facet_counts(queryset, field):
    counts = {
        row[field]: row['total']
        for row in queryset.order_by().values(field).annotate(total=Count('pk'))
    }
    return {'ALL': sum(counts.values()), **counts}

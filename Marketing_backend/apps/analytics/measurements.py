"""Measurement availability without rewriting historical source evidence."""
from collections import defaultdict
from decimal import Decimal

METRIC_FIELDS = ('impressions', 'reach', 'engagement', 'clicks', 'conversions')


def measured_fields(observation):
    payload = observation.source_payload or {}
    explicit = payload.get('measured_fields')
    known = {field for field in METRIC_FIELDS if getattr(observation, field) != 0}
    if isinstance(explicit, list):
        return known | set(explicit).intersection(METRIC_FIELDS)
    # Legacy non-zero values are evidence; a default zero alone is not.
    if observation.source == 'X_API':
        metrics = payload.get('public_metrics') or {}
        if metrics.get('impression_count') is not None:
            known.update(('impressions', 'reach'))
        if any(metrics.get(key) is not None for key in (
            'like_count', 'reply_count', 'retweet_count', 'quote_count', 'bookmark_count'
        )):
            known.add('engagement')
    elif observation.source == 'YOUTUBE_API':
        metrics = payload.get('statistics') or {}
        if metrics.get('viewCount') is not None:
            known.add('reach')
        if any(metrics.get(key) is not None for key in ('likeCount', 'commentCount', 'favoriteCount')):
            known.add('engagement')
        # Preserve historical non-zero evidence; missing/default zero
        # impressions are not evidence of a measured zero.
    return known


def summarize(rows, fields=('reach', 'engagement', 'clicks', 'conversions')):
    rows = list(rows)
    available = [(row, measured_fields(row)) for row in rows]
    values = {}
    coverage = {}
    for field in fields:
        measured = [row for row, known in available if field in known]
        coverage[field] = {'measured': len(measured), 'total': len(rows)}
        # A partial sum must not masquerade as a complete total.
        values[field] = sum(getattr(row, field) for row in measured) if rows and len(measured) == len(rows) else None
    return {**values, 'measurement_coverage': coverage}


def dashboard_measurements(rows):
    by_day = defaultdict(list)
    by_platform = defaultdict(list)
    for row in rows:
        by_day[row.observed_at.date()].append(row)
        by_platform[row.platform].append(row)
    return {
        'trend': [
            {'date': day, **summarize(group), 'posts_published': None}
            for day, group in sorted(by_day.items())
        ],
        'platform_perf': [
            {'id': platform, 'platform': platform, **summarize(group), 'roi_multiplier': None}
            for platform, group in sorted(by_platform.items())
        ],
        'totals': summarize(rows),
    }


def campaign_returns(observations, events):
    """Ratios only within one source currency, never an implied FX rate."""
    spend = defaultdict(lambda: Decimal('0'))
    revenue = defaultdict(lambda: Decimal('0'))
    for row in observations:
        if row.campaign_name and row.spend:
            spend[(row.campaign_name, row.currency)] += row.spend
    for event in events:
        if event.campaign_name:
            revenue[(event.campaign_name, event.currency)] += event.amount
    return [
        {'id': f'{name}:{currency}', 'campaign_name': name, 'currency': currency,
         'roi_multiplier': float(revenue[(name, currency)] / spend[(name, currency)])
         if spend[(name, currency)] > 0 and (name, currency) in revenue else None}
        for name, currency in sorted(set(spend) | set(revenue))
    ]

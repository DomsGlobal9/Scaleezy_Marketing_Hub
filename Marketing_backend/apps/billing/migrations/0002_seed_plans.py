"""
Seeds the plan catalogue.

Deliberately does NOT create a Subscription for anybody. Every existing
workspace predates this table, and a billing migration that quietly enrolled
them all would turn a deploy into an outage the moment someone hit a limit
they never agreed to. An unsubscribed workspace stays unlimited; enrolling one
is an explicit act in the admin.
"""
from django.db import migrations

PLANS = [
    {
        'key': 'free',
        'name': 'Free',
        'description': 'Trial allowance for evaluating the hub.',
        'monthly_generations': 30,
        'monthly_spend_cap': '5.00',
        'max_scheduled_jobs': 10,
        'price': '0.00',
        'is_default': True,
        'position': 0,
    },
    {
        'key': 'studio',
        'name': 'Studio',
        'description': 'For a single brand publishing regularly.',
        'monthly_generations': 300,
        'monthly_spend_cap': '50.00',
        'max_scheduled_jobs': 100,
        'price': '49.00',
        'is_default': False,
        'position': 1,
    },
    {
        'key': 'agency',
        'name': 'Agency',
        'description': 'Multiple brands, uncapped generation.',
        'monthly_generations': 0,
        'monthly_spend_cap': '0.00',
        'max_scheduled_jobs': 0,
        'price': '199.00',
        'is_default': False,
        'position': 2,
    },
]


def seed(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for plan in PLANS:
        Plan.objects.get_or_create(key=plan['key'], defaults=plan)


def unseed(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    # PROTECT on Subscription.plan means a plan in use will refuse to go, which
    # is the correct outcome for a rollback.
    Plan.objects.filter(
        key__in=[p['key'] for p in PLANS], subscriptions__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('billing', '0001_initial')]

    operations = [migrations.RunPython(seed, unseed)]

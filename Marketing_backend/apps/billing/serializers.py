from rest_framework import serializers

from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'key', 'name', 'description', 'monthly_generations',
            'monthly_spend_cap', 'max_scheduled_jobs', 'price', 'is_default',
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id', 'plan', 'status', 'period_start', 'period_end',
            'generations_override', 'spend_cap_override',
        ]
        read_only_fields = fields

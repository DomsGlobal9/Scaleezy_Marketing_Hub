from rest_framework import serializers

from apps.common.permissions import get_request_workspace
from apps.gemini.limits import MAX_GENERATION_INSTRUCTION_CHARS
from apps.social_accounts.models import SocialConnection

from .models import AutopilotPolicy, AutopilotRun, AutopilotStep
from .services import PRODUCIBLE_FORMATS, tidy_campaign_brief


def _refusal(field, code, message):
    """A refusal the Missions panel can show. Its client (lib/api.ts) reads
    `error.message` and `error.code` - the envelope the trigger action
    answers with - never a DRF field map, so a field-keyed error alone
    reached the user as "Request failed (400)". The field entry stays for
    API callers that do read the map."""
    return serializers.ValidationError({
        field: [message], 'error': {'code': code, 'message': message},
    })


class AutopilotStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutopilotStep
        fields = ['id', 'key', 'status', 'detail', 'created_at', 'updated_at']


class AutopilotPolicySerializer(serializers.ModelSerializer):
    social_connections = serializers.PrimaryKeyRelatedField(
        queryset=SocialConnection.objects.all(), many=True, required=False
    )

    class Meta:
        model = AutopilotPolicy
        fields = [
            'id', 'brand', 'name', 'objective', 'campaign_brief', 'mode',
            'cadence', 'next_run_at', 'allowed_formats', 'social_connections',
            'daily_generation_limit', 'monthly_spend_cap', 'enabled', 'paused',
            'emergency_stop', 'created_at', 'updated_at',
        ]
        # next_run_at stays read-only: the model owns its lifecycle (armed one
        # interval out on save, advanced by the sweep) and a client writing it
        # directly could schedule immediate spend.
        read_only_fields = [
            'next_run_at', 'emergency_stop', 'created_at', 'updated_at'
        ]

    def validate(self, attrs):
        request = self.context['request']
        workspace, error = get_request_workspace(request)
        if error:
            raise serializers.ValidationError('No accessible workspace selected.')
        brand = attrs.get('brand') or getattr(self.instance, 'brand', None)
        if brand is None or brand.workspace_id != workspace.id:
            raise serializers.ValidationError({'brand': 'Brand must belong to the selected client.'})
        connections = attrs.get('social_connections', [])
        if any(connection.workspace_id != workspace.id for connection in connections):
            raise serializers.ValidationError({
                'social_connections': 'Every social account must belong to the selected client.'
            })
        # Only a written allowed_formats is judged: a policy saved with
        # CAROUSEL before autopilot refused it must stay pausable and
        # editable, and its runs fail honestly at runtime (FORMAT_UNSUPPORTED)
        # until the formats are fixed.
        if 'allowed_formats' in attrs:
            formats = attrs['allowed_formats']
            if not isinstance(formats, list):
                raise serializers.ValidationError({'allowed_formats': 'Choose a list of formats.'})
            unsupported = sorted(set(map(str.upper, map(str, formats))) - set(PRODUCIBLE_FORMATS))
            if unsupported:
                raise _refusal(
                    'allowed_formats', 'FORMAT_UNSUPPORTED',
                    f"Autopilot cannot produce {', '.join(unsupported)} yet. "
                    f"Choose from: {', '.join(PRODUCIBLE_FORMATS)}.",
                )
        # The studio's cap, judged on the text the worker will read: a brief
        # past it was silently cut at run time, and the cut could fall inside
        # a labelled line ("Offer: ...") that then generated in part.
        brief = attrs.get('campaign_brief')
        if brief is not None and len(tidy_campaign_brief(brief)) > MAX_GENERATION_INSTRUCTION_CHARS:
            raise _refusal(
                'campaign_brief', 'CAMPAIGN_BRIEF_TOO_LONG',
                f'The campaign brief must be {MAX_GENERATION_INSTRUCTION_CHARS} '
                'characters or fewer.',
            )
        return attrs


class AutopilotRunSerializer(serializers.ModelSerializer):
    policy_name = serializers.CharField(source='policy.name', read_only=True)
    mode = serializers.CharField(source='policy.mode', read_only=True)
    steps = AutopilotStepSerializer(many=True, read_only=True)

    class Meta:
        model = AutopilotRun
        fields = [
            'id', 'policy', 'policy_name', 'mode', 'status', 'scheduled_for',
            'policy_snapshot', 'generation_request', 'content_item', 'task_id',
            'next_check_at', 'error_code', 'error', 'started_at', 'completed_at',
            'created_at', 'updated_at', 'steps',
        ]

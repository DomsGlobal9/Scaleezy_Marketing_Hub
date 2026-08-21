"""
Shared tenancy/RBAC assertions for API tests.

Every tenant-owned domain in this project has to defend the same short list of
attacks, and each one has been re-hand-written per app so far. The cost of that
is not typing: it is that a negative test which asserts only a 400 looks
identical to one that also proves nothing was written, and the weaker version
keeps getting copied. These helpers assert the response **and** the database
every time, so the strong version is the cheap one.

Deliberately not generic beyond that. Each helper names the attack it defends
(`assert_cross_brand_fk_rejected`, not `assert_bad_request`) so a reader can
tell from the call site which rule is under test, and endpoint-specific
semantics — which status, which error key, which state machine — stay in the
calling test where they belong.

Used by `apps.inspirations.tests`; intended for the tenant-owned domains
arriving in PR3 onwards.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from apps.workspaces.models import MarketingWorkspace, WorkspaceMember

User = get_user_model()


def workspace_header(workspace):
    return {'HTTP_X_WORKSPACE_ID': str(workspace.id)}


def error_body(response):
    """The field-error mapping, whichever envelope the view used.

    DRF's ModelViewSet returns `{field: [...]}` directly; the custom actions
    wrap it as `{success: false, error: {field: [...]}}` via `APIResponse`.
    A helper that understood only one of them would silently pass on the other.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    if isinstance(body, dict) and isinstance(body.get('error'), dict):
        return body['error']
    return body if isinstance(body, dict) else {}


def field_value(instance, field):
    """`brand` reads back as `brand_id`; plain fields read back as themselves."""
    return getattr(instance, f'{field}_id', None) or getattr(instance, field, None)


class TenantFixtureMixin:
    """Workspace/brand/member construction, so each app stops reinventing it."""

    def make_workspace(self, name, customer_id):
        return MarketingWorkspace.objects.create(
            customer_id=customer_id, workspace_name=name
        )

    def authenticate_as(self, workspace, role, username):
        """A user with `role` in `workspace`, and a client already signed in."""
        user = User.objects.create_user(username=username, password='pw')
        WorkspaceMember.objects.create(workspace=workspace, user=user, role=role)
        client = APIClient()
        client.force_authenticate(user=user)
        return user, client


class TenantSecurityAssertions:
    """Attack assertions. Each proves the response *and* that nothing moved."""

    # --- creation attacks -------------------------------------------------

    def assert_create_rejected(
        self, *, client, url, payload, workspace, model, error_field,
        why, expected_status=status.HTTP_400_BAD_REQUEST, format='json',
    ):
        before = model.objects.count()
        response = client.post(
            url, payload, format=format, **workspace_header(workspace)
        )
        self.assertEqual(
            response.status_code, expected_status,
            f"{why}: expected {expected_status}, got {response.status_code} "
            f"({response.content[:300]})",
        )
        self.assertIn(
            error_field, error_body(response),
            f"{why}: rejection did not name '{error_field}' ({response.content[:300]})",
        )
        self.assertEqual(
            model.objects.count(), before,
            f"{why}: request was rejected but a {model.__name__} row was still created",
        )
        return response

    def assert_cross_tenant_fk_rejected(
        self, *, client, url, payload, workspace, model, field, foreign_id,
        format='json',
    ):
        """Submitting another tenant's object id in a foreign key."""
        return self.assert_create_rejected(
            client=client, url=url, workspace=workspace, model=model,
            payload={**payload, field: str(foreign_id)}, error_field=field,
            why=f"cross-tenant {field}", format=format,
        )

    def assert_cross_brand_fk_rejected(
        self, *, client, url, payload, workspace, model, field, foreign_id,
        format='json',
    ):
        """Same workspace, wrong brand — workspace equality alone is not enough."""
        return self.assert_create_rejected(
            client=client, url=url, workspace=workspace, model=model,
            payload={**payload, field: str(foreign_id)}, error_field=field,
            why=f"cross-brand {field}", format=format,
        )

    # --- role attacks -----------------------------------------------------

    def assert_viewer_mutation_denied(
        self, *, client, method, url, workspace, model, payload=None, format='json',
    ):
        before = model.objects.count()
        send = getattr(client, method)
        response = (
            send(url, payload, format=format, **workspace_header(workspace))
            if payload is not None
            else send(url, **workspace_header(workspace))
        )
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            f"viewer {method.upper()} {url}: expected 403, got "
            f"{response.status_code} ({response.content[:300]})",
        )
        self.assertEqual(
            model.objects.count(), before,
            f"viewer {method.upper()} {url} was denied but still changed the table",
        )
        return response

    # --- mutation attacks on existing rows --------------------------------

    def assert_field_immutable(
        self, *, client, url, instance, field, new_value, workspace, method='patch',
    ):
        """A field that may be set at creation and never moved afterwards."""
        original = field_value(instance, field)
        response = getattr(client, method)(
            url, {field: str(new_value)}, format='json', **workspace_header(workspace)
        )
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST,
            f"{method.upper()} of immutable '{field}': expected 400, got "
            f"{response.status_code} ({response.content[:300]})",
        )
        instance.refresh_from_db()
        self.assertEqual(
            field_value(instance, field), original,
            f"'{field}' moved despite the request being rejected",
        )
        return response

    def assert_protected_state_not_patchable(
        self, *, client, url, instance, updates, workspace, method='patch',
    ):
        """Lifecycle fields that only named actions may move.

        These are serializer read-only rather than rejected, so the request may
        legitimately return 200 — what must never happen is the state moving.
        """
        before = {name: field_value(instance, name) for name in updates}
        response = getattr(client, method)(
            url, updates, format='json', **workspace_header(workspace)
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST),
            f"protected-state PATCH returned {response.status_code} "
            f"({response.content[:300]})",
        )
        instance.refresh_from_db()
        for name, original in before.items():
            self.assertEqual(
                field_value(instance, name), original,
                f"protected field '{name}' was moved by an ordinary "
                f"{method.upper()} — it must require its named action",
            )
        return response

    # --- visibility attacks ------------------------------------------------

    def assert_object_hidden_from_other_workspace(
        self, *, client, detail_url, list_url, workspace, object_id,
    ):
        detail = client.get(detail_url, **workspace_header(workspace))
        self.assertEqual(
            detail.status_code, status.HTTP_404_NOT_FOUND,
            f"{detail_url} leaked to another workspace ({detail.status_code})",
        )
        listing = client.get(list_url, **workspace_header(workspace))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        rows = listing.json()
        rows = rows.get('results', rows) if isinstance(rows, dict) else rows
        self.assertNotIn(
            str(object_id), [str(row.get('id')) for row in rows],
            f"{list_url} listed an object from another workspace",
        )
        return detail

    # --- repeat-execution attacks ------------------------------------------

    def assert_duplicate_action_idempotent(
        self, *, client, url, workspace, state_of, expected_second_status=None,
    ):
        """Running an action twice must not compound its effect.

        `state_of` is a callable returning whatever "the permanent effect" means
        for this action — a row count, a status, a tuple. It is captured after
        the first call and must be identical after the second.
        """
        first = client.post(url, format='json', **workspace_header(workspace))
        after_first = state_of()
        second = client.post(url, format='json', **workspace_header(workspace))
        after_second = state_of()
        if expected_second_status is not None:
            self.assertEqual(
                second.status_code, expected_second_status,
                f"second {url} returned {second.status_code} "
                f"({second.content[:300]})",
            )
        self.assertEqual(
            after_first, after_second,
            f"running {url} twice changed the outcome: "
            f"{after_first!r} then {after_second!r}",
        )
        return first, second

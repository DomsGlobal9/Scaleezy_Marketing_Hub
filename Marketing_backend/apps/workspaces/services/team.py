"""
Team and role delegation for one client.

The rules that make delegation safe, in one place so every surface — the
client's own Admin screen and the platform console — enforces the same thing:

* nobody may grant a role above their own, or they could promote themselves
  by proxy;
* nobody may modify an OWNER unless they are an OWNER;
* the last OWNER can be neither demoted nor removed, or the client becomes
  unadministrable and only a shell can fix it;
* suspending is reversible and keeps the row, so history and attribution
  survive; removing deletes only the membership, never the user or their work.

There is no invite flow. Adding a brand-new person to a client is a platform
action (`attach_user_to_workspace`), because it crosses the tenant boundary.
"""
import logging

from django.db import transaction

from ..models import MarketingWorkspace, WorkspaceMember

logger = logging.getLogger(__name__)


class TeamError(Exception):
    """The requested team change is not allowed."""


def permission_matrix():
    """The real matrix, derived from ROLE_RANK — never a hand-kept constant.

    A constant here would drift the moment a role is added, and the screen
    would then describe permissions the server does not enforce.
    """
    capabilities = [
        ('view_content', 'View content and brand intelligence', WorkspaceMember.Role.VIEWER),
        ('edit_content', 'Create and edit content', WorkspaceMember.Role.EDITOR),
        ('edit_brand', 'Edit brand intelligence', WorkspaceMember.Role.EDITOR),
        ('publish', 'Publish and schedule', WorkspaceMember.Role.MANAGER),
        ('view_costs', 'See usage and cost', WorkspaceMember.Role.MANAGER),
        ('manage_ai', 'Configure AI providers and routing', WorkspaceMember.Role.ADMIN),
        ('manage_team', 'Change roles, suspend and remove people', WorkspaceMember.Role.ADMIN),
        ('manage_workspace', 'Rename or delete the client', WorkspaceMember.Role.ADMIN),
        ('transfer_ownership', 'Grant or remove OWNER', WorkspaceMember.Role.OWNER),
    ]
    roles = sorted(WorkspaceMember.ROLE_RANK, key=lambda r: WorkspaceMember.ROLE_RANK[r])
    return {
        'roles': [
            {'role': role, 'rank': WorkspaceMember.ROLE_RANK[role]} for role in roles
        ],
        'capabilities': [
            {
                'key': key,
                'label': label,
                'minimum_role': minimum,
                'granted_to': [
                    role for role in roles
                    if WorkspaceMember.ROLE_RANK[role] >= WorkspaceMember.ROLE_RANK[minimum]
                ],
            }
            for key, label, minimum in capabilities
        ],
    }


def owner_count(workspace) -> int:
    """Active OWNERs. A suspended OWNER cannot administrate, so it does not count."""
    return WorkspaceMember.objects.filter(
        workspace=workspace,
        role=WorkspaceMember.Role.OWNER,
        status=WorkspaceMember.Status.ACTIVE,
    ).count()


def _guard(actor_membership, target, *, action):
    """Shared authority checks for every mutation below."""
    if actor_membership is None:
        raise TeamError("You are not a member of this client.")
    if actor_membership.workspace_id != target.workspace_id:
        raise TeamError("That person is not a member of this client.")
    if not actor_membership.has_at_least(WorkspaceMember.Role.ADMIN):
        raise TeamError(f"Only an admin or owner can {action}.")
    if (
        target.role == WorkspaceMember.Role.OWNER
        and actor_membership.role != WorkspaceMember.Role.OWNER
    ):
        raise TeamError("Only an owner can change another owner.")


@transaction.atomic
def change_member_role(actor_membership, target, new_role):
    """Change one member's role, bounded by the actor's own authority."""
    if new_role not in WorkspaceMember.ROLE_RANK:
        raise TeamError(f"Unknown role: {new_role}")
    _guard(actor_membership, target, action='change roles')

    # The ceiling that stops privilege escalation by proxy: an ADMIN cannot
    # mint an OWNER and then be promoted by them.
    if WorkspaceMember.ROLE_RANK[new_role] > actor_membership.rank:
        raise TeamError("You cannot grant a role above your own.")

    if (
        target.role == WorkspaceMember.Role.OWNER
        and new_role != WorkspaceMember.Role.OWNER
        and owner_count(target.workspace) <= 1
    ):
        raise TeamError(
            "This is the last owner. Promote somebody else to owner first."
        )

    if target.role == new_role:
        return target

    previous = target.role
    target.role = new_role
    target.save(update_fields=['role', 'updated_at'])
    logger.info(
        "Role changed: workspace=%s member=%s %s -> %s by %s",
        target.workspace_id, target.pk, previous, new_role, actor_membership.user_id,
    )
    return target


@transaction.atomic
def set_member_status(actor_membership, target, status):
    """Suspend or reactivate. `WorkspaceMember.status` has existed since
    Phase 1 and until now had no writer, so suspension was unreachable."""
    if status not in WorkspaceMember.Status.values:
        raise TeamError(f"Unknown status: {status}")
    _guard(actor_membership, target, action='suspend or reactivate people')

    if target.pk == actor_membership.pk and status == WorkspaceMember.Status.SUSPENDED:
        raise TeamError("You cannot suspend yourself.")

    if (
        status == WorkspaceMember.Status.SUSPENDED
        and target.role == WorkspaceMember.Role.OWNER
        and owner_count(target.workspace) <= 1
    ):
        raise TeamError("This is the last owner and cannot be suspended.")

    if target.status == status:
        return target
    target.status = status
    target.save(update_fields=['status', 'updated_at'])
    logger.info(
        "Member %s on workspace %s set to %s", target.pk, target.workspace_id, status
    )
    return target


@transaction.atomic
def remove_member(actor_membership, target):
    """Delete the membership. The user account and everything they created stay."""
    _guard(actor_membership, target, action='remove people')

    if target.pk == actor_membership.pk:
        raise TeamError("You cannot remove yourself. Ask another admin.")
    if (
        target.role == WorkspaceMember.Role.OWNER
        and owner_count(target.workspace) <= 1
    ):
        raise TeamError("This is the last owner and cannot be removed.")

    workspace_id, member_id = target.workspace_id, target.pk
    target.delete()
    logger.info("Member %s removed from workspace %s", member_id, workspace_id)
    return True


@transaction.atomic
def attach_user_to_workspace(user, workspace, *, role=WorkspaceMember.Role.EDITOR,
                             by=None, archive_orphan=True):
    """Platform action: put an existing user onto an existing client.

    This is the answer to the case signup deliberately blocks. When a
    colleague signs up for a company that is already a Scaleezy client, the
    duplicate-website guard refuses them — correctly, or the approval queue
    fills with duplicates of one company. But refusing without a remedy just
    strands the person, so this is the remedy: an operator attaches them to
    the real client, and the empty workspace their signup created (if any) is
    archived rather than left to look like a second customer.

    Crosses the tenant boundary, so it is platform-only and always audited.
    """
    from apps.audit.models import record_platform_event

    if role not in WorkspaceMember.ROLE_RANK:
        raise TeamError(f"Unknown role: {role}")
    if workspace.status != MarketingWorkspace.Status.ACTIVE:
        raise TeamError("That client is suspended or archived.")

    membership, created = WorkspaceMember.objects.get_or_create(
        workspace=workspace, user=user,
        defaults={'role': role, 'invited_by': by},
    )
    if not created:
        # Already there: reactivate rather than error, which is what the
        # operator meant.
        if membership.status != WorkspaceMember.Status.ACTIVE:
            membership.status = WorkspaceMember.Status.ACTIVE
            membership.save(update_fields=['status', 'updated_at'])

    archived = []
    if archive_orphan:
        from apps.workspaces.services.lifecycle import archive_workspace

        # Any OTHER client where this user is the only member and nothing has
        # been approved: that is the stranded signup, not a real customer.
        others = (
            WorkspaceMember.objects.filter(user=user)
            .exclude(workspace_id=workspace.pk)
            .select_related('workspace')
        )
        for other in others:
            if other.workspace.status != MarketingWorkspace.Status.ACTIVE:
                continue
            if WorkspaceMember.objects.filter(workspace=other.workspace).count() != 1:
                continue
            from apps.brands.models import Brand

            if Brand.objects.filter(
                workspace=other.workspace, status=Brand.Status.ACTIVE
            ).exists():
                continue  # a real, approved client — never touch it
            archive_workspace(
                other.workspace, by=by,
                reason=f'Duplicate signup; user attached to {workspace.client_code}',
            )
            archived.append(str(other.workspace.pk))

    record_platform_event(
        actor=by, action='USER_ATTACHED_TO_CLIENT', workspace=workspace,
        target=f'user:{user.pk}',
        detail={
            'username': user.get_username(),
            'role': role,
            'created_membership': created,
            'archived_orphan_workspaces': archived,
        },
    )
    return membership, archived

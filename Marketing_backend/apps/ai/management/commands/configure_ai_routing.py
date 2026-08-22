"""
Provision the minimum viable AI routing for a workspace.

    manage.py configure_ai_routing --dry-run
    manage.py configure_ai_routing --apply

A workspace with no route gets a 503 from every Create, because
`AIRouter._candidates()` has nothing to select. That is a configuration gap,
not a code one, so it is fixed with a command rather than a migration: routing
is an operational decision per tenant, and a migration would impose one on
every environment that runs it.

CREDENTIALS ARE NOT REQUIRED, AND BY DEFAULT NOT TOUCHED.
`registry.build()` constructs an adapter whether or not a workspace credential
is stored, and `GeminiAdapter` falls back to `settings.GEMINI_API_KEY` - the
server's own environment. Leaving the workspace credential empty is therefore
the SAFER configuration: the key stays in one place (the platform's secret
store) instead of being copied into a database column, and rotating it is one
operation rather than one per tenant.

`--credential-env NAME` exists for the case where one tenant must use a key of
its own. It reads that environment variable directly and encrypts it with the
same Fernet helper the OAuth tokens use. The value is never printed, never
logged and never returned to a client - only whether one is present.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ai.models import AIProvider, Capability, Strategy, WorkspaceAIProvider, WorkspaceAIRoute
from apps.ai.registry import get_adapter_class
from apps.workspaces.models import MarketingWorkspace

#: The capabilities a workspace needs routed before Create works end to end.
#: TEXT alone produces copy with no poster; the generation accelerator asks for
#: both and keeps whichever succeeds.
REQUIRED_CAPABILITIES = (Capability.TEXT, Capability.IMAGE)

DEFAULT_PRIORITY = 100
DEFAULT_STRATEGY = Strategy.FAILOVER


class Command(BaseCommand):
    help = "Ensure a workspace has an enabled provider and routes for TEXT and IMAGE."

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider', default='gemini',
            help="Adapter key to route (default: gemini). Must be installed AND in the catalogue.",
        )
        parser.add_argument(
            '--workspace', action='append', default=None,
            help="Workspace id to configure. Repeatable. Default: every workspace.",
        )
        parser.add_argument(
            '--capability', action='append', default=None,
            help=f"Capability to route. Repeatable. Default: {', '.join(REQUIRED_CAPABILITIES)}.",
        )
        parser.add_argument(
            '--priority', type=int, default=DEFAULT_PRIORITY,
            help=f"Route priority, lower runs first (default: {DEFAULT_PRIORITY}).",
        )
        parser.add_argument(
            '--credential-env', default=None,
            help=(
                "Name of an environment variable holding this workspace's own API key. "
                "Omit to rely on the server's configured key, which is usually correct. "
                "The value is read directly from the environment and never printed."
            ),
        )
        parser.add_argument(
            '--apply', action='store_true',
            help="Write the changes. Without it the command reports the plan and writes nothing.",
        )
        parser.add_argument('--dry-run', action='store_true', help="Explicit no-op (the default).")

    def handle(self, *args, **options):
        apply_changes = options['apply'] and not options['dry_run']
        provider_key = options['provider']

        capabilities = options['capability'] or list(REQUIRED_CAPABILITIES)
        unknown = [c for c in capabilities if c not in Capability.values]
        if unknown:
            raise CommandError(f"Unknown capability/capabilities: {', '.join(unknown)}")

        # 1. The adapter must actually be installed. Routing to a provider with
        #    no code behind it produces a candidate that build() drops, which
        #    looks like "configured" and behaves like "503".
        adapter_class = get_adapter_class(provider_key)
        if adapter_class is None:
            raise CommandError(
                f"No adapter installed for '{provider_key}'. Routing it would silently "
                f"produce no candidates."
            )

        try:
            provider = AIProvider.objects.get(key=provider_key)
        except AIProvider.DoesNotExist:
            raise CommandError(
                f"'{provider_key}' is installed but absent from the AIProvider catalogue. "
                f"Add the catalogue row first; this command does not invent providers."
            )

        # 2. The catalogue and the adapter must agree about what it can do.
        #    Believing the catalogue alone is how a capability gets routed to
        #    code that cannot serve it.
        declared = {str(c) for c in (getattr(adapter_class, 'capabilities', ()) or ())}
        unsupported = [
            c for c in capabilities
            if not provider.supports(c) or (declared and c not in declared)
        ]
        if unsupported:
            raise CommandError(
                f"'{provider_key}' does not genuinely support {', '.join(unsupported)} "
                f"(catalogue: {provider.capabilities}; adapter: {sorted(declared)}). "
                f"Route an approved provider that does, or drop the capability."
            )

        if not provider.is_available:
            raise CommandError(
                f"'{provider_key}' is switched off globally (is_available=False). "
                f"That kill switch is deliberate; clear it before routing."
            )

        credential = None
        if options['credential_env']:
            import os

            credential = os.environ.get(options['credential_env'], '')
            if not credential:
                raise CommandError(
                    f"{options['credential_env']} is not set in this environment. "
                    f"Run this where the secret actually lives, or omit --credential-env "
                    f"to use the server's configured key."
                )

        workspaces = MarketingWorkspace.objects.all().order_by('workspace_name')
        if options['workspace']:
            workspaces = workspaces.filter(pk__in=options['workspace'])
            if workspaces.count() != len(set(options['workspace'])):
                raise CommandError("One or more --workspace ids do not exist.")

        if not workspaces:
            raise CommandError("No workspaces matched.")

        mode = self.style.WARNING('APPLY') if apply_changes else self.style.NOTICE('DRY RUN')
        self.stdout.write(f"{mode}  provider={provider_key}  capabilities={', '.join(capabilities)}  "
                          f"priority={options['priority']}  strategy={DEFAULT_STRATEGY}")
        self.stdout.write(
            "credential source: "
            + (f"${options['credential_env']} (stored encrypted per workspace)"
               if credential else "server environment (nothing stored per workspace)")
        )
        self.stdout.write('')

        planned = []
        for workspace in workspaces:
            planned.extend(
                self._configure(workspace, provider, capabilities, options['priority'],
                                credential, apply_changes)
            )

        self.stdout.write('')
        if not planned:
            self.stdout.write(self.style.SUCCESS("Nothing to change - routing already correct."))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Applied {len(planned)} change(s)."))
        else:
            self.stdout.write(f"{len(planned)} change(s) would be made. Re-run with --apply.")

        self.stdout.write('')
        self._verify(workspaces, provider, capabilities)

    # ------------------------------------------------------------------ write

    def _configure(self, workspace, provider, capabilities, priority, credential, apply_changes):
        changes = []
        label = f'{workspace.workspace_name} ({workspace.pk})'

        with transaction.atomic():
            wp = WorkspaceAIProvider.objects.filter(
                workspace=workspace, provider=provider
            ).first()

            if wp is None:
                changes.append(f'{label}: create WorkspaceAIProvider (enabled)')
                if apply_changes:
                    wp = WorkspaceAIProvider.objects.create(
                        workspace=workspace, provider=provider, enabled=True,
                    )
            elif not wp.enabled:
                changes.append(f'{label}: enable existing WorkspaceAIProvider')
                if apply_changes:
                    wp.enabled = True
                    wp.save(update_fields=['enabled', 'updated_at'])

            if credential and wp is not None:
                # Encrypted with the same helper that protects OAuth tokens.
                # Only the fact of a credential is ever reported, never its value.
                from apps.social_accounts.utils.encryption import encrypt_token

                changes.append(f'{label}: store workspace credential (encrypted)')
                if apply_changes:
                    wp.credentials_encrypted = encrypt_token(credential)
                    wp.save(update_fields=['credentials_encrypted', 'updated_at'])

            for capability in capabilities:
                route = WorkspaceAIRoute.objects.filter(
                    workspace=workspace, capability=capability, provider=provider
                ).first()
                if route is None:
                    changes.append(f'{label}: route {capability} -> {provider.key}')
                    if apply_changes:
                        WorkspaceAIRoute.objects.create(
                            workspace=workspace, capability=capability, provider=provider,
                            priority=priority, enabled=True, strategy=DEFAULT_STRATEGY,
                        )
                elif not route.enabled:
                    changes.append(f'{label}: re-enable {capability} route')
                    if apply_changes:
                        route.enabled = True
                        route.save(update_fields=['enabled'])

        for change in changes:
            self.stdout.write(f'  {"+" if apply_changes else "~"} {change}')
        if not changes:
            self.stdout.write(f'  = {label}: already correct')
        return changes

    # ----------------------------------------------------------------- verify

    def _verify(self, workspaces, provider, capabilities):
        """Every condition the router checks, reported per workspace.

        Presence of a credential is reported as a boolean and nothing else.
        """
        self.stdout.write('VERIFICATION (the conditions AIRouter._candidates actually applies)')
        adapter_class = get_adapter_class(provider.key)

        for workspace in workspaces:
            wp = WorkspaceAIProvider.objects.filter(
                workspace=workspace, provider=provider
            ).first()
            self.stdout.write(f'  {workspace.workspace_name} ({workspace.pk})')
            self.stdout.write(
                f'    provider enabled     : {bool(wp and wp.enabled)}\n'
                f'    workspace credential : {bool(wp and wp.credentials_encrypted)}'
                f'   (absent is fine - the adapter falls back to the server key)\n'
                f'    globally available   : {provider.is_available}\n'
                f'    adapter installed    : {adapter_class is not None}'
            )
            for capability in capabilities:
                route = WorkspaceAIRoute.objects.filter(
                    workspace=workspace, capability=capability, provider=provider
                ).first()
                self.stdout.write(
                    f'    {capability:<6} route        : '
                    f'{"enabled" if route and route.enabled else "MISSING"}'
                    + (f'  priority={route.priority} strategy={route.strategy}' if route else '')
                    + f'  supported={provider.supports(capability)}'
                )

            if wp and wp.enabled and adapter_class is not None:
                # health_check only asks whether a key is reachable. It makes no
                # network call and so costs nothing and cannot leak a value.
                from apps.ai.registry import build

                adapter = build(wp)
                health = adapter.health_check() if adapter else {'ok': False, 'detail': 'no adapter'}
                self.stdout.write(
                    f'    key reachable        : {health.get("ok")}  ({health.get("detail", "")})'
                )

"""
Provision the minimum viable AI routing for a workspace.

    manage.py configure_ai_routing --dry-run
    manage.py configure_ai_routing --apply

A workspace with no route gets a 503 from every Create, because
`AIRouter._candidates()` has nothing to select. New workspaces now provision
themselves on creation via strict `apps.ai.provisioning.provision_default_ai`,
so this command is the repair tool: it backfills workspaces that predate that,
re-enables what an operator switched off, and routes a provider other than the
default one the service picks. The writes themselves are that same service, so
there is one place where routing gets created and one place to change it.

CREDENTIALS ARE NOT REQUIRED, AND BY DEFAULT NOT TOUCHED.
`registry.build()` constructs an adapter whether or not a workspace credential
is stored, and an adapter may use its platform-managed server credential.
Leaving the workspace credential empty is therefore the SAFER configuration:
the key stays in one place (the platform's secret store) instead of being
copied into a database column, and rotating it is one operation rather than
one per tenant.

`--credential-env NAME` exists for the case where one tenant must use a key of
its own. It reads that environment variable directly and encrypts it with the
same Fernet helper the OAuth tokens use. The value is never printed, never
logged and never returned to a client - only whether one is present.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.ai.models import AIProvider, Capability, WorkspaceAIProvider, WorkspaceAIRoute
from apps.ai.provisioning import (
    DEFAULT_PRIORITY,
    DEFAULT_STRATEGY,
    REQUIRED_CAPABILITIES,
    provider_serves,
    provision_ai_routing,
    resolve_default_provider,
)
from apps.ai.registry import get_adapter_class
from apps.workspaces.models import MarketingWorkspace


class Command(BaseCommand):
    help = "Ensure a workspace has an enabled provider and routes for TEXT and IMAGE."

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider', default=None,
            help=(
                "Adapter key to route. Omit to select by enabled catalogue, installed "
                "adapter, required capabilities and stable cost/key policy."
            ),
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
        capabilities = options['capability'] or list(REQUIRED_CAPABILITIES)
        unknown = [c for c in capabilities if c not in Capability.values]
        if unknown:
            raise CommandError(f"Unknown capability/capabilities: {', '.join(unknown)}")

        provider_key = options['provider']
        if provider_key:
            try:
                provider = AIProvider.objects.get(key=provider_key)
            except AIProvider.DoesNotExist:
                raise CommandError(
                    f"No AIProvider catalogue row exists for '{provider_key}'."
                )
        else:
            provider = resolve_default_provider(capabilities)
            if provider is None:
                raise CommandError(
                    "No installed, globally available catalogue provider serves "
                    f"{', '.join(capabilities)}. Enable one in Admin or pass "
                    "--provider after installing its adapter."
                )
            provider_key = provider.key

        # The adapter must actually be installed. Routing to a provider with
        # no code behind it produces a candidate that build() drops, which
        # looks like "configured" and behaves like "503".
        adapter_class = get_adapter_class(provider_key)
        if adapter_class is None:
            raise CommandError(
                f"No adapter installed for '{provider_key}'. Routing it would silently "
                f"produce no candidates."
            )

        # The catalogue and the adapter must agree about what it can do.
        #    Believing the catalogue alone is how a capability gets routed to
        #    code that cannot serve it.
        declared = {str(c) for c in (getattr(adapter_class, 'capabilities', ()) or ())}
        unsupported = [
            c for c in capabilities if not provider_serves(provider, adapter_class, [c])
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
        """Reporting only. The writes belong to apps.ai.provisioning, which is
        also what workspace creation calls — one writer, so the command and the
        automatic path cannot drift into provisioning different things."""
        changes = provision_ai_routing(
            workspace, provider,
            capabilities=capabilities, priority=priority,
            credential=credential, apply=apply_changes,
        )

        for change in changes:
            self.stdout.write(f'  {"+" if apply_changes else "~"} {change}')
        if not changes:
            self.stdout.write(
                f'  = {workspace.workspace_name} ({workspace.pk}): already correct'
            )
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
                # The health check is an authenticated, read-only provider
                # request. It creates no content and consumes no generation
                # tokens; adapters also sanitize every failure.
                from apps.ai.registry import build

                adapter = build(wp)
                health = adapter.health_check() if adapter else {'ok': False, 'detail': 'no adapter'}
                self.stdout.write(
                    f'    key reachable        : {health.get("ok")}  ({health.get("detail", "")})'
                )

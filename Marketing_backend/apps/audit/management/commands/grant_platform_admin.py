"""
Bootstrap the first platform admin.

Every other grant is made by an existing platform admin through the console.
The first one cannot be — so it is made here, deliberately from a shell, once
per environment.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.audit.services import (
    PlatformAdminError,
    grant_platform_admin,
    revoke_platform_admin,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Grant or revoke Scaleezy platform-admin authority for a user."

    def add_arguments(self, parser):
        parser.add_argument('username', help="Username (the signup email) to act on.")
        parser.add_argument(
            '--revoke', action='store_true',
            help="Revoke instead of grant. The grant history is kept.",
        )
        parser.add_argument('--note', default='', help="Why this grant exists.")

    def handle(self, *args, **options):
        username = options['username']
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"No user with username {username!r}.")

        # Both paths go through the audited service, so a grant made from a
        # shell is recorded exactly like one made from the console.
        if options['revoke']:
            try:
                _, changed = revoke_platform_admin(user)
            except PlatformAdminError as exc:
                raise CommandError(str(exc))
            if not changed:
                self.stdout.write(f"{username} does not hold platform admin.")
                return
            self.stdout.write(
                self.style.WARNING(f"Revoked platform admin from {username}.")
            )
            return

        _, changed = grant_platform_admin(user, note=options['note'])
        if not changed:
            self.stdout.write(f"{username} already holds platform admin.")
            return
        self.stdout.write(self.style.SUCCESS(f"Granted platform admin to {username}."))

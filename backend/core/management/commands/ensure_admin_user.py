from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure a single is_staff/is_superuser admin exists, matching ADMIN_USERNAME/ADMIN_PASSWORD."

    def handle(self, *args, **options):
        username = settings.ADMIN_USERNAME
        password = settings.ADMIN_PASSWORD

        if not password:
            self.stdout.write(self.style.WARNING("ADMIN_PASSWORD is unset; skipping admin bootstrap."))
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_superuser": True, "email": ""},
        )

        user.is_staff = True
        user.is_superuser = True

        if not user.check_password(password):
            user.set_password(password)
            self.stdout.write(self.style.SUCCESS(f"Admin {'created' if created else 'updated'}: {username}"))
        elif created:
            user.set_password(password)
            self.stdout.write(self.style.SUCCESS(f"Admin created: {username}"))
        else:
            self.stdout.write(f"Admin already up-to-date: {username}")

        user.save()

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """Authenticate with e-mail (primary) or username, case-insensitively."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username or kwargs.get(User.USERNAME_FIELD)
        if not identifier or password is None:
            return None
        user = User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier)
        ).first()
        if user is None:
            User().set_password(password)  # equalise timing
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

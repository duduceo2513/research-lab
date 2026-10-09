from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserRole(models.TextChoices):
    ADMIN = 'ADMIN', 'Administrator'
    TEACHER = 'TEACHER', 'Teacher'
    STUDENT = 'STUDENT', 'Student'


class UserManager(BaseUserManager):
    """Manager for a user model that logs in with e-mail."""

    use_in_migrations = True

    def _unique_username(self, email: str) -> str:
        base = email.split('@')[0][:120] or 'user'
        candidate, n = base, 1
        while self.model.objects.filter(username__iexact=candidate).exists():
            n += 1
            candidate = f'{base}{n}'
        return candidate

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError('The e-mail address must be set.')
        email = self.normalize_email(email).lower()
        extra['username'] = extra.get('username') or self._unique_username(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault('role', UserRole.STUDENT)
        extra.setdefault('is_staff', False)
        extra.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra['role'] = UserRole.ADMIN
        extra['is_staff'] = True
        extra['is_superuser'] = True
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, email: str):
        return self.get(email__iexact=email)


class User(AbstractUser):
    """Platform user. ``email`` is the primary login identifier."""

    email = models.EmailField('e-mail address', unique=True, db_index=True)
    role = models.CharField('role', max_length=16, choices=UserRole.choices,
                            default=UserRole.STUDENT, db_index=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    objects = UserManager()

    class Meta:
        verbose_name = 'user'
        verbose_name_plural = 'users'
        ordering = ['email']
        indexes = [models.Index(fields=['role', 'is_active'], name='user_role_active_idx')]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.username

    @property
    def is_admin_role(self) -> bool:
        return self.role == UserRole.ADMIN or self.is_superuser

    @property
    def is_teacher(self) -> bool:
        return self.role == UserRole.TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == UserRole.STUDENT

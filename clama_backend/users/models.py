from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Default custom user model for clama_backend.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = models.CharField("Nome", blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]

    def get_full_name(self) -> str:
        return self.name or self.username

    def get_short_name(self) -> str:
        return self.name or self.username

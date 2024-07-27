import hashlib

from django.contrib.auth.models import AbstractUser
from django.utils.http import urlencode

from judge.models import Profile
from judge.utils.unicode import utf8bytes
from django.conf import settings
from . import registry


@registry.function
def gravatar(email, size=80, default=None):
    if isinstance(email, Profile):
        if default is None:
            default = email.mute
        user_id = email.user.id
    elif isinstance(email, AbstractUser):
        user_id = email.id

    return f"/avatar/{user_id}.png"

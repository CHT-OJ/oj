import hashlib

from django.contrib.auth.models import AbstractUser
from django.utils.http import urlencode

from judge.models import Profile
from judge.utils.unicode import utf8bytes
from . import registry


@registry.function
def gravatar(email, size=80, default=None):
    if isinstance(email, Profile):
        if default is None:
            default = email.mute
        user_id = email.user.id
        email = email.user.email
    elif isinstance(email, AbstractUser):
        user_id = email.id
        email = email.email
    elif isinstance(email, str):
        user_id = Profile.objects.get(user__username=email).user_id
    else:
        return fallback(email, size, default)
    try:
        prof = Profile.objects.get(user__id=user_id)
        if not prof.avt_url:
            return fallback(email, size, default)
        else:
            return f"/avatar{prof.avt_url.thumbnail[f'{size}x{size}']}"
    except Profile.DoesNotExist:
        return fallback(email, size, default)


def fallback(email, size, default):
    gravatar_url = 'https://www.gravatar.com/avatar/' + hashlib.md5(utf8bytes(email.strip().lower())).hexdigest() + '?'
    args = {'d': 'identicon', 's': str(size)}
    if default:
        args['f'] = 'y'

    gravatar_url += urlencode(args)
    return gravatar_url

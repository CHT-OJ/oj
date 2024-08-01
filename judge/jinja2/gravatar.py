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
        email = email.user.email

    elif isinstance(email, AbstractUser):
        user_id = email.id
        email = email.email

    if not Profile.objects.get(id=user_id).avt_url:
        gravatar_url = 'https://www.gravatar.com/avatar/' + hashlib.md5(utf8bytes(email.strip().lower())).hexdigest() + '?'
        args = {'d': 'identicon', 's': str(size)}
        if default:
            args['f'] = 'y'

        gravatar_url += urlencode(args)
        return gravatar_url
    else:
        return f"/avatar{Profile.objects.get(id=user_id).avt_url.thumbnail[f'{size}x{size}']}"

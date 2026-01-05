from django.contrib import admin
from django.forms import ModelForm
from judge.models import Logo

from judge.widgets import AdminSelect2MultipleWidget


class LogoForm(ModelForm):
    class Meta:
        model = Logo
        fields = '__all__'
        widgets = {
            'allowed_users': AdminSelect2MultipleWidget(attrs={'style': 'width: 100%'}),
            'organizations': AdminSelect2MultipleWidget(attrs={'style': 'width: 100%'}),
        }


class LogoAdmin(admin.ModelAdmin):
    form = LogoForm

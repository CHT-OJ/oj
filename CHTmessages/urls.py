from django.urls import path
from . import views

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("convo/<str:username>/", views.conversation, name="conversation"),
    path("convo/<str:username>/send/", views.send_message, name="send_message"),
]

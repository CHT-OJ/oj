from django.contrib import admin
from .models import Message

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'recipient', 'body_snippet', 'timestamp', 'read')
    list_filter = ('read', 'timestamp', 'sender', 'recipient')
    search_fields = ('body', 'sender__username', 'recipient__username')
    ordering = ('-timestamp',)
    readonly_fields = ('timestamp',)

    def body_snippet(self, obj):
        return obj.body[:50] + ('...' if len(obj.body) > 50 else '')
    body_snippet.short_description = 'Message'

import json
import asyncio
import websockets
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from .models import Message
from django.db.models import Q, Max

async def _send_ws(channel: str, payload: dict):
    packet = {
        "command": "post",
        "channel": channel,
        "message": json.dumps(payload),
    }
    uri = "ws://127.0.0.1:15101"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps(packet))
        return True
    except Exception as e:
        print(f"Failed to send WS message: {e}")
        return False

def send_chat_event(channel: str, payload: dict):
    try:
        asyncio.run(_send_ws(channel, payload))
        return True
    except Exception:
        return False

@login_required
def inbox(request):
    msgs = Message.objects.filter(Q(sender=request.user) | Q(recipient=request.user)).order_by('-timestamp')
    conv = {}
    for m in msgs:
        other_user = m.sender if m.sender != request.user else m.recipient
        if other_user.id not in conv:
            conv[other_user.id] = m

    sorted_conv = sorted(conv.values(), key=lambda x: x.timestamp, reverse=True)
    return render(request, "CHTmessages/inbox.html", {"conversations": sorted_conv, "title":"Inbox"})


from django.template import engines
from django.http import HttpResponse
@login_required
def conversation(request, username):
    other_user = get_object_or_404(User, username=username)
    messages_qs = Message.objects.filter(
        sender__in=[request.user, other_user],
        recipient__in=[request.user, other_user],
    ).order_by("timestamp").select_related("sender")

    # jinja đ chạy đ fix đc :)))
    django_engine = engines['django']

    template = django_engine.get_template('CHTmessages/convo.html')
    return HttpResponse(template.render({
        "messages": messages_qs,
        "other_user": other_user,
        "request": request,
    }, request))



@require_POST
@login_required
def send_message(request, username):
    other_user = get_object_or_404(User, username=username)
    body = request.POST.get("body", "").strip()
    if not body:
        return JsonResponse({"error": "empty"}, status=400)

    msg = Message.objects.create(
        sender=request.user,
        recipient=other_user,
        body=body,
        read=False,
    )

    payload = {
        "id": msg.id,
        "sender": request.user.username,
        "recipient": other_user.username,
        "body": body,
        "timestamp": int(msg.timestamp.timestamp() * 1000),
    }
    send_chat_event(f"chat_{other_user.username}", payload)
    send_chat_event(f"chat_{request.user.username}", payload)


    return JsonResponse({
        "id": msg.id,
        "sender": request.user.username,
        "recipient": other_user.username,
        "body": msg.body,
        "timestamp": payload["timestamp"],
    })
from judge.models import Profile
from django.utils.timezone import now as time_now
import datetime

def check_time_difference(time1, time2):
    if time1 is None or time2 is None:
        return False

    if isinstance(time1, str):
        time1 = datetime.datetime.strptime(time1, "%Y-%m-%d %H:%M:%S.%f")
    if isinstance(time2, str):
        time2 = datetime.datetime.strptime(time2, "%Y-%m-%d %H:%M:%S.%f")

    time_difference = time2 - time1
    days_difference = time_difference.days

    return days_difference > 14

for user in Profile.objects.all():
  try:
    tn = time_now()
    if check_time_difference(user.last_warned, tn):
        user.last_warned = None
        user.save()
  except Exception as e:
    print(f"{user.username} : {e}") 
       

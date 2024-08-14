from judge.models import Profile
from django.utils.timezone import now as time_now 

def check_time_difference(time1, time2):
    if isinstance(time1, str):
      time1 = datetime.datetime.strptime(time1, "%Y-%m-%d %H:%M:%S.%f")
    if isinstance(time2, str):
      time2 = datetime.datetime.strptime(time2, "%Y-%m-%d %H:%M:%S.%f")

    time_difference = time2 - time1
    days_difference = time_difference.days

    return days_difference > 14
  
def auto_change_warn_time():
    tn = time_now()
    for user in Profile.objects.all():
        if(user.last_warned == None and check_time_difference(user.last_warned,tn)==false):
            user.last_warned = None
            user.save()
    
    
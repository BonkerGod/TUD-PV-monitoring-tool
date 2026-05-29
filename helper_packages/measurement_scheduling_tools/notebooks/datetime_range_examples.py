#!/usr/bin/env python
# coding: utf-8

# In[2]:


from datetime import datetime, timedelta, timezone
from helper_packages.measurement_scheduling_tools import datetime_range


# In[31]:


interval = timedelta(seconds=10)
present = datetime(2022, 1, 20, 10, 1, 0, microsecond=0, tzinfo=timezone.utc)
# Simplest usage
datetime_range(
    present,
    present + interval,
    interval
)


# In[3]:


# Intervals are aligned with the origin, which is the start of the Unix
# epoch by default.
#
# Here, we advance the start and end times by 2 s and the intervals stay
# aligned to :10, :20, etc.
datetime_range(
    datetime(2022, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
    datetime(2022, 1, 1, 0, 1, 2, tzinfo=timezone.utc),
    timedelta(seconds=10)
)


# In[4]:


# A different origin can be specified. Here, the origin is set to the start
# datetime.
start = datetime(2022, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
datetime_range(
    start,
    datetime(2022, 1, 1, 0, 1, 2, tzinfo=timezone.utc),
    timedelta(seconds=10),
    origin=start
)


# In[5]:


# Everything works fine if time zones are different
datetime_range(
    datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    datetime(2022, 1, 1, 0, 1, 0, tzinfo=timezone(timedelta(hours=-7))),
    timedelta(hours=1)
)


# In[6]:


# Everything works fine if time zones are absent, but a tz-naive origin must
# be specified
datetime_range(
    datetime(2022, 1, 1, 0, 0, 0),
    datetime(2022, 1, 1, 0, 1, 0),
    timedelta(seconds=10),
    origin=datetime(1970, 1, 1, 0, 0, 0)
)


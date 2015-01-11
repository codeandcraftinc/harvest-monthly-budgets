#!/usr/bin/env python
'''
Based on https://gist.github.com/jonasvp/1330207.

Harvest (www.getharvest.com) does not support setting monthly budgets for projects.
The recommended workaround is creating a new project every month. This script is
supposed to run on the first of every month and uses the Harvest API in order to
archive last month's projects and create new ones for the current month. Members
and tasks are automatically copied over to the new project.

Projects with monthly budgets need to fulfill two requirements:
    1. They need to have a budget set
    2. The name needs to end in "[YYYY-MM]", meaning year and month of the current 
       month. Example would be: "Some Sample Project [2011-10]".

An example crontab entry would be:

    0 1 1 * * MAILGUN_API_KEY=some_key MAILGUN_DOMAIN=mg.example.com NOTIFY=someone@needstoknow.com SLUG=sample USERNAME=example@example.com PASSWORD=xyz /path/to/harvest_monthly_budgets.py

Uses the "requests" library (http://pypi.python.org/pypi/requests)
'''

import os
import re
import datetime
import requests
import json

LOG = []

def log(message, sub=False):
  global LOG
  LOG.append(('----> ' if sub else '==> ') + message)
  print LOG[-1]


REQUEST_HEADERS = {
  'auth': (os.environ['USERNAME'], os.environ['PASSWORD']),
  'headers': {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
  }
}

EXCLUDED_FIELDS = (
  'active_task_assignments_count', 'active_user_assignments_count',
  'cache_version', 'created_at', 'earliest_record_at',
  'hint-earliest-record-at', 'hint-latest-record-at', 'id',
  'latest_record_at', 'name', 'updated_at'
)

BASE_URL = 'https://' + os.environ['SLUG'] + '.harvestapp.com/projects'

t = datetime.date.today()
y, m  = t.year, t.month
this_month = '[' + t.replace(day=1).strftime('%Y-%m') + ']'
last_month = t.replace(month=12, year=y-1) if m == 1 else t.replace(month=m-1)
last_month = '[' + last_month.strftime('%Y-%m') + ']'
projects = requests.get(BASE_URL, **REQUEST_HEADERS).json()

for p in projects:
  project = p['project']
  if project['active'] and project['name'].endswith(last_month) and (
    (project['budget'] and float(project['budget'])) or
    (project['cost_budget'] and float(project['cost_budget']))
  ):

    # get existing project ID, prepare new project
    log('duplicating project: %s' % project['name'])
    pid = project['id']
    new_project = { 'name': project['name'].replace(last_month, this_month) }
    for key, value in project.items():
      if key not in EXCLUDED_FIELDS:
        new_project[key] = value

    # create new project via API
    log('creating new project: %s' % new_project['name'], True)
    r = requests.post(BASE_URL, data=json.dumps({ 'project': new_project }), **REQUEST_HEADERS)
    if r.status_code != 201:
      log('could not create new project: %s' % r.read())
      continue

    # capture the new project's ID
    new_pid = re.findall('(\d+)$', r.headers['Location'])[0]
    log('successfully duplicated "%s" <%s> as "%s" <%s>' % (project['name'], pid, new_project['name'], new_pid), True)

    # assign existing users to the new project
    # {u'user_assignment': {u'is_project_manager': True, u'deactivated': False, u'created_at': u'2015-01-11T03:14:11Z', u'budget': None, u'updated_at': u'2015-01-11T03:14:11Z', u'user_id': 849683, u'estimate': None, u'project_id': 7091999, u'id': 56882531, u'hourly_rate': 150.0}}
    log('transferring users:', True)
    users = requests.get('%s/%s/user_assignments' % (BASE_URL, pid), **REQUEST_HEADERS).json()
    for u in users:
      new_user = { 'user': { 'id': u['user_assignment']['user_id'] } }
      log('adding user <%s> to new project <%s>' % (new_user['user']['id'], new_pid), True)
      r = requests.post('%s/%s/user_assignments' % (BASE_URL, pid), data=json.dumps(new_user), **REQUEST_HEADERS)
      if r.status_code != 201:
        log('could not assign user <%s> to new project <%s>' % (new_user['user']['id'], new_pid), True)

    # 
    log('transferring tasks:', True)
    tasks = requests.get('%s/%s/task_assignments' % (BASE_URL, pid), **REQUEST_HEADERS).json()
    for t in tasks:
      new_task = { 'task': { 'id': t['task_assignment']['task_id'] } }
      log('adding task <%s> to new project <%s>' % (new_task['task']['id'], new_pid), True)
      r = requests.post('%s/%s/task_assignments' % (BASE_URL, pid), data=json.dumps(new_task), **REQUEST_HEADERS)
      if r.status_code != 201:
        log('could not add task <%s> to new project <%s>' % (new_task['task']['id'], new_pid), True)

    # archive last month's project
    log('disabling old project <%s>' % pid, True)
    r = requests.put('%s/%s/toggle' % (BASE_URL, pid), **REQUEST_HEADERS)
    if r.status_code != 200:
      log('could not archive old project <%s>' % pid, True)

# send email log
if len(LOG):
  requests.post(
    "https://api.mailgun.net/v2/%s/messages" % os.environ['MAILGUN_DOMAIN'],
    auth=("api", os.environ['MAILGUN_API_KEY']),
    data={"from": "Code & Craft Cron <no-reply@codeandcraft.nyc>",
          "to": os.environ['NOTIFY'],
          "subject": "Webfaction Cron: Harvest Monthly Budgets",
          "text": "\r\n".join(LOG) })


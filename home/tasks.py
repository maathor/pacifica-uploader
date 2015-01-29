from __future__ import absolute_import
from celery import shared_task, current_task
import sys

from bundler import bundle
from uploader import upload

#tag to show this def as a celery task
@shared_task
def upload_files(bundle_name='',
                instrument_name='',
                proposal='',
                file_list=None,
                groups=None,
                server='',
                user='',
                password=''):

    # initial state pushed through celery
    current_task.update_state("PROGRESS", meta={'Status': "Starting Bundle/Upload Process"})

    bundle(bundle_name=bundle_name,
           instrument_name=instrument_name,
           proposal=proposal,
           file_list=file_list,
           recursive=False,
           verbose=True,
           groups=groups)


    current_task.update_state(state="PROGRESS", meta={'Status': "Starting Upload"})

    res = upload(bundle_name=bundle_name,
                 protocol="https",
                 server=server,
                 user=user,
                 insecure=True,
                 password=password,
                 negotiate=False,
                 verbose=True)

    if res is None:
        current_task.update_state("FAILURE", \
            meta={'Status': "Uploader dieded. We don't know whyitded"})

    print >> sys.stderr, "upload completed"

    current_task.update_state("PROGRESS", meta={'Status': "Completing Upload Process"})

    if "http" in res:
        print >> sys.stderr, "Status Page: {0}".format(res)
        current_task.update_state(state='SUCCESS', meta={'url': res})
        return res
    else:
        current_task.update_state("FAILURE", meta={'Status': "No URL"})
        return "Upload Failed"
#pylint: disable=no-member
# justification:  dynamic methods

#pylint: disable=invalid-name
# justification: module level variables

"""
Django views, handle requests from the client side pages
"""

from __future__ import absolute_import

from django.conf import settings

from django.shortcuts import render_to_response
from django.template import RequestContext
from django.http import HttpResponseRedirect
from django.http import HttpResponse
from django.core.urlresolvers import reverse

import json

import datetime

from urlparse import urlparse

#operating system and platform
import os
import platform

#celery heartbeat
import psutil
from subprocess import call

#uploader
from uploader import test_authorization
from uploader import user_info

#database imports
from home.models import Filepath
from home.models import Metadata

#session imports
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib import auth
from django.contrib.auth.decorators import login_required

# celery tasks
from home import tasks

# delay for celery heartbeat
from time import sleep

class MetaData(object):
    """
    structure used to pass upload metadata back and forth to the upload page
    """

    label = ''
    value = ''
    name = ''

    def __init__(self):
        pass

class FolderMeta(object):
    """
    meta data about a folder, including filecount, directory count, and the total bytes.
    """

    fileCount = 0
    dir_count = 0
    totalBytes = 0

    def __init__(self):
        pass



class SessionData(object):
    """
    meta data about a folder, including filecount, directory count, and the total bytes.
    """

    user = ''
    user_full_name = ''
    password = ''

    current_user = None

    current_time = ''
    instrument = ''
    proposal_verbose = ''
    proposal_id = ''
    selected_dirs = []
    selected_files = []
    dir_sizes = []
    file_sizes = []
    directory_history = []

    # meta data values
    meta_list = []

    # proposals
    proposal_list = []

    # process that handles bundling and uploading
    bundle_process = None

# Module level variables
session_data = SessionData()

def login_user_locally(request):
    """
    if we have a new user, let's create a new Django user and log them
    in with a bogus password, "shrubbery".  Actual authentication will be done
    before this function is called.
    """
    username = request.POST['username']
    password = 'shrubbery'

    # does this user exist?
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        user = None

    if user is None:
        #create a new user
        user = User.objects.create_user(username=username, password=password)
        user.save()

    # we have a local user that matches the already validated EUS user
    # authenticate and log them in locally
    user = authenticate(username=username, password=password)
    if user is not None:
        if user.is_active:
            auth.login(request, user)


def celery_lives():
    """
    check to see if the celery process to bundle and upload is alive, alive!
    """
    for proc in psutil.process_iter():
        try:
            name = proc.name().lower()
            print name
            if name == 'celery.exe':
                return True
        except:
            pass
    return False

def start_celery():
    """
    starts the celery process
    """
    alive = celery_lives()
    if not alive:
        try:
            call(['StartCelery.bat', ''])
        except Exception,e:
            print e

    count = 0
    alive = False
    while not alive and count < 5:
        sleep (1)
        alive = celery_lives()
        count = count + 1

    return alive

def current_directory(history):
    """
    builds the current directory based on the navigation history
    """

    directory = ''
    for path in history:
        directory = os.path.join(directory, path)
        directory = directory + "/"

    return directory

def folder_size(folder):
    """
    recursively totals up total size of the files in the folder and sub folders
    """

    total_size = os.path.getsize(folder)
    for item in os.listdir(folder):
        itempath = os.path.join(folder, item)
        if os.path.isfile(itempath):
            total_size += os.path.getsize(itempath)
        elif os.path.isdir(itempath):
            total_size += folder_size(itempath)

    return total_size

def folder_meta(folder, meta):
    """
    gets the meta data for a folder
    number of folders
    number of files
    total size
    """

    meta.dir_count += 1

    for item in os.listdir(folder):
        itempath = os.path.join(folder, item)
        if os.path.isfile(itempath):
            meta.totalBytes += os.path.getsize(itempath)
            meta.fileCount += 1
        elif os.path.isdir(itempath):
            folder_meta(itempath, meta)

def file_tuples_recursively(folder, tuple_list, root_dir):
    """
    recursively gets file tuples for a folder
    """

    for item in os.listdir(folder):
        path = os.path.join(folder, item)
        if os.path.isfile(path):
            relative_path = path.replace(root_dir, '')
            tuple_list.append((path, relative_path))
        elif os.path.isdir(path):
            file_tuples_recursively(path, tuple_list, root_dir)

def file_tuples(selected_list, tuple_list, root_dir):
    """
    gets all the file tuples for a list of either folders or files
    tuples consist of the absolute path where the local file can be found
    and the relative path used to store the file in the archive
    """
    for path in selected_list:
        if os.path.isfile(path):
            # the relative path is the path without the root directory
            relative_path = path.replace(root_dir, '')
            tuple_list.append((path, relative_path))
        elif os.path.isdir(path):
            file_tuples_recursively(path, tuple_list, root_dir)

def upload_size_string(total_size):
    """
    returns the upload size as a string with the appropriate units
    """

    # less than a Kb show b
    if total_size < 1024:
        return str(total_size) + " b"
    # less than an Mb show Kb
    if total_size < 1048576:
        kilobytes = float(total_size) / 1024.0
        return str(round(kilobytes, 2)) + " Kb"
    # less than a Gb show Mb
    elif total_size < 1073741824:
        megabytes = float(total_size) / 1048576.0
        return str(round(megabytes, 2)) + " Mb"
    # else show in Gb
    else:
        gigabytes = float(total_size) / 1073741824.0
        return str(round(gigabytes, 2)) + " Gb"

def upload_meta_string(folder):
    """
    returns the meta data for a folder as a string to be displayed to the user
    """
    meta = FolderMeta()
    folder_meta(folder, meta)

    print '{0}|{1}'.format(str(meta.fileCount), str(meta.totalBytes))

    meta.dir_count -= 1
    meta_str = 'folders {0} | files {1} | {2}'.\
        format(str(meta.dir_count), str(meta.fileCount), upload_size_string(meta.totalBytes))

    return meta_str

def file_size_string(filename):
    """
    returns a string with the file size in appropriate units
    """

    total_size = os.path.getsize(filename)

    return upload_size_string(total_size)

@login_required(login_url=settings.LOGIN_URL)
def populate_upload_page(request):
    """
    formats the main uploader page
    """

    global session_data

    # if not logged in
    if session_data.password == '':
        # call login error with no error message
        b = request.user.is_authenticated()
        return login_error(request, '')

    root_dir = current_directory(session_data.directory_history)

    if root_dir == "": # first time through, initialize
        data_path = Filepath.objects.get(name="dataRoot")
        if data_path is not None:
            root_dir = data_path.fullpath
        elif "Linux" in platform.platform(aliased=0, terse=0):
            root_dir = "/home"
        else:
            root_dir = "c:\\"

        if root_dir.endswith("\\"):
            root_dir = root_dir[:-1]
        session_data.directory_history.append(root_dir)
        root_dir = current_directory(session_data.directory_history)

        # create a list of metadata entries to pass to the list upload page
        for meta in Metadata.objects.all():
            meta_entry = MetaData()
            meta_entry.label = meta.label
            meta_entry.name = meta.name
            meta_entry.value = ""
            session_data.meta_list.append(meta_entry)

    checked_dirs = []
    unchecked_dirs = []
    checked_files = []
    unchecked_files = []

    contents = os.listdir(root_dir)

    for path in contents:
        full_path = os.path.join(root_dir, path)

        if os.path.isdir(full_path):
            if full_path in session_data.selected_dirs:
                checked_dirs.append(path)
            else:
                unchecked_dirs.append(path)
        else:
            if full_path in session_data.selected_files:
                checked_files.append(path)
            else:
                unchecked_files.append(path)

    # Render list page with the documents and the form
    return render_to_response('home/uploader.html', \
        {'instrument': session_data.instrument,
         'proposalList': session_data.proposal_list,
         'proposal':session_data.proposal_verbose,
         'directoryHistory': session_data.directory_history,
         'metaList': session_data.meta_list,
         'checkedDirs': checked_dirs,
         'uncheckedDirs': unchecked_dirs,
         'checkedFiles': checked_files,
         'uncheckedFiles': unchecked_files,
         'selectedDirs': session_data.selected_dirs,
         'dirSizes': session_data.dir_sizes,
         'selectedFiles': session_data.selected_files,
         'fileSizes': session_data.file_sizes,
         'current_time': session_data.current_time,
         'user': session_data.user_full_name
        },
                              context_instance=RequestContext(request))

def spin_off_upload(request, s_data):
    """
    spins the upload process off to a background celery process
    """

    # check to see if background celery process is alive
    # if not, start it.  Wait 5 seconds, if it doesn't start,
    # we're boned.
    alive = start_celery()
    print 'Celery lives = %s' % (alive)
    if not alive:
        return render_to_response('home/status.html', \
                                 {'instrument': s_data.instrument,
                                  'status': 'Upload processor has failed',
                                  'proposal':s_data.proposal_verbose,
                                  'metaList':s_data. meta_list,
                                  'current_time': s_data.current_time,
                                  'user': s_data.user_full_name},
                                 context_instance=RequestContext(request))


    root_dir = current_directory(s_data.directory_history)

    # get the meta data values from the post
    for meta in s_data. meta_list:
        value = request.POST.get(meta.name)
        if value:
            meta.value = value

    # get the selected proposal string from the post
    s_data.proposal_verbose = request.POST.get("proposal")

    # split the proposal string into ID and description
    split = s_data.proposal_verbose.split()
    s_data.proposal_id = split[0]

    # get the root directory from the database
    data_path = Filepath.objects.get(name="dataRoot")
    if data_path is not None:
        root_dir = data_path.fullpath
    else:
        # handle error here
        root_dir = ""

    # get the correct \/ orientation for the OS
    root = root_dir.replace("\\", "/")

    #create a list of tuples (filepath, arcpath)
    tuples = []
    file_tuples(s_data.selected_files, tuples, root)
    file_tuples(s_data.selected_dirs, tuples, root)

    # create the groups dictionary
    #{"groups":[{"name":"FOO1", "type":"Tag"}]}
    groups = {}
    for meta in s_data.meta_list:
        groups[meta.name] = meta.value

    s_data.current_time = datetime.datetime.now().strftime("%m.%d.%Y.%H.%M.%S")

    target_path = Filepath.objects.get(name="target")
    if target_path is not None:
        target_dir = target_path.fullpath
    else:
        target_dir = root_dir

    bundle_name = os.path.join(target_dir, s_data.current_time + ".tar")

    server_path = Filepath.objects.get(name="server")
    if server_path is not None:
        full_server_path = server_path.fullpath
    else:
        #handle error here
        full_server_path = "dev1.my.emsl.pnl.gov"

    # spin this off as a background process and load the status page
    s_data.bundle_process = \
                tasks.upload_files.delay(bundle_name=bundle_name,
                                         instrument_name=s_data.instrument,
                                         proposal=s_data.proposal_id,
                                         file_list=tuples,
                                         groups=groups,
                                         server=full_server_path,
                                         user=s_data.user,
                                         password=s_data.password)

    return render_to_response('home/status.html', \
                {'instrument': s_data.instrument,
                 'status': 'Starting Upload',
                 'proposal':s_data.proposal_verbose,
                 'metaList':s_data. meta_list,
                 'current_time': s_data.current_time,
                 'user': s_data.user},
                              context_instance=RequestContext(request))

def clear_upload_lists(s_data):
    """
    clears the directory and file lists
    """
    s_data.selected_files = []
    s_data.selected_dirs = []

def modify(request):
    """
    modifies the data underlying the main upload page depending on the request
    the main request catagories are:
        file sytem navigation
        selected list management
        upload request
    """

    print 'modify ' + request.get_full_path()

    global session_data

    root_dir = current_directory(session_data.directory_history)

    if request.POST:

        print request.POST

        if request.POST.get("Clear"):
            clear_upload_lists(session_data)

        if request.POST.get("Upload Files & Metadata"):
            return spin_off_upload(request, session_data)

    else:
        value_pair = urlparse(request.get_full_path())
        params = value_pair.query.split("=")
        mod_type = params[0]
        path = params[1]

        # spaces
        path = path.replace("%20", " ")
        # backslash
        path = path.replace("%5C", "\\")

        full = os.path.join(root_dir, path)

        if mod_type == 'enterDir':
            root_dir = os.path.join(root_dir, path)
            session_data.directory_history.append(path)

        elif mod_type == 'toggleFile':
            if full not in session_data.selected_files:
                session_data.selected_files.append(full)
                session_data.file_sizes.append(file_size_string(full))
            else:
                index = session_data.selected_files.index(full)
                session_data.selected_files.remove(full)
                del session_data.file_sizes[index]

        elif mod_type == 'toggleDir':
            if full not in session_data.selected_dirs:
                session_data.selected_dirs.append(full)
                session_data.dir_sizes.append(upload_meta_string(full))
            else:
                index = session_data.selected_dirs.index(full)
                session_data.selected_dirs.remove(full)
                del session_data.dir_sizes[index]

        elif mod_type == "upDir":
            index = int(path)
            del session_data.directory_history[index:]
            print current_directory(session_data.directory_history)

    return HttpResponseRedirect(reverse('home.views.populate_upload_page'))

"""
login and login related accesories
"""
#########################################################################################
def login_error(request, error_string):
    """
    returns to the login page with an error message
    """
    return render_to_response(settings.LOGIN_VIEW, {'message': error_string}, context_instance=RequestContext(request))

def populate_user_info(session_data, info):
    """
    parses user information from a json struct
    """
    try:
        info = json.loads(info)
    except Exception:
        return 'Unable to parse user information'

    print json.dumps(info, sort_keys=True, indent=4, separators=(',', ': '))

    first_name = info["first_name"]
    if not first_name:
        first_name = '';
    last_name = info["last_name"]
    if not last_name:
        last_name = ''

    session_data.user_full_name = '%s (%s %s)' % (session_data.user, first_name, last_name);

    instruments = info["instruments"]

    valid_instrument = False
    for inst_id, inst_block in instruments.iteritems():
        inst_name = inst_block.get("instrument_name")
        inst_str = inst_id + "  " + inst_name
        if session_data.instrument == inst_id:
            valid_instrument = True
        print inst_str
        print ""

    if not valid_instrument:
        return 'User is not valid for this instrument'

    """
    need to filter proposals based on the existing instrument 
    if there is no valid proposal for the user for this instrument
    throw and error
    """
    print "props"
    props = info["proposals"]
    session_data.proposal_list = []
    for prop_id, prop_block in props.iteritems():
        title = prop_block.get("title")
        prop_str = prop_id + "  " + title
        # session_data.proposal_list.append(prop_str)

        # list only proposals valid for this instrument
        instruments = prop_block.get("instruments")

        try:
            if instruments is not None and instruments.count > 0:
                for inst_id in instruments: # eh.  inst_id is a list of 1 element.
                    id = str(inst_id[0])
                    if session_data.instrument == id:
                        session_data.proposal_list.append(prop_str)

        except Exception, err:
            print err.msg

    if len(session_data.proposal_list) == 0:
        return 'No valid proposals for this user on this instrument'

    # no errors found
    return ''

def cookie_test(request):
    """
    This test needs to be called twice in a row.  The first call should fail as the
    cookie hasn't been set.  The second should succeed.  If it doesn't, 
    you need to enable cookies on the browser.
    """
    # test that the browser is supporting cookies so we can maintain our session state
    if request.session.test_cookie_worked():
        request.session.delete_test_cookie()
        return render_to_response('home/cookie.html', {'message': 'Cookie Success'}, context_instance=RequestContext(request))
    else:
        request.session.set_test_cookie()
        return render_to_response('home/cookie.html', {'message': 'Cookie Failure'}, context_instance=RequestContext(request))

def login(request):
    """
    Logs the user in
    If the login fails for whatever reason, authentication, invalid for instrument, etc.,
    returns to login page with error.
    Otherwise, gets the user data to populate the main page
    """

    global session_data

    # ignore GET
    if not request.POST:
        return login_error(request, '')

    """
    # check to see if there is an existing user logged in
    if (session_data.current_user):
        # if the current user is still logged in, throw an error
        if (session_data.current_user.is_authenticated()):
            return login_error(request, 'User %s is currently logged in' % session_data.user_full_name)
    # if this was the last user logged in, maintain the session state
    if (request.user is not session_data.current_user):
        cleanup_session(session_data)
    """

    cleanup_session(session_data)

    #even if this is the current user, we still need to re-authenticate them
    session_data.user = request.POST['username']
    session_data.password = request.POST['password']

    server_path = Filepath.objects.get(name="server")
    if server_path is not None:
        full_server_path = server_path.fullpath
    else:
        return login_error(request, 'Server path does not exist')

    # test to see if the user authorizes against EUS
    authorized = test_authorization(protocol="https",
                                    server=full_server_path,
                                    user=session_data.user,
                                    password=session_data.password)
    if not authorized:
        return login_error(request, 'User or Password is incorrect')

    # get the user's info from EUS
    info = user_info(protocol="https",
                        server=full_server_path,
                        user=session_data.user,
                        password=session_data.password)

    inst = Filepath.objects.get(name="instrument")
    if inst and inst is not '':
        session_data.instrument = inst.fullpath
    else:
        return login_error(request, 'This instrument is undefined')

    err_str = populate_user_info(session_data, info)
    if err_str is not '':
        return login_error(request, err_str)

    # if the user passes EUS authentication then log them in locally for our session
    login_user_locally(request)

    # did that work?
    if not request.user.is_authenticated():
        return login_error(request, 'Problem with local authentication')

    # ok, passed all EUS and local authorization tests, valid user data is loaded
    # keep a copy of the user so we can keep other users from stepping on them if they are still 
    # logged in
    session_data.current_user = request.user

    return HttpResponseRedirect(reverse('home.views.populate_upload_page'))

def cleanup_session(s_data):
    """
    resets a session to a clean state
    """

    s_data.meta_list = []
    s_data.bundle_process = None
    s_data.current_time = None
    s_data.dir_sizes = []
    s_data.directory_history = []
    s_data.file_sizes = []
    s_data.instrument = None
    s_data.proposal_id = None
    s_data.proposal_list = []
    s_data.selected_dirs = []
    s_data.selected_files = []
    s_data.user = ''
    s_data.password = ''
    s_data.user_full_name = ''

def logout(request):
    """
    logs the user out and returns to the main page
    which will bounce to the login page
    """

    # pass pylint
    request = request

    global session_data

    #logs out local user session
    # if the LOGOUT_URL is set to this view, we create a recursive call to here
    logout(request)

    return HttpResponseRedirect(reverse('home.views.login'))

def incremental_status(request):
    """
    updates the status page with the current status of the background upload process
    """
    # pass pylint
    request = request

    global session_data

    output = session_data.bundle_process.status
    if output is None:
        output = "FAILURE"
    state = output
    print state

    output = session_data.bundle_process.result
    if output is None:
        output = "FAILURE"
    result = output
    print result

    if result is not None:
        if "http" in result:
            state = 'DONE'
            result = result.strip('"')

    # create json structure
    retval = json.dumps({'state':state, 'result':result})

    return HttpResponse(retval)

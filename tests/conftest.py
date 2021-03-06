"""Module-wide fixtures for testing pumapy."""

# pylint: disable-msg=fixme

# TODO: pylint for Python2 complains about redefining an outer scope when using
# pytest fixtures, this is supposed to be fixed in newer versions, so it should
# be checked again after migration to Python3 (see pylint issue #1535):
# pylint: disable-msg=redefined-outer-name

import pytest

from pumapy.user import PpmsUser

__author__ = "Niko Ehrenfeuchter"
__copyright__ = __author__
__license__ = "gpl3"


def extend_raw_details(raw_details):
    """Helper function to extend a details dict with some additional elements.

    Creates a copy of the given dict with user details (created by the
    user_details_raw() and user_admin_details_raw() fixtures) and extends it
    with some details that are useful for the related tests.

    Parameters
    ----------
    raw_details : dict
        A dict with user details as created by the `user_details_raw()` and
        `user_admin_details_raw()` fixtures.

    Returns
    -------
    dict
        A copy of the provided dict extended by the keys 'fullname', 'expected'
        and 'api_response'.
    """
    details = raw_details.copy()
    details['fullname'] = "%s %s" % (details['lname'], details['fname'])
    details['expected'] = (
        'username: %s, email: %s, fullname: %s, ppms_group: %s, active: True' %
        (details['login'], details['email'], details['fullname'],
         details['unitlogin'])
    )
    details['api_response'] = (
        u'login,lname,fname,email,phone,bcode,affiliation,'
        u'unitlogin,mustchpwd,mustchbcode,active\r\n'
        '"%s","%s","%s","%s","%s","","","%s",false,false,true\r\n' %
        (details['login'], details['lname'], details['fname'],
         details['email'], details['phone'], details['unitlogin'])
    )

    return details


### raw user dicts ###

@pytest.fixture(scope="module")
def user_details_raw():
    """A dict with default user details matching a parsed API response.

    Provides a dict with user details that corresponds to the same format that
    is generated by the PpmsUser.from_response() constructor.

    Returns
    -------
    dict
    """
    return {
        u'active': True,
        u'affiliation': u'',
        u'bcode': u'',
        u'email': u'pumapy@python-facility.example',
        u'fname': u'PumAPI',
        u'lname': u'Python',
        u'login': u'pumapy',
        u'mustchbcode': False,
        u'mustchpwd': False,
        u'phone': u'+98 (76) 54 3210',
        u'unitlogin': u'pumapy_group'
    }


@pytest.fixture(scope="module")
def user_admin_details_raw():
    """A dict with default admin-user details matching a parsed API response.

    Provides a dict with user details of an admin user that corresponds to the
    same format that is generated by the PpmsUser.from_response() constructor.

    Returns
    -------
    dict
    """
    return {
        u'active': True,
        u'affiliation': u'',
        u'bcode': u'',
        u'email': u'pumapy-adm@python-facility.example',
        u'fname': u'PumAPI (Administrator)',
        u'lname': u'Python',
        u'login': u'pumapy-adm',
        u'mustchbcode': False,
        u'mustchpwd': False,
        u'phone': u'+98 (76) 54 3112',
        u'unitlogin': u'pumapy_group'
    }


### extended user dicts (with keys 'fullname', 'api_response', 'expected') ###

@pytest.fixture(scope="module")
def user_details(user_details_raw):
    """A dict with extended user details."""
    return extend_raw_details(user_details_raw)


@pytest.fixture(scope="module")
def user_admin_details(user_admin_details_raw):
    """A dict with extended administrator user details."""
    return extend_raw_details(user_admin_details_raw)


### PpmsUser objects ###

@pytest.fixture(scope="module")
def ppms_user(user_details):
    """Helper function to create a PpmsUser object with default values.

    Parameters
    ----------
    user_details : dict
        A dictionary with user details.

    Returns
    -------
    pumapy.user.PpmsUser
    """
    return PpmsUser(
        username=user_details['login'],
        email=user_details['email'],
        fullname=user_details['fullname'],
        ppms_group=user_details['unitlogin']
    )


@pytest.fixture(scope="module")
def ppms_user_admin(user_admin_details):
    """Helper function to create a PpmsUser object of an administrator user.

    Parameters
    ----------
    user_details : dict
        A dictionary with user details.

    Returns
    -------
    pumapy.user.PpmsUser
    """
    return PpmsUser(
        username=user_admin_details['login'],
        email=user_admin_details['email'],
        fullname=user_admin_details['fullname'],
        ppms_group=user_admin_details['unitlogin']
    )


@pytest.fixture(scope="module")
def ppms_user_from_response(user_details):
    """Helper function to create a PpmsUser object with default values.

    Parameters
    ----------
    user_details : dict
        A dictionary with user details.

    Returns
    -------
    pumapy.user.PpmsUser
    """
    return PpmsUser.from_response(user_details['api_response'])


### group details ###

@pytest.fixture(scope="module")
def group_details():
    """Helper function providing a dict with default group details.

    Returns
    -------
    dict
    """
    return {
        u'heademail': u'group-leader@python-facility.example',
        u'unitname': u'Python Core Facility',
        u'unitlogin': u'pumapy_group',
        u'unitbcode': u'pumapy_group',
        u'department': u'Scientific Software Support',
        u'headname': u'PythonGroup Supervisor',
        u'active': True,
        u'institution': u'Famous Research Foundation',
    }


### system detail dicts ###

@pytest.fixture(scope="module")
def system_details_raw():
    """A dict with default system details matching a parsed API response.

    Provides a dict with system details that corresponds to the same format that
    is consumed by the PpmsSystem.from_parsed_response() constructor.

    Returns
    -------
    dict
    """
    return {
        u'System id': u'31',
        u'Name': u'Python Development System',
        u'Localisation': u'VDI (Development)',
        u'Type': u'Virtualized Workstation',
        u'Core facility ref': u'2',
        u'Schedules': u'True',
        u'Active': u'True',
        u'Stats': u'True',
        u'Bookable': u'True',
        u'Autonomy Required': u'True',
        u'Autonomy Required After Hours': u'False',
    }


### mapping dicts for user fullname, system name, ... ###

@pytest.fixture(scope="module")
def fullname_mapping(ppms_user, ppms_user_admin):
    """A dict to map user "fullnames" to login / account names."""
    mapping = {
        ppms_user.fullname: ppms_user.username,
        ppms_user_admin.fullname: ppms_user_admin.username,
    }
    return mapping


@pytest.fixture(scope="module")
def systemname_mapping(system_details_raw):
    """A dict to map the system name to its ID."""
    mapping = {
        system_details_raw['Name']: int(system_details_raw['System id']),
    }
    return mapping


### booking / runningsheet details ###

@pytest.fixture(scope="module")
def runningsheet_response():
    """Example response text of a 'getrunningsheet' request.

    The runningsheet returned by this function has entries of four bookings
    (13:00-14:00, 18:00-19:00, 20:00-21:00, 22:00-23:00), all of the same
    user (pumapy) for the same system.

    Returns
    -------
    str
        The full (multi-line) text as produced by a getrunningsheet request.
    """
    txt = ('Location, Start time, End time, Object, User, Training, Assisted\n'
           '"VDI (Development)","13:00","14:00","Python Development System",'
           '"Python PumAPI","",""\n'
           '"VDI (Development)","18:00","19:00","Python Development System",'
           '"Python PumAPI","",""\n'
           '"VDI (Development)","20:00","21:00","Python Development System",'
           '"Python PumAPI","",""\n'
           '"VDI (Development)","22:00","23:00","Python Development System",'
           '"Python PumAPI","",""\n')
    return txt

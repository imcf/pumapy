"""Module-wide fixtures for testing pumapy."""

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


@pytest.fixture(scope="module")
def user_details(user_details_raw):
    """A dict with extended user details."""
    return extend_raw_details(user_details_raw)


@pytest.fixture(scope="module")
def user_admin_details(user_admin_details_raw):
    """A dict with extended administrator user details."""
    return extend_raw_details(user_admin_details_raw)


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

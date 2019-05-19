# -*- coding: utf-8 -*-

"""Access to the Stratocore PPMS booking system API.

Authors: Basil Neff <basil.neff@unibas.ch>
         Niko Ehrenfeuchter <nikolaus.ehrenfeuchter@unibas.ch
"""

# pylint: disable-msg=line-too-long
# pylint: disable-msg=invalid-name
# pylint: disable-msg=wrong-import-position
# pylint: disable-msg=broad-except
# pylint: disable-msg=logging-not-lazy
# pylint: disable-msg=dangerous-default-value

import logging
import re
from datetime import datetime, timedelta

import requests

from .system import PpmsSystem
from .user import PpmsUser


LOG = logging.getLogger(__name__)


def process_response_values(values):
    """Process (in-place) a list of strings, remove quotes, detect boolean etc.

    Check all (str) elements of the given list, remove surrounding double-quotes
    and convert 'true' / 'false' strings into Python booleans.

    Parameters
    ----------
    values : list(str)
        The list of strings that should be processed.

    Returns
    -------
    None
        Nothing is returned, the list's element are processed in-place.
    """
    # tell pylint that there is no real gain using enumerate here:
    # pylint: disable-msg=consider-using-enumerate
    for i in range(len(values)):
        values[i] = values[i].strip('"')
        if values[i] == 'true':
            values[i] = True
        if values[i] == 'false':
            values[i] = False

def dict_from_single_response(text, graceful=True):
    """Parse a two-line CSV response from PUMAPI and create a dict from it.

    Parameters
    ----------
    text : str
        The PUMAPI response with two lines: a header line and one data line.
    graceful : bool, optional
        Whether to continue in case the response text is inconsistent, i.e.
        having different number of fields in the header line and the data line,
        by default True. In graceful mode, any inconsistency detected in the
        data will be logged as a warning, in non-graceful mode they will raise
        an Exception.

    Returns
    -------
    dict
        A dict with the fields of the header line being the keys and the fields
        of the data line being the values. Values are stripped from quotes
        and converted to Python boolean values where applicable.

    Raises
    ------
    ValueError
        Raised when the response text is inconsistent and the `graceful`
        parameter has been set to false, or if parsing fails for any other
        unforeseen reason.
    """
    # TODO: use Python's CSV parser that is much more robust than the manual
    # string splitting approach below which will fail as soon as a field
    # contains a comma!
    try:
        lines = text.splitlines()
        if len(lines) != 2:
            LOG.warn('Response expected to have exactly two lines: %s', text)
            if not graceful:
                raise ValueError("Invalid response format!")
        header = lines[0].split(',')
        data = lines[1].split(',')
        process_response_values(data)
        if len(header) != len(data):
            msg = 'Splitting CSV data failed'
            LOG.warn('%s, header has %s fields whereas the data has %s fields!',
                     msg, len(header), len(data))
            if not graceful:
                raise ValueError(msg)
            minimum = min(len(header), len(data))
            if minimum < len(header):
                LOG.warn('Discarding header-fields: %s', header[minimum:])
                header = header[:minimum]
            else:
                LOG.warn('Discarding data-fields: %s', data[minimum:])
                data = data[:minimum]

    except Exception as err:
        msg = ('Unable to parse data returned by PUMAPI: %s - ERROR: %s' %
               (text, err))
        LOG.error(msg)
        raise ValueError(msg)

    parsed = dict(zip(header, data))
    return parsed


class PpmsConnection(object):

    """Connection object to communicate with a PPMS instance."""

    def __init__(self, url, api_key):
        """Constructor for the PPMS connection object.

        Open a connection to the PUMAPI defined in `url` and try to authenticate
        against it using the given API Key.

        Parameters
        ----------
        url : str
            The URL of the PUMAPI to connect to.
        api_key : str
            The API key to use for authenticating against the PUMAPI.

        Raises
        ------
        requests.exceptions.ConnectionError
            Raised in case authentication fails.
        """
        self.url = url
        self.api_key = api_key
        self.users = None
        self.systems = None

        if not self.__authenticate():
            msg = 'Authenticating against %s with key [%s...%s] FAILED!' % (
                url, api_key[:2], api_key[-2:])
            LOG.error(msg)
            raise requests.exceptions.ConnectionError(msg)

    def __authenticate(self):
        """Try to authenticate to PPMS using the `auth` request.

        Returns
        -------
        bool
            True if authentication was successful, False otherwise.
        """
        LOG.debug('Attempting authentication against %s with key [%s...%s]',
                  self.url, self.api_key[:2], self.api_key[-2:])
        response = requests.post(self.url, data={'action': 'auth',
                                                 'apikey': self.api_key})
        LOG.debug('Authenticate response: %s', response.text)

        # WARNING: the HTTP status code returned is not correct - it is always
        # `200` even if authentication failed, so we need to check the actual
        # response *TEXT* to check if we have succeeded:
        if 'request not authorized' in response.text.lower():
            LOG.warn('Authentication failed: %s', response.text)
            return False
        elif 'error' in response.text.lower():
            LOG.warn('Authentication failed with an error: %s', response.text)
            return False

        if response.status_code == requests.codes.ok:  # pylint: disable-msg=no-member
            LOG.info('Authentication succeeded, response=[%s]', response.text)
            LOG.debug('HTTP Status: %s', response.status_code)
            return True

        LOG.warn("Unexpected combination of response [%s] and status code [%s],"
                 " it' uncelar if the authentication was successful (assuming "
                 "it wasn't)", response.status_code, response.text)
        return False

    def request(self, action, parameters={}):
        """Generic method to submit a request to PPMS and return the result.

        This convenience method deals with adding the API key to a given
        request, submitting it to the PUMAPI and checking the response for some
        specific keywords indicating an error.

        Parameters
        ----------
        action : str
            The command to be submitted to the PUMAPI.
        parameters : dict, optional
            A dictionary with additional parameters to be submitted with the
            request.

        Returns
        -------
        requests.Response
            The response object created by posting the request.

        Raises
        ------
        requests.exceptions.ConnectionError
            Raised in case the request is not authorized.
        """
        req_data = {
            'action': action,
            'apikey': self.api_key,
        }
        req_data.update(parameters)

        response = requests.post(self.url, data=req_data)
        if 'request not authorized' in response.text.lower():
            msg = 'Not authorized to run action `%s`' % req_data['action']
            LOG.error(msg)
            raise requests.exceptions.ConnectionError(msg)

        return response

    ############ users / groups ############

    def get_users(self, active=False):
        """Get a list with all user IDs in the PPMS system.

        Parameters
        ----------
        active : bool, optional
            Request only users marked as active in PPMS, by default False.
            NOTE: "active" is a tri-state parameter in PPMS: "true", "false"
            or empty!

        Returns
        -------
        list
            A list of all (or active-only) user IDs in PPMS.
        """
        # TODO: describe format of returned list and / or give an example!
        parameters = dict()
        if active:
            parameters['active'] = 'true'

        response = self.request('getusers', parameters)

        users = response.text.splitlines()
        active_desc = "active " if active else ""
        LOG.info('%s %susers in the PPMS database', len(users), active_desc)
        LOG.debug(', '.join(users))
        return users

    def get_user_dict(self, login_name):
        """Get details on a given user from PPMS.

        Parameters
        ----------
        login_name : str
            The PPMS account / login name of the user to query.

        Returns
        -------
        dict
            A dict with the user details returned by the PUMAPI.

        Example
        -------
        >>> conn.get_user('pumapy')
        ... {u'active': u'true',
        ...  u'affiliation': u'""',
        ...  u'bcode': u'""',
        ...  u'email': u'"does-not-reply@facility.xy"',
        ...  u'fname': u'"PumAPI"',
        ...  u'lname': u'"Python"',
        ...  u'login': u'"pumapy"',
        ...  u'mustchbcode': u'false',
        ...  u'mustchpwd': u'false',
        ...  u'phone': u'"+98 (76) 54 3210"',
        ...  u'unitlogin': u'"Python Core Facility"'}

        Raises
        ------
        KeyError
            Raised in case the user account is unknown to PPMS.
        ValueError
            Raised if the user details can't be parsed from the PUMAPI response.
        """
        response = self.request('getuser', {'login': login_name})

        if not response.text:
            msg = "User [%s] is unknown to PPMS" % login_name
            LOG.error(msg)
            raise KeyError(msg)

        # EXAMPLE:
        # response.text = (
        #     u'login,lname,fname,email,phone,bcode,affiliation,unitlogin,'
        #     u'mustchpwd,mustchbcode,active\r\n'
        #     u'"pumapy","Python","PumAPI","does-not-reply@facility.xy","","",'
        #     u'"","Python Core Facility",false,false,true\r\n'
        # )
        fields, values = response.text.splitlines()
        fields = fields.split(',')
        values = values.split(',')
        if len(fields) != len(values):
            msg = 'Unable to parse user details: %s' % response.text
            LOG.warn(msg)
            raise ValueError(msg)

        details = dict(zip(fields, values))
        LOG.debug("Details for user [%s]: %s", login_name, details)
        return details

    def get_user(self, login_name):
        """Fetch user details from PPMS and create a PpmsUser object from it.

        Parameters
        ----------
        login_name : str
            The user's PPMS login name.

        Returns
        -------
        PpmsUser
            The user object created from the PUMAPI response.

        Raises
        ------
        KeyError
            Raised if the user doesn't exist in PPMS.
        """
        response = self.request('getuser', {'login': login_name})

        if not response.text:
            msg = "User [%s] is unknown to PPMS" % login_name
            LOG.error(msg)
            raise KeyError(msg)

        return PpmsUser.from_response(response.text)

    def get_admins(self):
        """Get all PPMS administrator users.

        Returns
        -------
        list(PpmsUser)
            A list with PpmsUser objects that are PPMS administrators.
        """
        response = self.request('getadmins')

        admins = response.text.splitlines()
        users = []
        for username in admins:
            user = self.get_user(username)
            users.append(user)
        LOG.debug('%s admins in the PPMS database: %s', len(admins),
                  ', '.join(admins))
        return users

    def get_groups(self):
        """Get a list of all groups in PPMS.

        Returns
        -------
        list(str)
            A list with the group identifiers in PPMS.
        """
        response = self.request('getgroups')

        groups = response.text.splitlines()
        LOG.debug('%s groups in the PPMS database: %s', len(groups),
                  ', '.join(groups))
        return groups

    def get_group(self, group_id):
        """Fetch group details from PPMS and create a dict from them.
        
        Parameters
        ----------
        group_id : str
            The group's identifier in PPMS, called 'unitlogin' there.
        
        Returns
        -------
        dict
            A dict with the group details, keys being derived from the header
            line of the PUMAPI response, values from the data line.
        """
        response = self.request('getgroup', {'unitlogin': group_id})
        LOG.debug("Group details returned by PPMS (raw): %s", response.text)

        details = dict_from_single_response(response.text)

        LOG.debug('Details of group %s: %s', group_id, details)
        return details

    def get_group_users(self, group_id):
        """
        Returns an array with all user objects in the given group.
        :param group_id:
        :return:
        """
        response = requests.post(self.url, data={'action': 'getgroupusers', 'unitlogin': group_id, 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get group users of %s from %s' % (group_id, self.url))
            raise requests.exceptions.ConnectionError('Not authorized to get group users of %s from %s' % (group_id, self.url))
        LOG.debug('Response text with group users: %s' % response.text)

        usernames = response.text.splitlines()
        LOG.debug('%s users in group %s: %s' % (len(usernames), group_id, ', '.join(usernames)))

        # Get user objects from user ids
        users = []
        for username in usernames:
            user = self.get_ppms_user(username)
            users.append(user)

        return users

    def get_user_experience(self, user_id=None, system_id=None):
        """"
        Returns an array with dictionaries of user experience.
        Example:
        [
            {u'last_res': u'n/a', u'booked_hours': u'0', u'last_train': u'n/a', u'used_hours': u'0', u'login': u'neffba00', u'id': u'26'},
            {u'last_res': u'2016/12/07', u'booked_hours': u'3.25', u'last_train': u'n/a', u'used_hours': u'0', u'login': u'neffba00', u'id': u'37'}
        ]

        If the user_id or system_id is given, only results of the given objects are returned.
        """
        # pylint: disable-msg=deprecated-lambda
        data = {'action': 'getuserexp', 'apikey': self.api_key}
        if user_id is not None and user_id is not '':
            data['login'] = user_id
        if system_id is not None and system_id is not '':
            data['id'] = system_id

        response = requests.post(self.url, data=data)
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get users experience of %s from %s' % (user_id, self.url))
            raise requests.exceptions.ConnectionError('Not authorized to get users experience of %s from %s' % (user_id, self.url))
        #LOG.debug('Response text with users experience: %s' % response.text)

        # First line is the header, therefore len(systems)-1
        LOG.debug('%s user experience in the PPMS database (Filter: user = %s, system = %s): [...]' % (len(response.text.splitlines())-1, user_id, system_id))
        # Try it whithout quotes
        text = response.text.replace('"', '')

        headers = text.splitlines()[0].split(',')
        headers = map(lambda x: x.strip(), headers)  # http://sametmax.com/les-listes-en-intentions-vs-map-en-python/
        experience_array = []
        for line in text.splitlines()[1:]:
            values = line.split(',')
            experience = dict()
            for index, header in enumerate(headers):
                # Convert to number if possible
                try:
                    experience[header] = float(values[index])
                except ValueError:
                    if 'n/a' in values[index]:
                        values[index] = None
                    experience[header] = values[index]
            experience_array.append(experience)
            #LOG.debug('Experience: %s' % experience)
        return experience_array


    def get_users_emails(self, active=False):
        """Assemble a list with all email addresses. WARNING: very slow!"""
        addr = list()
        for user in self.get_users(active=active):
            cur = self.get_user(user)['email'].strip('"').strip()
            if not cur:
                LOG.warn("--- WARNING: no email for user %s! ---" % user)
                continue
            LOG.info("%s: %s" % (user, cur))
            addr.append(cur)
        return addr

    ###########
    # RESOURCES
    ###########

    def get_systems(self, use_cached=True):
        """"
        Retuns an array of with System objects.
        Caches to systems.
        """
        # pylint: disable-msg=deprecated-lambda

        if self.systems is not None and use_cached:
            LOG.debug('System objects cached, return these.')
            return self.systems

        response = requests.post(self.url, data={'action': 'getsystems',
        'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get all systems from %s' % self.url)
            raise requests.exceptions.ConnectionError('Not authorized to get all systems from %s' % self.url)

        # First line is the header, therefore len(systems)-1
        LOG.debug('%s systems in the PPMS database: %s' % (len(response.text.splitlines())-1, ', '.join(response.text.splitlines())))
        # False and true are not escaped, escape them. Otherwise the will be a problem with the split (because headname contains a comma)
        text = re.sub(',false', ',"False"', response.text, flags=re.IGNORECASE)
        text = re.sub(',true', ',"True"', text, flags=re.IGNORECASE)
        # Suround numbers with hyphpens
        # http://stackoverflow.com/questions/5984633/python-re-sub-group-number-after-number
        text = re.sub(r',(\d+),', r',"\g<1>",', text)
        # http://stackoverflow.com/questions/17648999/python-re-sub-beginning-of-line-anchoring
        text = re.sub(r'^(\d+),', r'"\g<1>",', text, flags=re.M)
        text = re.sub(r',(\d+)$', r',"\g<1>"', text, flags=re.M)
        headers = text.splitlines()[0].split(',')
        headers = map(lambda x: x.strip(), headers)  # http://sametmax.com/les-listes-en-intentions-vs-map-en-python/
        system_array = []
        for line in text.splitlines()[1:]:
            values = line.split('","')
            # Remove hyphens from first and last value
            values[0] = values[0][1:]
            values[-1] = values[-1][:-1]

            details = {}
            for index, header in enumerate(headers):
                # Convert to real True/False objects
                if values[index] == 'True':
                    values[index] = True
                elif values[index] == 'False':
                    values[index] = False

                details[header] = values[index]

            system = PpmsSystem(details['System id'],
                                details['Name'],
                                details['Localisation'],
                                details['Type'],
                                details['Core facility ref'],
                                details['Schedules'],
                                details['Active'],
                                details['Stats'],
                                details['Bookable'],
                                details['Autonomy Required'],
                                details['Autonomy Required After Hours'])

            system.machine_catalogue = self.__get_machine_catalogue_from_system(system.name)

            system_array.append(system)
            #LOG.debug('System: %s' % system)

        # Cache it
        self.systems = system_array

        return system_array

    def get_system(self, system_id):
        """
        Returns the system with the given id. None if no system with given id is found.
        :param system_id:
        :return:
        """
        systems = self.get_systems()

        for system in systems:
            if system_id == system.id:
                LOG.debug('System with id %s found: %s' % (system_id, system))
                return system
        LOG.debug('Could not find a system with given id %s, return None' % system_id)
        return None

    def get_bookable_ids(self, localisation, name_contains):
        """Query PPMS for systems with a specific location and name.

        This method assembles a list of PPMS system IDs whose "localisation"
        (room) field matches a given string and where the system name contains
        at least one of the strings given as the `name_contains` parameter.

        Parameters
        ----------
        localisation : str
            A string that the system's "localisation" (i.e. the "Room" field in
            the PPMS web interface) has to match.
        name_contains : list(str)
            A list of valid names (categories) of which the system's name has to
            match at least one for being included. Supply an empty list for
            skipping this filter.

        Returns
        -------
        list(int)
            A list with PPMS system IDs matching all of the given criteria.
        """
        loc = localisation
        LOG.info('Querying PPMS for bookable systems with location %s', loc)
        system_ids = []
        for system in self.get_systems():
            if loc.lower() not in str(system.localisation).lower():
                LOG.debug('PPMS system [%s] location (%s) is NOT matching '
                          '(%s), ignoring', system.name,
                          system.localisation, loc)
                continue

            LOG.debug('Checking if PPMS system [%s] matches a valid category',
                      system.name)
            for valid_name in name_contains:
                if valid_name in system.name:
                    LOG.debug('System [%s] is a %s system', system.name, loc)
                    system_ids.append(system.id)
                    break

            if system.id not in system_ids:
                LOG.debug('System [%s] is NOT a %s system', system.name, loc)

        LOG.info('Found %s bookable %s systems', len(system_ids), loc)
        LOG.debug('PPMS IDs of bookable %s systems: %s', loc, system_ids)
        return system_ids

    def __get_system_with_name(self, system_name):
        """

        :param system_name:
        :return:
        """
        systems = self.get_systems()
        for system in systems:
            if system_name == system.name:
                LOG.debug('Sytem with name %s found: %s' % (system_name, system))
                return system

        LOG.warn('Could not find sytem with name %s. Return None' % system_name)
        return None

    def __get_machine_catalogue_from_system(self, system_name, catalogue_names=['Naboo', 'Dagobah', 'Tatooine', 'Hoth']):
        """
        Returns the VAMP machine catalogue/class ('Naboo', 'Dagobah', 'Tatooine', 'Hoth') from the system name.
        None if no corresponding catalogue is found.
        """

        for catalogue_name in catalogue_names:
            if catalogue_name.lower() in system_name.lower():
                LOG.debug('System %s belongs to VAMP machine catalogue %s' % (system_name, catalogue_name))
                return catalogue_name
        LOG.debug('Could not find a VAMP machine catalogue for system %s, return None' % system_name)
        return None

    ####################
    # SYSTEM/USER RIGHTS
    ####################

    def get_users_with_access_to_system(self, system_id):
        """"
        Returns an array of usernames.
        """

        LOG.debug('Get all users with access to system %s.' % system_id)

        response = requests.post(self.url, data={'action': 'getsysrights', 'id': system_id, 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get all systems from %s' % self.url)
            raise requests.exceptions.ConnectionError('Not authorized to get all systems from %s' % self.url)

        username_array = []
        for userright in response.text.split():
            values = userright.split(':')
            username = values[-1]
            if values[0].lower() == 'd':
                LOG.debug('User %s is deactivated (%s) at system %s, do not list user.' % (username, values[0], system_id))
                continue

            LOG.debug('User %s has type %s.' % (username, values[0]))
            username_array.append(username)

        LOG.debug('System %s has %s users with access: %s' % (system_id, len(username_array), ', '.join(username_array)))
        return username_array

    def give_user_access_to_system(self, username, system_id):
        """"
        Gives user access to given system (id).
        Returns True if everything went fine, False if there was a problem.
        """

        LOG.debug('Give user %s access to system %s.' % (username, system_id))

        response = requests.post(self.url, data={'action': 'setright', 'id': system_id, 'login': username, 'type': 'A', 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get all systems from %s' % self.url)
            raise requests.exceptions.ConnectionError('Not authorized to get all systems from %s' % self.url)

        LOG.debug('Response: %s' % response.text)
        if 'invalid user' in response.text.lower():
            LOG.debug('User %s does not exist in PPMS.' % username)
            return False
        elif 'error: ' in response.text.lower():
            LOG.debug('There was an error: %s' % response.text)
            return False
        elif 'done' in response.text.lower():
            LOG.debug('User %s successfully added to system %s' % (username, system_id))
            return True

        LOG.debug('Unknown return value, expect everything went fine: %s' % response.text)
        return True

    def remove_user_access_from_system(self, username, system_id):
        """"
        Removes access for user to given system (id).
        Returns True if everything went fine, False if there was a problem.
        """

        LOG.debug('Remove (Disable) access for user %s to system %s.' % (username, system_id))

        response = requests.post(self.url, data={'action': 'setright', 'id': system_id, 'login': username, 'type': 'D', 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get all systems from %s' % self.url)
            raise requests.exceptions.ConnectionError('Not authorized to get all systems from %s' % self.url)

        LOG.debug('Response: %s' % response.text)
        if 'invalid user' in response.text.lower():
            LOG.debug('User %s does not exist in PPMS.' % username)
            return False
        elif 'error: ' in response.text.lower():
            LOG.debug('There was an error: %s' % response.text)
            return False
        elif 'done' in response.text.lower():
            LOG.debug('User %s successfully disabled in system %s' % (username, system_id))
            return True

        LOG.debug('Unknown return value, expect everything went fine: %s' % response.text)
        return True

    #########
    # BOOKING
    #########

    def get_next_booking(self, system_id):
        """"
        Returns a dictionary with the following information:
        {
            user: <uid>
            start: <datetime>
            minutes_until_start: <minutes>
            session: <session_id>
        }

        If there is no upcoming booking, None is returned.
        """

        response = requests.post(self.url, data={'action': 'nextbooking', 'id': system_id, 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get next booking of %s from %s' % (system_id, self.url))
            raise requests.exceptions.ConnectionError('Not authorized to get next booking of %s from %s' % (system_id, self.url))
        LOG.debug('Response text with upcoming booking infos: %s' % response.text.splitlines())

        if not response.text.splitlines():
            LOG.debug('System with the id %s does not have an upcoming booking.' % system_id)
            return None
        # Extract info: username, minutes until booking, sessionid
        booking = response.text.splitlines()
        now = datetime.now().replace(second=0, microsecond=0)
        booking_dict = {'user': booking[0], 'start': now + timedelta(minutes=int(booking[1])), 'minutes_until_start': int(booking[1]), 'session': booking[2]}
        LOG.debug('Upcoming booking at system %s: %s' % (system_id, booking_dict))
        return booking_dict


    def get_current_booking(self, system_id):
        """
        Returns a dictionary with the following information:
        {
            user: <uid>
            end: <datetime>
            minutes_until_end: <minutes>
            session: <session_id>
        }

        If there is no current booking, None is returned.
        """


        response = requests.post(self.url, data={'action': 'getbooking', 'id': system_id, 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get current booking of %s from %s' % (system_id, self.url))
            raise requests.exceptions.ConnectionError('Not authorized to get current booking of %s from %s' % (system_id, self.url))
        LOG.debug('Response text with current booking infos: %s' % response.text.splitlines())

        if not response.text.splitlines():
            LOG.debug('System with the id %s does not have any booking at the moment.' % system_id)
            return None
        # Extract info: username, minutes until booking, sessionid
        booking = response.text.splitlines()
        now = datetime.now().replace(second=0, microsecond=0)
        booking_dict = {'user': booking[0], 'end': now + timedelta(minutes=int(booking[1])), 'minutes_until_end': int(booking[1]), 'session': booking[2]}
        LOG.debug('Current booking at system %s: %s' % (system_id, booking_dict))
        return booking_dict

    def get_running_sheet(self, core_facility_id, date=None, vamp_only=False):
        """
        Returns an array of reservation objects with all bookings of the given core facility and day.
        It takes a while, because it needs to loop over all users and systems, because the usernames and system names returned from PPMS are not the identifiers.
        :param core_facility_id: System.core_facility_ref()
        :param date: datetime object. If date is None, the current day is taken.
        :return:
        """
        # pylint: disable-msg=deprecated-lambda


        if date is None:
            date = datetime.now()

        date_string = date.strftime("%Y-%m-%d")
        response = requests.post(self.url, data={
            'action': 'getrunningsheet',
            'plateformid': '%s' % core_facility_id,
            'day': '%s' % date_string,
            'apikey': self.api_key
        })
        if 'request not authorized' in response.text.lower():
            LOG.debug('Not authorized to get running sheet from %s' % self.url)
            raise requests.exceptions.ConnectionError('Not authorized to get running sheet from %s' % self.url)

        # First line is the header, therefore len(systems)-1
        LOG.debug('%s bookings in the PPMS database for %s: %s' % (len(response.text.splitlines())-1, date_string, ', '.join(response.text.splitlines())))

        # {u'Training': u'', u'Assisted': u'', u'Object': u'VAMP-TEST1', u'Start time': u'14:30', u'End time': u'15:30', u'User': u'Neff Basil', u'Location': u'VAMP'}
        # {u'Training': u'', u'Assisted': u'', u'Object': u'TissueCyte 1000', u'Start time': u'17:00', u'End time': u'00:00', u'User': u'Li Jiagui', u'Location': u'182'},
        # {u'Training': u'', u'Assisted': u'', u'Object': u'Luke', u'Start time': u'09:00', u'End time': u'17:00', u'User': u'Schina Riccardo', u'Location': u'188'},
        # {u'Training': u'', u'Assisted': u'', u'Object': u'Zeiss LSM700 inverted', u'Start time': u'08:30', u'End time': u'09:00', u'User': u'Chaker Zayna', u'Location': u'725a - 7th floor'},
        # {u'Training': u'', u'Assisted': u'', u'Object': u'Zeiss LSM700 inverted', u'Start time': u'09:00', u'End time': u'13:00', u'User': u'Chaker Zayna', u'Location': u'725a - 7th floor'},
        # {u'Training': u'', u'Assisted': u'', u'Object': u'Leica SP5-II-Matrix', u'Start time': u'14:00', u'End time': u'17:00', u'User': u'Schellinx Niels', u'Location': u'187'}
        # ...

        # False and true are not escaped, escape them. Otherwise the will be a problem with the split
        text = re.sub(',false', ',"False"', response.text, flags=re.IGNORECASE)
        text = re.sub(',true', ',"True"', text, flags=re.IGNORECASE)
        #text = response.text.lower().replace(',false',',"false"')

        # Suround numbers with hyphpens
        # http://stackoverflow.com/questions/5984633/python-re-sub-group-number-after-number
        text = re.sub(r',(\d+),', r',"\g<1>",', text)
        # http://stackoverflow.com/questions/17648999/python-re-sub-beginning-of-line-anchoring
        text = re.sub(r'^(\d+),', r'"\g<1>",', text, flags=re.M)
        text = re.sub(r',(\d+)$', r',"\g<1>"', text, flags=re.M)

        if text == '':
            LOG.debug('No bookings at day %s' % date)
            return []

        headers = text.splitlines()[0].split(',')
        headers = [x.strip() for x in headers]
        reservation_array = []
        for line in text.splitlines()[1:]:
            values = line.split('","')
            # Remove hyphens from first and last value
            values[0] = values[0][1:]
            values[-1] = values[-1][:-1]

            booking = dict()
            for index, header in enumerate(headers):
                # Convert to real True/False objects
                if values[index] == 'True':
                    values[index] = True
                elif values[index] == 'False':
                    values[index] = False

                booking[header] = values[index]

            # Get Systems
            system = self.__get_system_with_name(booking['Object'])
            if system is None:
                LOG.warn('Could not find a system belonging to system name %s' % booking['Object'])
            else:
                LOG.debug('Booking %s belongs to system %s' % (booking, system))

            # Check if it is a VAMP machine
            if vamp_only and system.machine_catalogue is None:
                continue

            # Get User
            user = None
            userfullname = booking['User']
            if self.mysql_connection is not None:
                user = Common.get_user_from_fullname(self.mysql_connection, userfullname)
            if user is None:
                user = self.__get_ppms_user_with_fullname(userfullname)
                # Store it in the database if a VAMP reservation and user not yet in the db with ppms fields
                if user is not None and self.mysql_connection is not None and system.machine_catalogue is not None:
                    Common.update_user(self.mysql_connection, user)

            if user is None:
                LOG.warn('Could not find a user belonging to user fullname %s' % userfullname)
            else:
                LOG.debug('Booking %s belongs to user %s' % (booking['Object'], user))

            # Time
            start = date.replace(
                hour=int(booking['Start time'].split(':')[0]),
                minute=int(booking['Start time'].split(':')[1]),
                second=0,
                microsecond=0
            )
            end = date.replace(
                hour=int(booking['End time'].split(':')[0]),
                minute=int(booking['End time'].split(':')[1]),
                second=0,
                microsecond=0
            )
            start_hour = int(booking['Start time'].split(':')[0])
            start_min = int(booking['Start time'].split(':')[1])
            reservation_start = date.replace(second=0, microsecond=0)
            reservation_start = reservation_start.replace(hour=start_hour, minute=start_min)

            end_hour = int(booking['End time'].split(':')[0])
            end_min = int(booking['End time'].split(':')[1])
            reservation_end = date.replace(second=0, microsecond=0)
            reservation_end = reservation_end.replace(hour=end_hour, minute=end_min)

            # If reservation end = 00:00 -> add one day
            if end_hour == 00 and end_min == 00:
                LOG.debug('Reservation ends at midnight, add one day: %s' % booking['End time'].split(':'))
                reservation_end = reservation_end + timedelta(days=1)

            reservation = Reservation(user.username,
                                      system.system_id,
                                      system.machine_catalogue,
                                      start,
                                      reservation_end)

            reservation_array.append(reservation)
        return reservation_array


    ############ deprecated methods ############

    def get_ppms_user(self, ppms_user_id):
        """"
        Returns a user object from ppms.
        """
        # pylint: disable-msg=deprecated-lambda

        response = requests.post(self.url, data={'action': 'getuser',
                                                 'login' : ppms_user_id,
                                                 'apikey': self.api_key})
        if 'request not authorized' in response.text.lower():
            msg = 'Not authorized to get user %s from PPMS' % ppms_user_id
            LOG.warn(msg)
            raise requests.exceptions.ConnectionError(msg)

        LOG.debug('Response text with user infos: %s' % response.text)
        # login,lname,fname,email,phone,bcode,affiliation,unitlogin,mustchpwd,mustchbcode,active
        # "neffba00","Neff","Basil","basil.neff@unibas.ch","-","","","rainer.poehlmann",false,false,true

        # Quote false and true, otherwise they will cause issues with the split
        # as `headname` contains a comma:
        text = re.sub(',false', ',"false"', response.text, flags=re.DOTALL)
        text = re.sub(',true', ',"true"', text, flags=re.DOTALL)

        # Quote numbers:
        text = re.sub(r',(\d+),', r',"\g<1>",', text)
        text = re.sub(r'^(\d+),', r'"\g<1>",', text, flags=re.M)
        text = re.sub(r',(\d+)$', r',"\g<1>"', text, flags=re.M)

        headers = text.splitlines()[0].split(',')
        headers = [x.strip() for x in headers]
        values = text.splitlines()[1].split('","')
        # Remove quotes from first and last value
        values[0] = values[0][1:]
        values[-1] = values[-1][:-1]

        user_info = dict()
        for index, header in enumerate(headers):
            # LOG.debug('Index %s = %s = %s' % (index, header, values[index]))
            # Convert to objects
            if values[index] == 'true':
                user_info[header] = True
            elif values[index] == 'false':
                user_info[header] = False
            else:
                user_info[header] = values[index]

        user_fullname = '%s %s' % (user_info['fname'], user_info['lname'])
        ppms_user_fullname = '%s %s' % (user_info['lname'], user_info['fname'])

        user = User(user_info['login'],
                    user_fullname,
                    user_info['email'],
                    None,
                    ppms_fullname=ppms_user_fullname,
                    ppms_group=user_info['unitlogin'])
        return user


    def __get_ppms_user_with_fullname(self, user_fullname):
        """
        Tries to get the user from the user fullname (getrunningsheet).
        Because get_ppms_users and get_ppms_users do not return the fullname
        (fname and lname instead), it is not 100% sure if the user can be found
        (Return None).
        It is expected that the userfullname is "<lastname> <firstname>"
        (assigned in function get_ppms_user(userid)).
        :param user_fullname:
        :return:
        """
        users = self.get_users()
        for user in users:
            # Check for PPMS username
            if user.ppms_fullname != None:
                if user_fullname == user.ppms_fullname:
                    LOG.debug('User %s has ppms_fullname %s, therefore identical with given user fullname %s.' %
                                      (user, user.ppms_fullname, user_fullname))
                    return user
            elif user.fullname == user_fullname:
                LOG.debug('User fullname %s is identical with given user fullname %s.' %
                                  (user.fullname, user_fullname))
                return user

        LOG.debug('No user with fullname %s found, return None' % user_fullname)
        return None

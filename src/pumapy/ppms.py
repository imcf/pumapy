# -*- coding: utf-8 -*-

"""Access Stratocore's PPMS Utility Management API.

Authors: Niko Ehrenfeuchter <nikolaus.ehrenfeuchter@unibas.ch>
         Basil Neff <basil.neff@unibas.ch>
"""

# pylint: disable-msg=fixme

# pylint: disable-msg=dangerous-default-value

import logging
import os
import os.path

import requests

from .common import dict_from_single_response, parse_multiline_response
from .user import PpmsUser
from .system import PpmsSystem
from .booking import PpmsBooking


LOG = logging.getLogger(__name__)


class PpmsConnection(object):

    """Connection object to communicate with a PPMS instance."""

    # TODO: all methods returning a list of user objects (get_group_users,
    # get_admins, ...) should be refactored to return a dict with those objects
    # instead, having the username ('login') as the key.

    # TODO: implement caching systems, ... during the object's lifetime

    def __init__(self, url, api_key, timeout=10, cache=None):
        """Constructor for the PPMS connection object.

        Open a connection to the PUMAPI defined in `url` and try to authenticate
        against it using the given API key (or use cache-only mode if key is
        None). If an optional path to a caching location is specified, responses
        will be read from that location unless no matching file can be found
        there, in which case an on-line request will be done (with the response
        being saved to the cache path).

        Parameters
        ----------
        url : str
            The URL of the PUMAPI to connect to.
        api_key : str
            The API key to use for authenticating against the PUMAPI. If
            specified as 'None' authentication will be skipped and the
            connection is running in cache-only (local) mode.
        timeout : float, optional
            How many seconds to wait for the PUMAPI server to send a response
            before giving up, by default 10.
        cache : str, optional
            A path to a local directory for caching responses from PUMAPI in
            individual text files. Useful for testing and for speeding up
            slow requests like 'getusers'

        Raises
        ------
        requests.exceptions.ConnectionError
            Raised in case authentication fails.
        """
        self.url = url
        self.api_key = api_key
        self.timeout = timeout
        self.users = {}
        self.fullname_mapping = {}
        self.systems = None
        self.status = {
            'auth_state': 'NOT_TRIED',
            'auth_response': None,
            'auth_httpstatus': -1,
        }
        self.cache_path = cache

        # run in cache-only mode (e.g. for testing or off-line usage) if no API
        # key has been specified, skip authentication then:
        if api_key is not None:
            self.__authenticate()
        elif cache is None:
            raise RuntimeError("No API key *and* no cache path given, at least "
                               "one of them is required!")

    def __authenticate(self):
        """Try to authenticate to PPMS using the `auth` request.

        Raises
        ------
        requests.exceptions.ConnectionError
            Raised in case authentication failed for any reason.
        """
        LOG.debug('Attempting authentication against %s with key [%s...%s]',
                  self.url, self.api_key[:2], self.api_key[-2:])
        self.status['auth_state'] = 'attempting'
        response = self.request('auth')
        LOG.debug('Authenticate response: %s', response.text)
        self.status['auth_response'] = response.text
        self.status['auth_httpstatus'] = response.status_code

        # NOTE: an unauthorized request has already been caught be the request()
        # method above. Our legacy code was additionally testing for 'error' in
        # the response text - however, there doesn't seem to be a way to trigger
        # such a response, so we exclude it from testing (and coverage).
        if 'error' in response.text.lower():  # pragma: no cover
            self.status['auth_state'] = 'FAILED-ERROR'
            msg = 'Authentication failed with an error: %s' % response.text
            LOG.error(msg)
            raise requests.exceptions.ConnectionError(msg)

        status_ok = requests.codes.ok  # pylint: disable-msg=no-member

        if response.status_code != status_ok:  # pragma: no cover
            # NOTE: branch excluded from coverage as we don't have a known way
            # to produce such a response from the API
            LOG.warn("Unexpected combination of response [%s] and status code "
                     "[%s], it's unclear if authentication succeeded (assuming "
                     "it didn't)", response.status_code, response.text)
            self.status['auth_state'] = 'FAILED-UNKNOWN'

            msg = 'Authenticating against %s with key [%s...%s] FAILED!' % (
                self.url, self.api_key[:2], self.api_key[-2:])
            LOG.error(msg)
            raise requests.exceptions.ConnectionError(msg)

        LOG.info('Authentication succeeded, response=[%s]', response.text)
        LOG.debug('HTTP Status: %s', response.status_code)
        self.status['auth_state'] = 'good'
        return

    def request(self, action, parameters={}, skip_cache=False):
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
        skip_cache : bool, optional
            If set to True the request will NOT be served from the local cache,
            independent whether a matching response file exists there, by
            default False.

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

        response = None
        read_from_cache = False
        try:
            if skip_cache:  # pragma: no cover
                raise LookupError("Skipping the cache has been requested")
            response = self.__intercept_read(req_data)
            read_from_cache = True
        except LookupError as err:
            LOG.debug("Doing an on-line request: %s", err)
            response = requests.post(self.url,
                                     data=req_data,
                                     timeout=self.timeout)

        # store the response if it hasn't been read from the cache before:
        if not read_from_cache:
            self.__intercept_store(req_data, response)

        # NOTE: the HTTP status code returned is always `200` even if
        # authentication failed, so we need to check the actual response *TEXT*
        # to figure out if we have succeeded:
        if 'request not authorized' in response.text.lower():
            self.status['auth_state'] = 'FAILED'
            msg = 'Not authorized to run action `%s`' % req_data['action']
            LOG.error(msg)
            raise requests.exceptions.ConnectionError(msg)

        return response

    def __interception_path(self, req_data, create_dir=False):
        """Derive the path for a local cache file from a request's parameters.

        Parameters
        ----------
        req_data : dict
            The request's parameters, used to derive the name of the cache file.
        create_dir : bool, optional
            If set to True the cache directory will be created if necessary.
            Useful when adding responses to the cache. By default False.

        Returns
        -------
        str
            The full path to a file name identified by all parameters of the
            request (except credentials like 'apikey').
        """
        action = req_data['action']
        intercept_dir = os.path.join(self.cache_path, action)
        if create_dir and not os.path.exists(intercept_dir):  # pragma: no cover
            os.makedirs(intercept_dir)
            LOG.debug('Created dir to store response: %s', intercept_dir)

        signature = ""
        for key, value in req_data.iteritems():
            if key == 'action' or key == 'apikey':
                continue
            signature += "__%s--%s" % (key, value)
        if signature == '':
            signature = "__response"
        signature = signature[2:] + ".txt"
        intercept_file = os.path.join(intercept_dir, signature)
        return intercept_file

    def __intercept_read(self, req_data):
        """Try to read a cached response from a local file.

        Parameters
        ----------
        req_data : dict
            The request's parameters, used to derive the name of the cache file.

        Returns
        -------
        PseudoResponse
            The response text read from the cache file wrapped in a
            PseudoResponse object, or None in case no matching file was found in
            the local cache.

        Raises
        ------
        LookupError
            Raised in case no cache path has been set or no cache file matching
            the request parameters could be found in the cache.
        """

        # pylint: disable-msg=too-few-public-methods
        class PseudoResponse(object):
            """Dummy response object with attribs 'text' and 'status_code'."""
            def __init__(self, text):
                self.text = text
                self.status_code = 200

        if self.cache_path is None:
            raise LookupError("No cache path configured")

        intercept_file = self.__interception_path(req_data, create_dir=False)
        if not os.path.exists(intercept_file):  # pragma: no cover
            raise LookupError("No cache hit for [%s]" % intercept_file)

        with open(intercept_file, 'r') as infile:
            text = infile.read()
        LOG.debug('Read intercepted response text from [%s]', intercept_file)
        return PseudoResponse(text)

    def __intercept_store(self, req_data, response):
        """Store the response in a local cache file named after the request.

        Parameters
        ----------
        req_data : dict
            The request's parameters, used to derive the name of the cache file
            so it can be matched later when running the same request again.
        response : requests.Response
            The response object to store in the local cache.
        """
        if self.cache_path is None:
            return

        intercept_file = self.__interception_path(req_data, create_dir=True)

        with open(intercept_file, 'w') as outfile:
            outfile.write(response.text)
        LOG.debug('Wrote response text to [%s]', intercept_file)


    ############ users / groups ############

    def get_user_ids(self, active=False):
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
        >>> conn.get_user_dict('pumapy')
        ... {
        ...     u'active': True,
        ...     u'affiliation': u'',
        ...     u'bcode': u'',
        ...     u'email': u'pumapy@python-facility.example',
        ...     u'fname': u'PumAPI',
        ...     u'lname': u'Python',
        ...     u'login': u'pumapy',
        ...     u'mustchbcode': False,
        ...     u'mustchpwd': False',
        ...     u'phone': u'+98 (76) 54 3210',
        ...     u'unitlogin': u'pumapy'
        ... }

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
        #     u'login,lname,fname,email,'
        #     u'phone,bcode,affiliation,unitlogin,mustchpwd,mustchbcode,'
        #     u'active\r\n'
        #     u'"pumapy","Python","PumAPI","pumapy@python-facility.example",'
        #     u'"+98 (76) 54 3210","","","pumapy",false,false,'
        #     u'true\r\n'
        # )
        details = dict_from_single_response(response.text)
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
            The user object created from the PUMAPI response. The object will be
            additionally stored in the self.users dict using the login_name as
            the dict's key.

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

        user = PpmsUser.from_response(response.text)
        self.users[user.username] = user  # update / add to the cached user objs
        self.fullname_mapping[user.fullname] = user.username
        return user

    def get_users(self, force_refresh=False):
        """Get user objects for all (or cached) PPMS users.

        Parameters
        ----------
        force_refresh : bool, optional
            Re-request information from PPMS even if user details have been
            cached locally before, by default False.

        Returns
        -------
        dict(PpmsUser)
            A dict of PpmsUser objects with the username (login) as key.
        """
        if self.users and not force_refresh:
            LOG.debug("Using cached details for %s users", len(self.users))
        else:  # pragma: no cover
            self.update_users()

        return self.users

    def update_users(self, user_ids=[]):
        """Update cached details for a list of users from PPMS.

        Get the user details on a list of users (or all active ones) from PPMS
        and store them in the local cache. WARNING - very slow!

        Parameters
        ----------
        user_ids : list(str), optional
            A list of user IDs (login names) to request the cache for, by
            default [] which will result in all *active* users to be requested.
        """
        if not user_ids:
            user_ids = self.get_user_ids(active=True)

        LOG.debug("Updating details on %s users", len(user_ids))
        for user_id in user_ids:
            self.get_user(user_id)

        LOG.debug("Collected details on %s users", len(self.users))

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

        if not response.text:
            msg = "Group [%s] is unknown to PPMS" % group_id
            LOG.error(msg)
            raise KeyError(msg)

        details = dict_from_single_response(response.text)

        LOG.debug('Details of group %s: %s', group_id, details)
        return details

    def get_group_users(self, unitlogin):
        """Get all members of a group in PPMS.

        Parameters
        ----------
        unitlogin : str
            The group's login ("unique login or id" in the PPMS web interface).

        Returns
        -------
        list(PpmsUser)
            A list with PpmsUser objects that are members of this PPMS group.
        """
        response = self.request('getgroupusers', {'unitlogin': unitlogin})

        members = response.text.splitlines()
        users = []
        for username in members:
            user = self.get_user(username)
            users.append(user)
        LOG.debug('%s members in PPMS group [%s]: %s', len(members), unitlogin,
                  ', '.join(members))
        return users

    def get_user_experience(self, login=None, system_id=None):
        """Get user experience ("User rights") from PPMS.

        Parameters
        ----------
        login : str, optional
            An optional login name to request the experience / permissions for,
            by default None
        system_id : int, optional
            An optional system ID to request the experience / permissions for,
            by default None

        Returns
        -------
        list(dict)
            A list with dicts parsed from the user experience response.
        """
        data = dict()
        if login is not None:
            data['login'] = login
        if system_id is not None:
            data['id'] = system_id
        response = self.request('getuserexp', parameters=data)

        parsed = parse_multiline_response(response.text)
        LOG.debug('Received %s experience entries for filters [user:%s] and '
                  '[id:%s]', len(parsed), login, system_id)
        return parsed

    def get_users_emails(self, users=None, active=False):
        """Get a list of user email addresses. WARNING - very slow!

        Parameters
        ----------
        users : list(str), optional
            A list of login names to retrieve the email addresses for, if
            omitted addresses for all (or active ones) will be requested.
        active : bool, optional
            Request only addresses of users marked as active in PPMS, by default
            False. Will be ignored if a list of usernames is given explicitly.

        Returns
        -------
        list(str)
            Email addresses of the users requested.
        """
        emails = list()
        # TODO: use the cached user objects and remove the "no cover" pragma
        if users is None:  # pragma: no cover
            users = self.get_user_ids(active=active)
        for user in users:
            email = self.get_user_dict(user)['email']
            if not email:  # pragma: no cover
                LOG.warn("--- WARNING: no email for user %s! ---", user)
                continue
            LOG.debug("%s: %s", user, email)
            emails.append(email)

        return emails

    ############ resources ############

    def get_systems(self):
        """Get a dict with all systems in PPMS.

        Returns
        -------
        dict(PpmsSystem)
            A dict with PpmsSystem objects parsed from the PUMAPI response where
            the system ID (int) is used as the dict's key. If parsing a system
            fails for any reason, the system is skipped entirely.
        """
        systems = dict()
        response = self.request('getsystems')
        details = parse_multiline_response(response.text, graceful=False)
        for detail in details:
            try:
                system = PpmsSystem.from_parsed_response(detail)
            except ValueError as err:  # pragma: no cover
                LOG.error('Error processing `getsystems` response: %s', err)
                continue

            systems[system.system_id] = system

        LOG.debug('Found %s systems in PPMS', len(systems))

        return systems

    def get_systems_matching(self, localisation, name_contains):
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
        LOG.info('Querying PPMS for systems with location matching [%s] and '
                 'name matching any of %s', localisation, name_contains)
        system_ids = []
        systems = self.get_systems()
        for sys_id in systems:
            system = systems[sys_id]
            # LOG.debug(system)
            if loc.lower() not in str(system.localisation).lower():
                LOG.debug('PPMS system [%s] location (%s) is NOT matching '
                          '(%s), ignoring', system.name,
                          system.localisation, loc)
                continue

            LOG.debug('System [%s] is matching location [%s], checking if the '
                      'name is matching any of the valid pattern %s',
                      system.name, loc, name_contains)
            for valid_name in name_contains:
                if valid_name in system.name:
                    LOG.debug('System [%s] matches all criteria', system.name)
                    system_ids.append(sys_id)
                    break

            if sys_id not in system_ids:
                LOG.debug('System [%s] does NOT match a valid name: %s',
                          system.name, name_contains)

        LOG.info('Found %s bookable %s systems', len(system_ids), loc)
        LOG.debug('PPMS IDs of bookable %s systems: %s', loc, system_ids)
        return system_ids

    ############ system / user permissions ############

    def get_users_with_access_to_system(self, system_id):
        """Get a list of usernames allowed to book the system with the given ID.

        Parameters
        ----------
        system_id : int or int-like
            The ID of the system to query permitted users for.

        Returns
        -------
        list(str)
            A list of usernames ('login') with permissions to book the system
            with the given ID in PPMS.

        Raises
        ------
        ValueError
            Raised in case parsing the response failes for any reason.
        """
        users = list()

        response = self.request('getsysrights', {'id': system_id})
        # this response has a unique format, so parse it directly here:
        try:
            lines = response.text.splitlines()
            for line in lines:
                permission, username = line.split(':')
                if permission.upper() == 'D':
                    LOG.debug('User [%s] is deactivated for booking system '
                              '[%s], skipping', username, system_id)
                    continue

                LOG.debug('User [%s] has permission to book system [%s]',
                          username, system_id)
                users.append(username)

        except Exception as err:  # pragma: no cover
            msg = ('Unable to parse data returned by PUMAPI: %s - ERROR: %s' %
                   (response.text, err))
            LOG.error(msg)
            raise ValueError(msg)

        return users

    def set_system_booking_permissions(self, login, system_id, permission):
        """Set permissions for a user on a given system in PPMS.

        Parameters
        ----------
        username : str
            The username ('login') to allow for booking the system.
        system_id : int or int-like
            The ID of the system to add the permission for.
        permission : str
            The permission level to set for the user, one of:
            - 'D' (deactivated)
            - 'A' (autonomous)
            - 'N' (novice)
            - 'S' (superuser)

        Returns
        -------
        bool
            True in case setting permissions for the given username on the
            system with the specified ID succeeded (or if the user already had
            those permissions before), False otherwise.
        """

        def permission_name(shortname):
            """Closure to validate a permission level and return its long name.

            Parameters
            ----------
            shortname : str
                A single character defining the permission level.

            Returns
            -------
            str
                The long (human-readable) name of the permission level.

            Raises
            ------
            KeyError
                Raised in case an invalid permission level was given.
            """
            mapping = {
                'D': 'deactivated',
                'A': 'autonomous',
                'N': 'novice',
                'S': 'superuser',
            }
            try:
                return mapping[shortname]
            except KeyError:
                raise KeyError('Invalid permission [%s] given' % shortname)

        LOG.debug('Setting permission level [%s] for user [%s] on system [%s]',
                  permission_name(permission), login, system_id)

        parameters = {
            'id': system_id,
            'login': login,
           	'type': permission,
        }
        response = self.request('setright', parameters)

        # LOG.debug('Request returned text: %s', response.text)
        if response.text.lower().strip() == 'done':
            LOG.debug('User [%s] now has permission level [%s] on system [%s]',
                      login, permission_name(permission), system_id)
            return True

        if 'invalid user' in response.text.lower():
            LOG.warn("User [%s] doesn't seem to exist in PPMS", login)
        elif 'error: ' in response.text.lower():  # pragma: no cover
            LOG.error('Request resulted in an error: %s', response.text)
        else:  # pragma: no cover
            LOG.warn('Unexpected response, assuming the request failed: %s',
                     response.text)

        return False

    def give_user_access_to_system(self, username, system_id):
        """Add permissions for a user to book a given system in PPMS.

        Parameters
        ----------
        username : str
            The username ('login') to allow for booking the system.
        system_id : int or int-like
            The ID of the system to add the permission for.

        Returns
        -------
        bool
            True in case the given username now has the permissions to book the
            system with the specified ID (or if the user already had them
            before), False otherwise.
        """
        return self.set_system_booking_permissions(username, system_id, 'A')

    def remove_user_access_from_system(self, username, system_id):
        """Remove permissions for a user to book a given system in PPMS.

        Parameters
        ----------
        username : str
            The username ('login') to remove booking permissions on the system.
        system_id : int or int-like
            The ID of the system to modify the permission for.

        Returns
        -------
        bool
            True in case the given username now has the permissions to book the
            system with the specified ID (or if the user already had them
            before), False otherwise.
        """
        return self.set_system_booking_permissions(username, system_id, 'D')

    ############ bookings ############

    def get_booking(self, system_id, booking_type='get'):
        """Get the current or next booking of a system.

        Parameters
        ----------
        system_id : int or int-like
            The ID of the system in PPMS.
        booking_type : str, optional
            The type of booking to request, one of 'get' (requesting the
            currently running booking) and 'next' (requesting the next upcoming
            booking), by default 'get'.

        Returns
        -------
        PpmsBooking or None
            The booking object, or None if there is no booking for the system.

        Raises
        ------
        ValueError
            Raised if the specified `booking_type` is invalid.
        """
        valid = ['get', 'next']
        if booking_type not in valid:
            raise ValueError("Parameter 'booking_type' has to be one of %s but "
                             "was given as [%s]" % (valid, booking_type))

        response = self.request(booking_type + 'booking', {'id': system_id})

        if not response.text.strip():
            LOG.debug("System [%s] doesn't have upcoming bookings", system_id)
            return None

        return PpmsBooking.from_booking_request(response.text,
                                                booking_type,
                                                system_id)

    def get_current_booking(self, system_id):
        """Wrapper for get_booking() with 'booking_type' set to 'get'."""
        return self.get_booking(system_id, 'get')

    def get_next_booking(self, system_id):
        """Wrapper for get_booking() with 'booking_type' set to 'next'."""
        return self.get_booking(system_id, 'next')

    ############ deprecated methods ############

    # TODO: remove methods below with one of the next releases

    def _get_system_with_name(self, system_name):
        """Get the system ID from the system's name.

        Parameters
        ----------
        system_name : str
            The system name to look for in PPMS.

        Returns
        -------
        int
            The ID of the system with the given name or '-1' if no system with
            that name could be found.

        Raises
        ------
        DeprecationWarning
            This method will be removed in one of the next releases.
        """
        # raise DeprecationWarning('Use get_systems_matching() instead!')
        sys_ids = self.get_systems_matching('', [system_name])
        if sys_ids:
            return sys_ids[0]

        return -1

    def _get_machine_catalogue_from_system(self, system_name,
                                           catalogue_names=[]):
        """Get the machine catalog (location / category) of a system.

        WARNING: deprecated method from the legacy API!

        Parameters
        ----------
        system_name : str
            The name of the system to check PPMS for.
        catalogue_names : list(str), optional
            [description], by default []

        Returns
        -------
        str
            The machine catalog / location / category of the system. Will be an
            empty string ('') if none is found.
        """
        # raise DeprecationWarning('Use get_systems_matching() instead!')
        for category in catalogue_names:
            sys_ids = self.get_systems_matching(category, [system_name])
            if sys_ids:
                LOG.debug('Found system(s) %s to be in category [%s]',
                          sys_ids, category)
                return category

        LOG.warn('No category found for system [%s]', system_name)
        return ''

    def get_bookable_ids(self, localisation, name_contains):
        """Legacy method for getting IDs of specific systems (name + location).

        This method is not implemented any more, use get_systems_matching() with
        appropriate parameters to select the desired systems instead.
        """
        raise NotImplementedError('Use get_systems_matching() instead!')

    def get_system(self, system_id):
        """Legacy method for getting details of a specific system.

        This method is not implemented any more, use get_systems()[sys_id] with
        the related system ID instead.
        """
        raise NotImplementedError('Use get_systems()[system_id] instead!')

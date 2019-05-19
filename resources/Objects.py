# -*- coding: utf-8 -*-
# Author:       basil.neff@unibas.ch
# Date:         2017.05
# 
# Classes for all objects out of the database.

# pylint: disable-msg=line-too-long
# pylint: disable-msg=invalid-name
# pylint: disable-msg=wrong-import-position


# Unicode Filenames: https://stackoverflow.com/a/40346898
import sys
reload(sys)
sys.setdefaultencoding('utf-8')  # pylint: disable-msg=no-member


import logging
import datetime
import os
from __builtin__ import property

LOG = logging.getLogger(__name__)


def _minutes_since(timestamp, desc):
    """Calculate time elapsed in minutes since a given time stamp.

    Parameters
    ----------
    timestamp : datetime.datetime
        The time stamp to be compared to now.
    desc : str
        A description string of the time stamp to be used in log messages.

    Returns
    -------
    datetime.timedelta
        The time elapsed since the last session change.
    """
    now = datetime.datetime.now()
    try:
        # remove differences in seconds and microseconds
        now = now.replace(second=timestamp.second,
                          microsecond=timestamp.microsecond)
        elapsed = now - timestamp
    except Exception as ex:
        LOG.warn('Could not calculate time since %s [%s]: %s',
                 desc, timestamp, ex.message)
        return 0

    LOG.debug('Time since %s [%s]: %s', desc, timestamp, elapsed)
    return elapsed


class File(object):
    def __init__(self, hash, filename, directory, username, creation_date, modification_date, size_mb, notification_date, quarantine_date, deleted):
        self._hash              = hash
        self._filename          = filename
        self._directory         = directory
        self._username          = username
        self._creation_date     = creation_date
        self._modification_date = modification_date
        self._size_mb           = size_mb
        self._notification_date = notification_date
        self._quarantine_date   = quarantine_date
        self._deleted           = deleted

        self._expiry_date       = None

    @property
    def hash(self):
        return self._hash

    @property
    def filename(self):
        """
        Returns the filename without leading slash (separator)
        :return: 
        """
        if self._filename.startswith(os.path.sep):
            self._filename = self._filename[1:]
        return self._filename

    @property
    def directory(self):
        """
        Relative directory with slash at the end and NO slash in the beginning.
        :return: 
        """
        if not self._directory.endswith(os.path.sep):
            self._directory = '%s%s' % (self._directory, os.path.sep)
        if self._directory.startswith(os.path.sep):
            self._directory = '%s' % (self._directory[1:])
        return self._directory

    @property
    def filepath(self):
        """
        Returns the relative filepath with directory and filename. No slash in the beginning.
        The storage basepath is NOT included!
        :return: 
        """
        return '%s%s' % (self.directory, self.filename)

    @property
    def vamp_filepath(self):
        """
        Returns the absolute VAMP filepath with V:\ instead of username.
        :return: 
        """
        vamp_filepath = self.filepath.replace('%s' % (self.username), r'V:')
        return vamp_filepath

    @property
    def username(self):
        return '%s' % self._username

    @property
    def creation_date(self):
        return self._creation_date

    @property
    def modification_date(self):
        return self._modification_date

    @property
    def size_mb(self):
        return self._size_mb

    @property
    def notification_date(self):
        return self._notification_date

    @property
    def quarantine_date(self):
        return self._quarantine_date

    @property
    def deleted(self):
        return self._deleted

    @property
    def expiry_date(self):
        if self._expiry_date is None and self._quarantine_date is not None:
            return self._quarantine_date
        else:
            return self._expiry_date

    @expiry_date.setter
    def expiry_date(self, expiry_date):
        self._expiry_date = expiry_date


    def __str__(self):
        return '%s - Owner: %s - Created: %s - Modified: %s - %s MB - Notified: %s - Quarantine: %s - Deleted: %s' %\
               (self.filepath, self._username, self._creation_date, self._modification_date, self._size_mb, self._notification_date, self._quarantine_date, self._deleted)

    def __hash__(self):
        return self._hash


class Usage(object):

    def __init__(self, date, hostname, machine_catalogue, status, username, session_start, session_change):
        self._date              = date
        self._hostname          = hostname
        self._machine_catalogue = machine_catalogue
        self._status            = str(status)
        self._username          = str(username)
        self._session_start     = session_start
        self._session_change    = session_change

    @classmethod
    def from_query(cls, query_result):
        """Alternative constructor using a dict with DB query results.

        This is a temporary helper construct that should be removed (or turned
        into the actual class constructor to be precise), once all
        instantiations of the class have been migrated away from the old method.

        Parameters
        ----------
        query_result : dict
            A dictionary with the required keys to instantiate the class. Please
            see the constructor for details on which those are.

        Returns
        -------
        Usage
            A new instance of a Usage object.
        """
        # TODO: remove / merge method with actual constructor once all calling 
        # code has been migrated!
        LOG.debug("Instantiating a 'Usage' object from a DB query result.")
        return cls(
            date=query_result['date'],
            hostname=query_result['hostname'],
            machine_catalogue=query_result['machine_catalogue'],
            status=query_result['status'],
            username=query_result['username'],
            session_start=query_result['session_start'],
            session_change=query_result['session_change']
        )

    @property
    def date(self):
        return self._date

    @property
    def hostname(self):
        return self._hostname

    @property
    def machine_catalogue(self):
        return self._machine_catalogue

    @property
    def status(self):
        return self._status

    @property
    def username(self):
        return self._username

    @property
    def session_start(self):
        LOG.debug('Get session_start: %s', self._session_start)
        return self._session_start

    @property
    def session_change(self):
        return self._session_change

    @property
    def session_time(self):
        """Calculate elapsed time since session start in minutes.

        Returns
        -------
        datetime.timedelta
            The time elapsed since the session start.
        """
        return _minutes_since(self._session_start, 'session start')

    @property
    def session_change_time(self):
        """Calculate elapsed time since a session change in minutes.

        Returns
        -------
        datetime.timedelta
            The time elapsed since the last session change.
        """
        return _minutes_since(self._session_change, 'session change')

    def __str__(self):
        return '%s - hostname: %s - machine_catalogue: %s - status: %s - username: %s - session_start: %s - session_change: %s' %\
               (self.date, self.hostname, self.machine_catalogue, self.status, self.username, self.session_start, self.session_change)


class Storage(object):

    def __init__(self, date, username, num_files, size_mb):
        self._date      = date
        self._username  = username
        self._num_files = num_files
        self._size_mb   = size_mb

    @property
    def date(self):
        return self._date

    @property
    def username(self):
        return self._username

    @property
    def num_files(self):
        return self._num_files

    @property
    def size_mb(self):
        return self._size_mb

    def __str__(self):
        return '%s - username: %s - num_files: %s - size_mb: %s' %\
               (self.date, self.username, self.num_files, self.size_mb)


class Session(object):

    logger = logging.getLogger(__name__)

    def __init__(self, id, session_start, session_end, hostname, machine_catalogue, username):
        self._id                = id
        self._session_start     = session_start
        self._session_end       = session_end
        self._hostname          = hostname
        self._machine_catalogue = machine_catalogue
        self._username          = username

    def __str__(self):
        return '%s - session_start: %s - session_end: %s - hostname: %s - machine_catalogue: %s - username: %s' %\
               (self._id, self._session_start, self._session_end, self._hostname, self._machine_catalogue, self._username)

    @property
    def id(self):
        return self._id

    @property
    def session_start(self):
        return self._session_start

    @property
    def session_end(self):
        return self._session_end

    @property
    def session_time(self):
        self.logger.debug('Get session time from session_start %s and session_end %s.' % (self._session_start, self._session_end))
        return (self._session_end - self._session_start)

    @property
    def hostname(self):
        return self._hostname

    @property
    def machine_catalogue(self):
        return self._machine_catalogue

    @property
    def username(self):
        return self._username


class User(object):

    def __init__(self, username, fullname, email, expiry_days, ppms_fullname  = None, ppms_group = None, active = True):
        """
        Initialize a user, username is mandatory!
        firstname and lastname are optional (only supported from PPMS).
        :param username: 
        :param fullname: 
        :param email: 
        :param expiry_days: 
        """
        assert username is not None
        assert username != ''

        self._username   = u'%s'% username
        self._fullname   = u'%s'% fullname
        self._email      = str(email)
        self._expiry_days = expiry_days
        self._active     = active

        # PPMS fields
        self._ppms_fullname = ppms_fullname
        self._ppms_group    = ppms_group

    @property
    def username(self):
        return self._username

    @property
    def fullname(self):
        if self._fullname is None or self._fullname == '':
            return self._username
        else:
            return self._fullname

    @property
    def firstname(self):
        return self._firstname

    @property
    def lastname(self):
        return self._lastname

    @property
    def email(self):
        return self._email

    @property
    def expiry_days(self):
        return self._expiry_days

    @property
    def ppms_fullname(self):
        return self._ppms_fullname

    @property
    def ppms_group(self):
        return self._ppms_group

    @property
    def active(self):
        return self._active

    def __str__(self):
        return '%s' % self._username


###################
# PPMS
###################

class Reservation(object):

    logger = logging.getLogger(__name__)

    def __init__(self, username, ppms_system, machine_catalogue, reservation_start, reservation_end):
        #self.logger.debug('Reservation initialized: username: %s - system: %s - machine_cataloge: %s - reservation_start: %s - reservation_end: %s' %
        #				  (username, ppms_system, machine_catalogue, reservation_start, reservation_end))

        self._username          = username
        self._ppms_system       = ppms_system
        self._machine_catalogue = machine_catalogue
        self._reservation_start = reservation_start
        self._reservation_end   = reservation_end

    @property
    def username(self):
        return self._username

    @property
    def ppms_system(self):
        return self._ppms_system

    @ppms_system.setter
    def ppms_system(self, ppms_system):
        self._ppms_system = ppms_system

    @property
    def machine_catalogue(self):
        return self._machine_catalogue

    @property
    def reservation_start(self):
        return self._reservation_start

    @reservation_start.setter
    def reservation_start(self, reservation_start):
        self._reservation_start = reservation_start

    @property
    def reservation_end(self):
        return self._reservation_end

    @reservation_end.setter
    def reservation_end(self, reservation_end):
        self._reservation_end = reservation_end

    def __str__(self):
        return 'username: %s - system: %s - machine_cataloge: %s - reservation_start: %s - reservation_end: %s' % (self._username, self._ppms_system, self._machine_catalogue, self._reservation_start, self._reservation_end)

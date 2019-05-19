# -*- coding: utf-8 -*-
# Author:       basil.neff@unibas.ch
# Date:         2017.05
# 
# Common stuff

# Unicode Filenames: https://stackoverflow.com/a/40346898
import sys
reload(sys)
sys.setdefaultencoding('utf-8')  # pylint: disable-msg=no-member

import os
import mysql.connector
import smtplib
from email.mime.text import MIMEText
import random
import string
import psutil

from config import logger
from Objects import User

#############################
# General
#############################

def get_random_string(length = 8):
    """
    Returns a random string in the given length.
    https://stackoverflow.com/questions/2257441/random-string-generation-with-upper-case-letters-and-digits-in-python
    """
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))


#############################
# LOCK File
#############################

def is_process_running(lock_file):
    """
    Checks if the lock file does exist and the process is running: Returns True
    If the process does not exist, the lock file is removed: Returns False
    :return:
    """
    if not os.path.isfile(lock_file):
        logger.debug("Process not running, no lock file: %s", lock_file)
        return False

    # Check if the process in the lock file does still exist.
    lock_pid = None

    with open(lock_file, 'r') as infile:
        lock_pid = infile.readline()
        try:
            lock_pid = int(lock_pid) # Cast to int
        except Exception as ex:
            logger.warn('Failed casting lock_pid %s of lock file %s to int: %s',
                        lock_pid, lock_file, ex.message)
            lock_pid = None

    logger.debug('Checking if PID %s from lock file %s is running',
                 lock_pid, lock_file)

    pids = psutil.pids()

    if lock_pid is None:
        logger.info('Unable to parse PID from %s, assuming process is running',
                    lock_file)
        return True

    if lock_pid in pids:
        process_name = psutil.Process(lock_pid).name()
        logger.debug('PID %s from lock file %s is a running process: %s',
                     lock_pid, lock_file, process_name)
        return True

    # otherwise the lock file seems to be stale, so try to clean up:
    logger.debug('PID %s is not a running process, remoinge lock file %s',
                 lock_pid, lock_file)

    try:
        if not os.access(lock_file, os.W_OK):
            logger.debug('Changing permissions of %s to 0777', lock_file)
            os.chmod(lock_file, 0777)
    except Exception as ex:
        logger.warn('Changing permissions of %s failed', lock_file)
        logger.warn(ex)

    try:
        os.remove(lock_file)
    except Exception as ex:
        logger.warn('Removing lock file %s with pid %s FAILED: %s',
                    lock_file, lock_pid, ex.message)
        logger.debug(ex)
    return False


def create_lock_file(lock_file):
    """
    Creates a lock file with the process id in it.
    :return:
    """
    if os.path.isfile(lock_file):
        logger.warn('Lock file %s does already exist!' % lock_file)
        raise RuntimeError('Lock file %s does already exist, cannot create a new one.' % lock_file)

    pid = str(os.getpid())
    logger.debug('Create lock file %s with pid %s' % (lock_file, pid))
    try:
        file(lock_file, 'w').write(pid)
    except Exception as ex:
        logger.warn('Could not create lock file %s: %s' % (lock_file, ex.message))
        logger.debug(ex)
        return
    logger.debug('Lock file %s with pid %s created.' % (lock_file, pid))


def remove_lock_file(lock_file):
    """
    Removes the lock file.
    :return:
    """
    if os.path.isfile(lock_file):
        logger.debug('Remove lock file %s.' % lock_file)
        os.remove(lock_file)
    else:
        logger.debug('Lock file %s does not exist, nothing to do.' % lock_file)


########
# MySQL
########

def open_mysql_connection(hostname, username, password, database):
    """Establish a connection to the MySQL database.
    
    Parameters
    ----------
    hostname : str
        The MySQL database server (DNS name or IP address).
    username : str
        The username to use for authenticating against the MySQL server.
    password : str
        The password to use for authenticating against the MySQL server.
    database : str
        The name of the database to connect to.

    Returns
    -------
    MySQLConnection
        The MySQL connection object.
    """
    logger.debug('Trying to establish a MySQL connection to [%s] on host [%s]' +
                 ' as user [%s]', database, hostname, username)
    try:
        conn = mysql.connector.connect(user=username, password=password,
                                       host=hostname, database=database)
    except Exception as ex:
        logger.error("Establishing a MySQL connection failed: %s", ex.message)
        raise

    logger.info('New MySQL connection to [%s] on host [%s] as user [%s]: id=%s',
                database, hostname, username, conn.connection_id)
    return conn


def close_mysql_connection(mysql_connection):
    """
    Closes the given MySQL connection.
    :param mysql_connection: 
    :return: 
    """
    mysql_connection.close()
    logger.info('MySQL connection (id: %s) closed.' % (mysql_connection.connection_id))


def job_start(mysql_connection, task, description, remove_previous_tasks = False):
    """Add a job to the database with the current date and description.
    
    In case it is only requested when a job has been run the last time, set the
    parameter `remove_previous_tasks` to `True`. This will remove all jobs with
    the same name from the DB (given they are completed, i.e. `end_time` > 0).

    Parameters
    ----------
    mysql_connection : MySQLConnection
        The DB connection object.
    task : str
        The job (task) name.
    description : str
        A literal description of what the job does.
    remove_previous_tasks : bool, optional
        Remove all existing tasks with the same name given they are completed
        (default: False).
    
    Returns
    -------
    int
        The identifier of the job (required to terminate the job).
    """
    logger.debug('Add start of job with following description to database: %s' % description)

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.debug('Could not reconnect to MySQL: %s' % ex.message)


    # Remove task with task name
    if (remove_previous_tasks):
        logger.info('Remove "%s" tasks with end_time > 0 from jobs table', task)
        sql = 'DELETE FROM `jobs` WHERE `task`=%s AND end_time > 0;'
        logger.debug('SQL: %s' % sql)
        cursor = mysql_connection.cursor(buffered=True, dictionary=True)
        cursor.execute(sql, (task,))
        logger.debug('Executed following SQL Statement: %s' % cursor.statement)
        cursor.close()
        # Commit if autocommit is disabled
        if not mysql_connection.autocommit:
            logger.debug('Commit job remove previous tasks to database.')
            mysql_connection.commit()

    sql = 'INSERT INTO jobs (`start_time`, `task`, `description`) VALUES (NOW(), %s, %s);'

    cursor = mysql_connection.cursor(buffered=True, dictionary=True)
    cursor.execute(sql, (task, description))
    logger.debug('Executed following SQL Statement: %s' % cursor.statement)
    cursor.close()
    # Get identifier: https://stackoverflow.com/questions/2548493/how-do-i-get-the-id-after-insert-into-mysql-database-with-python
    identifier = cursor.lastrowid
    logger.debug('Identifier of job start: %s' % identifier)

    # Commit if autocommit is disabled
    if not mysql_connection.autocommit:
        logger.debug('Commit job start_time to database.')
        mysql_connection.commit()

    return identifier


def job_end(mysql_connection, identifier):
    logger.debug('Add end_time of job with identifier %s to database.' % identifier)

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.debug('Could not reconnect to MySQL: %s' % ex.message)

    sql = 'UPDATE `jobs` SET `end_time` = NOW() WHERE `id` = %s;'
    cursor = mysql_connection.cursor(buffered=True, dictionary=True)
    cursor.execute(sql, (identifier,)) # One paramater: https://bugs.mysql.com/bug.php?id=69657
    logger.debug('Executed following SQL Statement: %s' % cursor.statement)
    cursor.close()

    # Commit if autocommit is disabled
    if not mysql_connection.autocommit:
        logger.debug('Commit job end_time to database.')
        mysql_connection.commit()

    logger.debug('DB with job end_time updated.')


def insert_notification_to_DB(mysql_connection, username, task, description, hostname = None, session_start = None):

    logger.debug('Insert notification to db: username: %s, task: %s, description: %s, hostname: %s, session_start: %s' %
                 (username, task, description, hostname, session_start))

    # If a user object is given, convert it to a string.
    username = '%s' % username

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.debug('Could not reconnect to MySQL: %s' % ex.message)

    sql = 'INSERT INTO notifications (`date`, `username`, `task`, `description`, `hostname`, `session_start`) VALUES (NOW(), %s, %s, %s, %s, %s);'
    try:
        cursor = mysql_connection.cursor(buffered=True, dictionary=True)
        cursor.execute(sql, (username, task, description, hostname, session_start))
        logger.debug('Executed following SQL Statement: %s' % cursor.statement)
        cursor.close()
    except Exception as ex:
        logger.warn('Could not insert notification to db: %s' % ex.message)
        logger.debug(ex)

    # Commit if autocommit is disabled
    if not mysql_connection.autocommit:
        logger.debug('Commit notification %s of %s to database.' % (task, username))
        mysql_connection.commit()


def is_user_already_notified_about_open_session(mysql_connection,
                                                username, hostname,
                                                session_start,
                                                h_since_last_notify=(4*24)):
    """Check if a user has been notified about a session in the last N hours.
    
    Parameters
    ----------
    mysql_connection : MySQLConnection
        The database connection object
    username : str
        The username to check for notifications.
    hostname : str
        The host name that should be checked for notifications.
    session_start : datetime.datetime
        The time stamp of the session start.
    h_since_last_notify : int, optional
        Maximum time in hours since the last notification on this session has
        been sent to the particular user, by default 96h==4d (4*24).
    """
    logger.debug('Checking if user [%s] has already been notified about a ' +
                 'running session: hostname: %s, session_start: %s, ' +
                 'hours_since_last_notification: %s', username, hostname,
                 session_start, h_since_last_notify)

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.warn('Could not reconnect to MySQL: %s', ex.message)

    sql = """SELECT * FROM `notifications`
             WHERE
                 `username` = %s
                 AND `task` = 'disconnected'
                 AND `hostname` = %s
                 AND `session_start` = %s
                 AND `date` > DATE_SUB(NOW(), INTERVAL %s HOUR);
    """
    cursor = mysql_connection.cursor(buffered=True, dictionary=True)
    cursor.execute(sql, (username, hostname, session_start, h_since_last_notify))
    logger.debug('Executed following SQL Statement: %s', cursor.statement)
    num_results = len(cursor.fetchall())
    logger.debug('%s rows returned by query', num_results)
    cursor.close()

    if num_results > 0:
        logger.debug('User has already been notified about their session(s)')
        return True

    logger.debug('User has NOT YET been notified about their session(s)')
    return False


#######
# File
#######

def get_folders_of_files(files):
    """
    Returns all folders the given files are in.
    :param files: a list of files.
    :return: 
    """

    assert files is not None

    # If only one single file is given
    if not isinstance(files, list):
        files = [files]

    folders = []
    for file in files:
        basepath = os.path.dirname(file.vamp_filepath)
        # Slash at the end of the folder
        if not basepath.endswith(os.path.sep):
            basepath = '%s%s' % (basepath, os.path.sep)

        if basepath not in folders:
            folders.append(basepath)
    # Order
    folders.sort()

    logger.debug('Given %s files are in %s folders.' % (len(files), len(folders)))
    return folders


def get_size_of_files(files):
    """
    Returns the size of all given files in MB.
    Round it to one decimal place
    :param files: 
    :return: 
    """

    assert files is not None

    # If only one single file is given
    if not isinstance(files, list):
        logger.debug('Only a single file %s of %s MB is given.' % (files, files.size_mb))
        return int(files.size_mb)

    filesize = 0
    for file in files:
        try:
            filesize += file.size_mb
        except Exception as ex:
            logger.debug('Could not get filesize of file %s. Not the most important thing. Continue' % file)
            continue

    logger.debug('Given %s files have %s MB.' % (len(files), filesize))
    return int(filesize)


#######
# Email
#######

def send_email(recipient, subject, message, cc_recipient=None,
               sender='vamp@unibas.ch', smtp_server='smtp.unibas.ch'):
    raise NotImplementedError("Please use vamp.mail instead!")


###########
# DATE
###########

def strfdelta(timedelta):
    """
    Format a timedelta (without seconds):
    - 12 days 20:18h
    - 12:18h
    :param timedelta: 
    :return: 
    """
    try:
        # https://stackoverflow.com/questions/8906926/formatting-python-timedelta-objects
        if timedelta.days == 1:
            format = "{days} day {hours}:{minutes}h"
        elif timedelta.days > 1:
            format = "{days} days {hours}:{minutes}h"
        else:
            format = "{hours}:{minutes}h"
        d = {"days": timedelta.days}
        d["hours"], rem = divmod(timedelta.seconds, 3600)
        d["minutes"], d["seconds"] = divmod(rem, 60)
        d["minutes"] = "%02d" % d["minutes"] # with leading zeros
        d["seconds"] = "%02d" % d["seconds"] # with leading zeros
        return format.format(**d)
    except Exception as ex:
        logger.debug('Could not transform given timedelta (%s) to human readable date. Return given object' % timedelta)
        return timedelta


###############
# USER
###############

def get_all_vamp_users(mysql_connection, default_expiring_days = 30):
    """
    Returns all users as list with user objects
    """
    logger.debug('Get all VAMP users')

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.debug('Could not reconnect to MySQL: %s' % ex.message)

    query = """SELECT `username`, `fullname`, `email`, `ppms_group`, `ppms_fullname`, GREATEST(%d, `users`.`expiry_days`) as `expiry_days`, `active`
                FROM `users`
                WHERE `active` = 1;""" % (default_expiring_days)
    logger.debug('SQL query: %s' % query)
    cursor = mysql_connection.cursor(buffered=True, dictionary=True)
    cursor.execute(query)
    logger.debug('Query executed, %s rows returned.' % cursor.rowcount)
    # Prepare data
    users = []
    for row in cursor:
        username = row['username']
        fullname = row['fullname']
        email = row['email']
        expiry_days = row['expiry_days']
        active = row['active']

        ppms_fullname = row['ppms_fullname']
        ppms_group = row['ppms_group']
        user = User(username, fullname, email, expiry_days, ppms_fullname=ppms_fullname, ppms_group=ppms_group, active = active)
        users.append(user)
    cursor.close()
    logger.debug('Returned %s users.' % len(users))
    return users


def get_user_from_fullname(mysql_connection, user_fullname, default_expiring_days = 30):
    """
    Returns a user object, None if user does not exist.
    """
    logger.debug('Get user %s' % user_fullname)

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.debug('Could not reconnect to MySQL: %s' % ex.message)

    query = """SELECT `username`, `fullname`, `email`, `ppms_group`, `ppms_fullname`, GREATEST(%d, `users`.`expiry_days`) as `expiry_days`
                FROM `users`
                WHERE `fullname` = '%s' OR `ppms_fullname` = '%s'""" % (default_expiring_days, user_fullname, user_fullname)
    logger.debug('SQL query: %s' % query)
    cursor = mysql_connection.cursor(buffered=True, dictionary=True)
    cursor.execute(query)
    logger.debug('Query executed, %s rows returned.' % cursor.rowcount)
    # Prepare data
    user = None
    for row in cursor:
        username = row['username']
        fullname = row['fullname']
        email    = row['email']
        expiry_days = row['expiry_days']

        ppms_fullname = row['ppms_fullname']
        ppms_group = row['ppms_group']

        user = User(username, fullname, email, expiry_days, ppms_fullname=ppms_fullname, ppms_group=ppms_group)
    cursor.close()
    logger.debug('Returned user %s.' % user)
    return user


def update_user(mysql_connection, user):
    """
    Update the user in the database. Creates an entry if the user does not exist.
    :param user: 
    :return: 
    """
    logger.debug('Update user %s' % user)

    # Reconnect to MySQL if, maybe the session is closed.
    try:
        mysql_connection.reconnect(attempts=1, delay=0)
    except Exception as ex:
        logger.debug('Could not reconnect to MySQL: %s' % ex.message)

    query = """INSERT INTO users (`username`, `email`, `fullname`, `ppms_group`, `ppms_fullname`)
                VALUES ('%s', '%s', '%s', '%s', '%s')
                ON DUPLICATE KEY UPDATE `fullname`= '%s', `ppms_group`= '%s', `ppms_fullname`= '%s'""" % \
            (user.username, user.email, user.fullname, user.ppms_group, user.ppms_fullname, user.fullname,
             user.ppms_group, user.ppms_fullname)
    logger.debug('SQL query: %s' % query)
    cursor = mysql_connection.cursor(buffered=True, dictionary=True)
    cursor.execute(query)
    logger.debug('Query executed, %s rows returned.' % cursor.rowcount)
    cursor.close()
    logger.debug('User %s updated in DB.' % user)

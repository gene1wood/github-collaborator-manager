#!/usr/bin/python
# -*- coding: utf-8 -*-

import base64
import json
import logging
import traceback
from datetime import datetime
import yaml  # pip install PyYAML
from dateutil import tz  # pip install python-dateutil
import agithub.GitHub  # pip install agithub

DRYRUN=False


def logging_local_time_converter(secs):
    """Convert a UTC epoch time to a local timezone time for use as a logging
    Formatter

    :param secs: Time expressed in seconds since the epoch
    :return: a time.struct_time 8-tuple
    """
    from_zone = tz.gettz('UTC')
    to_zone = TIME_ZONE
    utc = datetime.fromtimestamp(secs)
    utc = utc.replace(tzinfo=from_zone)
    pst = utc.astimezone(to_zone)
    return pst.timetuple()


TIME_ZONE = tz.gettz('America/Los_Angeles')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if len(logging.getLogger().handlers) == 0:
    logger.addHandler(logging.StreamHandler())
logging.getLogger().setLevel(logging.INFO)
# fmt = "[%(levelname)s]   %(asctime)s.%(msecs)dZ  %(aws_request_id)s  %(message)s"
fmt = "[%(levelname)s] %(asctime)s %(message)s\n"
# datefmt = "%Y-%m-%dT%H:%M:%S"
datefmt = "%m/%d/%Y %H:%M:%S {}".format(TIME_ZONE.tzname(datetime.now()))
formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
formatter.converter = logging_local_time_converter
logging.getLogger().handlers[0].setFormatter(formatter)

# Disable boto logging
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('requests').setLevel(logging.CRITICAL)
logging.getLogger('urllib3').setLevel(logging.CRITICAL)

COLLABORATOR_FILENAME = '.well-known/collaborators.yaml'


def get_owner_and_repo_name(value, source_owner, source_repo):
    """Split a owner/repo returning both or raising an exception

    :param str value: A owner/repo value
    :param str source_owner: The owner of the repo containing the collaborator
           file referencing the owner/value value
    :param str source_repo: The repo name containing the collaborator
           file referencing the owner/value value
    :return: A two element list of the owner and repo
    """
    result = value.split('/')
    if len(result) != 2:
        raise Exception(
            '"%s" in %s/%s/%s appears to be a reference but '
            'is malformed' % (value, source_owner, source_repo,
                              COLLABORATOR_FILENAME))
    return result


def get_collaborator_file(ag, owner, repo_name):
    """Retrieve a collaborator file from a repo and return the contents

    :param agithub.GitHub.GitHub ag: A GitHub object
    :param str owner: A GitHub repository owner name
    :param str repo_name: A GitHub repository name
    :return: Dictionary of collaborator file contents
    """
    repo = "%s/%s" % (owner, repo_name)
    status, data = ag.repos[owner][repo_name].contents[COLLABORATOR_FILENAME].get()
    if status == 404:
        raise Exception('Repo %s/%s is missing a collaborator file at %s' %
                        (owner, repo_name, COLLABORATOR_FILENAME))
    if data['encoding'] == 'base64':
        content = base64.b64decode(data['content'])
    else:
        raise Exception(
            'Unexpected encoding %s in response to query for %s/%s' %
            (data['encoding'], repo, COLLABORATOR_FILENAME))
    try:
        result = yaml.load(content)
    except yaml.YAMLError, e:
        raise Exception('Unable to parse %s/%s due to %s' % (
            repo, COLLABORATOR_FILENAME, e))
    if 'collaborators' not in result:
        raise Exception('"collaborators" missing from %s/%s' % (
            repo, COLLABORATOR_FILENAME))
    return result

def fetch_collaborators(ag, owner, repo_name,
                        repo_collaborator_map=(None, None)):
    """Recursively fetch collaborators from COLLABORATOR_FILENAME and along the
    way trigger processing of any encountered collaborator files which list
    child collaborator files

    :param agithub.GitHub.GitHub ag: A GitHub object
    :param str owner: A GitHub repository owner name
    :param str repo_name: A GitHub repository name
    :param tuple repo_collaborator_map: An optional 2-tuple containing a repo
           name followed by a list of collaborators that have already been
           determined in this run
    :return: A 2-tuple with a list of collaborators' GitHub usernames first and
             a list of child repositories to update because the current repo
             collaborators have changed
    """
    desired_collaborators = []
    repo = "%s/%s" % (owner, repo_name)
    collaborator_repo_config = get_collaborator_file(ag, owner, repo_name)
    for collaborator in collaborator_repo_config['collaborators']:
        logger.debug(
            'Processing collaborator %s for repo %s'
            % (collaborator, repo))
        if '/' in collaborator:
            # Reference to parent collaborator file
            parent_owner, parent_repo_name = get_owner_and_repo_name(
                collaborator, owner, repo_name)
            parent_repo = '%s/%s' % (parent_owner, parent_repo_name)
            if repo_collaborator_map[0] != parent_repo:
                logger.debug(
                    'Fetching collaborator file %s/%s/%s because %s != %s'
                    % (parent_owner, parent_repo_name, COLLABORATOR_FILENAME,
                       repo_collaborator_map[0], parent_repo))
                parent_collaborators, _ = fetch_collaborators(
                    ag, parent_owner, parent_repo_name, repo_collaborator_map)
                desired_collaborators.extend(parent_collaborators)
            else:
                logger.debug(
                    'Appending desired_collaborators %s from repo %s with the '
                    'collaborators %s for repo %s because %s == %s'
                    % (desired_collaborators, repo, repo_collaborator_map[1],
                       parent_repo, repo_collaborator_map[0], parent_repo))
                desired_collaborators.extend(repo_collaborator_map[1])
        else:
            logger.debug(
                'Appending collaborator %s to desired_collaborators %s'
                % (collaborator, desired_collaborators))
            desired_collaborators.append(collaborator)
    if 'child_repos' in collaborator_repo_config:
        return desired_collaborators, collaborator_repo_config['child_repos']
    else:
        return desired_collaborators, []


def process_collaborator_file(
        ag, owner, repo_name, repo_collaborator_map=(None, None)):
    """Calling fetch_collaborators on an owner and repo_name, then compare the
    resulting list of collaborators against the existing collaborators and
    add and remove them in order to converge the state of the repo to what's
    in the collaborator file

    :param agithub.GitHub.GitHub ag: A GitHub object
    :param str owner: A GitHub repository owner name
    :param str repo_name: A GitHub repository name
    :param tuple repo_collaborator_map: An optional 2-tuple containing a repo
           name followed by a list of collaborators that have already been
           determined in this run
    :return:
    """
    repo = "%s/%s" % (owner, repo_name)
    try:
        logger.debug('Fetching collaborator file %s/%s'
                     % (repo, COLLABORATOR_FILENAME))
        desired_collaborators, child_repos = fetch_collaborators(
            ag, owner, repo_name, repo_collaborator_map)
    except Exception as e:
        logger.error("Uncaught exception thrown\n%s\n%s\n%s" % (
            e.__class__, e, traceback.format_exc()))
        logger.error('Unable to determine collaborators, exiting')
        return

    status, data = ag.repos[owner][repo_name].collaborators.get()
    current_collaborators = [x['login'] for x in data]

    status, data = ag.repos[owner][repo_name].invitations.get()
    invited_collaborators = {x['invitee']['login']: x['id'] for x in data}
    current_collaborators.extend(invited_collaborators.keys())
    if owner not in desired_collaborators:
        desired_collaborators.append(owner)
    logger.debug(
        'Desired collaborators for %s are %s and existing_collaborators are %s'
        % (repo, desired_collaborators, current_collaborators))
    collaborators_add = set(desired_collaborators) - set(current_collaborators)
    collaborators_remove = set(current_collaborators) - set(desired_collaborators)
    logger.debug('collaborators_add are %s and collaborators_remove are %s' %
                 (collaborators_add, collaborators_remove))
    for collaborator in collaborators_add:
        logger.info('Adding %s as a collaborator to %s'
                    % (collaborator, repo))
        if not DRYRUN:
            status, data = ag.repos[owner][repo_name].collaborators[collaborator].put()
            logger.debug("Add collaborator status is %s and data is %s"
                         % (status, data))
    for collaborator in collaborators_remove:
        if collaborator in invited_collaborators:
            invitation_id = invited_collaborators[collaborator]
            logger.info('Deleting collaboration invitation %s for %s to %s'
                        % (invitation_id, collaborator, repo))
            if not DRYRUN:
                status, data = ag.repos[owner][repo_name].invitations[invitation_id].delete()
                logger.debug("Delete invitation status is %s and data is %s"
                             % (status, data))
        else:
            logger.info('Removing %s as a collaborator to %s'
                        % (collaborator, repo))
            if not DRYRUN:
                status, data = ag.repos[owner][repo_name].collaborators[collaborator].delete()
                logger.debug("Remove collaborator status is %s and data is %s"
                             % (status, data))
    for child_repo in child_repos:
        child_owner, child_repo_name = get_owner_and_repo_name(
            child_repo, owner, repo_name)
        if not child_owner:
            continue
        process_collaborator_file(
            ag, child_owner, child_repo_name, (repo, desired_collaborators))


def lambda_handler(event, context):
    """Given an event determine if it's a GitHub webhook SNS `push` event and
    if so process the collaborator file for the repo in the SNS event

    :param event: A dictionary of metadata for an event
    :param context: The AWS Lambda context object
    :return:
    """
    if ('Records' not in event or
            type(event['Records']) != list or
            len(event['Records']) == 0 or
            type(event['Records'][0]) != dict or
            'EventSource' not in event['Records'][0] or
            event['Records'][0]['EventSource'] != 'aws:sns'):
        # Not an SNS published message
        # Note the upper case 'EventSource'
        return False

    logger.debug('Got event {}'.format(event))
    with open('config.yaml') as f:
        config = yaml.load(f.read())

    if ('github_token' not in config
            or config['github_token'] == '0123456789abcdef0123456789abcdef01234567'):
        logger.error(
            'github_token was not configured in config.yaml. Aborting')
        return False

    ag = agithub.GitHub.GitHub(token=config['github_token'])
    for message in [json.loads(x['Sns']['Message']) for x in event['Records']]:
        logger.debug('Message is %s' % message)
        if 'commits' not in message:
            # This is not a PushEvent webhook
            continue
        for commit in message['commits']:
            filenames_affected = set(
                commit['added'] + commit['removed'] + commit['modified'])
            if COLLABORATOR_FILENAME in filenames_affected:
                if DRYRUN:
                    logger.info('Running in dryrun mode')
                process_collaborator_file(
                    ag=ag, owner=message['repository']['owner']['name'],
                    repo_name=message['repository']['name']
                )
            else:
                logger.info('No %s file was affected. No changes made' %
                            COLLABORATOR_FILENAME)

# coding: utf8

from __future__ import unicode_literals
from logging import getLogger
import ckan.authz as authz
from ckan.common import _, config
from ckan.logic.action.get import resource_view_list
import ckan.lib.base as base
import ckan
from ckan.lib.mailer import mail_recipient
from ckan.lib.mailer import MailerException
import ckan.logic
from ckanext.restricted import logic as restricted_logic, auth
import ckan.lib.navl.dictization_functions as dictization_functions
from ckan.plugins import toolkit as tk
from ckan.lib.base import render as render_jinja2
import ckan.logic as logic
import ckan.plugins.toolkit as toolkit
from .logic import get_org_admins, send_request_mail_to_org_admins, restricted_get_restricted_dict, restricted_get_username_from_context
from .schemas import resource_request_access_schema
from .model import ResourceAndPackageAccessRequest
import os
from flask import request

DataError = dictization_functions.DataError
unflatten = dictization_functions.unflatten

try:
    # CKAN 2.7 and later
    from ckan.common import config
except ImportError:
    # CKAN 2.6 and earlier
    from pylons import config

log = getLogger(__name__)


_get_or_bust = ckan.logic.get_or_bust

NotFound = ckan.logic.NotFound
NotAuthorized = ckan.logic.NotAuthorized


@tk.chained_action
def restricted_user_create_and_notify(up_func, context, data_dict):

    def body_from_user_dict(user_dict):
        body = ''
        for key, value in user_dict.items():
            body += '* {0}: {1}\n'.format(
                key.upper(), value if isinstance(value, str) else str(value))
        return body

    user_dict = up_func(context, data_dict)

    # Send your email, check ckan.lib.mailer for params
    try:
        name = _('CKAN System Administrator')
        email = config.get('email_to')
        if not email:
            raise MailerException('Missing "email-to" in config')

        subject = _('New Registration: {0} ({1})').format(
            user_dict.get('name', _(u'new user')), user_dict.get('email'))

        extra_vars = {
            'site_title': config.get('ckan.site_title'),
            'site_url': config.get('ckan.site_url'),
            'user_info': body_from_user_dict(user_dict)}

        body = render_jinja2(
            'restricted/emails/restricted_user_registered.txt', extra_vars)

        mail_recipient(name, email, subject, body)

    except MailerException as mailer_exception:
        log.error('Cannot send mail after registration')
        log.error(mailer_exception)

    return (user_dict)


@logic.validate(resource_request_access_schema)
@tk.side_effect_free
def request_access_to_resource(context, data_dict):
    if toolkit.current_user.is_anonymous:
        log.info('this not authorized?')
        raise NotAuthorized
    user = toolkit.get_action('user_show')(
        {'user': os.environ.get('CKAN_SYSADMIN_NAME')}, {'id': toolkit.current_user.id})

    pkg = None
    res = None

    try:
        res = toolkit.get_action('resource_show')(
            {'ignore_auth': True}, {'id': data_dict.get('resource_id')})
    except toolkit.ObjectNotFound:
        raise NotFound('Resource not found')
    except Exception as e:
        log.error(e)
        return {
            'success': False,
            'errors': {'error': [_('Exception retrieving dataset to send mail')]},
            'error_summary': {_('error'): _('Exception retrieving dataset to send mail')},
        }

    try:
        pkg = toolkit.get_action('package_show')(
            context, {'id': res.get('package_id')})
        data_dict['pkg_dict'] = pkg
    except toolkit.ObjectNotFound:
        raise NotFound('Dataset not found')
    except Exception as e:
        log.error(e)
        return {
            'success': False,
            'errors': {'error': [_('Exception retrieving dataset to send mail')]},
            'error_summary': {_('error'): _('Exception retrieving dataset to send mail')},
        }

    if pkg.get('private'):
        return {
            'success': False,
            'errors': {'validation': [_('Dataset not found or private')]},
        }

    is_there_request_access_already_created_for_the_user = ResourceAndPackageAccessRequest.get_by_resource_user_and_status(
        res.get('id'), user.get('id'), 'pending')

    if len(is_there_request_access_already_created_for_the_user) > 0:
        return {
            'success': False,
            'errors': {'validation': [_('Request already created for this resource')]},
        }

    ResourceAndPackageAccessRequest.create(package_id=pkg.get('id'), user_id=user.get('id'), org_id=pkg.get(
        'organization').get('id'), message=data_dict.get('message'), resource_id=res.get('id'))

    site_title = os.environ.get('CKAN_FRONTEND_SITE_TITLE')

    email_notification_dict = {
        'user_id': user.get('id'),
        'site_title': site_title,
        'user_name': user.get('full_name') or user.get('display_name') or user.get('name'),
        'user_email': user.get('email'),
        'resource_name': res.get('name') or res.get('id'),
        'resource_id': res.get('id'),
        'package_id': pkg.get('id'),
        'package_name': pkg.get('name'),
        'user_organization': data_dict.get('user_organization', ''),
        'org_id': pkg.get('organization').get('id'),
        'package_type': pkg.get('type'),
        'message': data_dict.get('message'),
    }

    success = send_request_mail_to_org_admins(email_notification_dict)

    return {"success": success, 'message': 'Your request was sent successfully' if success else 'Your request was not registered'}


@tk.side_effect_free
def restricted_resource_view_list(context, data_dict):
    id = _get_or_bust(data_dict, 'id')
    # try:
    model = context['model']
    resource = model.Resource.get(id)
    if not resource:
        raise NotFound
    authorized = auth.restricted_resource_show(
        context, {'id': resource.get('id'), 'resource': resource}).get('success', False)

    if not authorized:
        return []

    return resource_view_list(context, data_dict)
    # except NotAuthorized:
    #     # Added validation because the CKAN view is not treating exceptions or empty lists
    #     if request.headers.get('Sec-Fetch-Site') == 'same-origin':
    #         base.abort(403, _(u'Unauthorized to read resource %s') % id)
    #     else:
    #         return []


@tk.side_effect_free
@tk.chained_action
def restricted_package_show(up_func, context, data_dict):
    package_metadata = up_func(context, data_dict)

    # Ensure user who can edit can see the resource
    if authz.is_authorized(
            'package_update', context, package_metadata).get('success', False):
        return package_metadata

    # Custom authorization
    if isinstance(package_metadata, dict):
        restricted_package_metadata = dict(package_metadata)
    else:
        restricted_package_metadata = dict(package_metadata.for_json())

    # restricted_package_metadata['resources'] = _restricted_resource_list_url(
    #     context, restricted_package_metadata.get('resources', []))
    restricted_package_metadata['resources'] = _restricted_resource_list_hide_fields(
        context, restricted_package_metadata.get('resources', []))

    # TODO check this validation after
    # restricted_package_metadata['resources'] = [x for x in restricted_package_metadata.get(
    #     'resources', []) if x.get('level', 'public') == 'public']

    restricted_package_metadata['num_resources'] = len(
        restricted_package_metadata['resources'])
    return (restricted_package_metadata)


@tk.chained_action
@tk.side_effect_free
def restricted_resource_search(up_func, context, data_dict):
    resource_search_result = up_func(context, data_dict)
    restricted_resource_search_result = {}

    for key, value in resource_search_result.items():
        if key == 'results':
            # restricted_resource_search_result[key] = \
            #     _restricted_resource_list_url(context, value)
            restricted_resource_search_result[key] = \
                _restricted_resource_list_hide_fields(context, value)
        else:
            restricted_resource_search_result[key] = value

    # Remove restricted resources.
    # Note, that private resources are now excluded from search even for admins.
    # An admin should go to package page to find a resource.
    # TODO check this validation after
    # restricted_resource_search_result['results'] = [
    #     x for x in restricted_resource_search_result['results'] if x.get('level', 'public') == 'public']

    restricted_resource_search_result['count'] = len(
        restricted_resource_search_result['results'])
    return restricted_resource_search_result


@tk.chained_action
@tk.side_effect_free
def restricted_package_search(up_func, context, data_dict):
    package_search_result = up_func(context, data_dict)
    package_show = ckan.logic.get_action('package_show')
    restricted_package_search_result = {}

    for key, value in package_search_result.items():
        if key == 'results':
            restricted_package_search_result_list = []
            for package in value:
                restricted_package_search_result_list.append(
                    package_show(context, {'id': package.get('id')}))
            restricted_package_search_result[key] = \
                restricted_package_search_result_list
        else:
            restricted_package_search_result[key] = value

    return restricted_package_search_result


@tk.chained_action
@tk.side_effect_free
def restricted_package_search(up_func, context, data_dict):
    package_search_result = up_func(context, data_dict)
    package_show = ckan.logic.get_action('package_show')
    results = package_search_result.get('results')
    restricted_package_search_result_list = []
    for package in results:
        restricted_package_search_result_list.append(
            package_show(context, {'id': package.get('id')}))

    package_search_result['results'] = restricted_package_search_result_list

    return package_search_result


@tk.side_effect_free
def restricted_check_access(context, data_dict):

    package_id = data_dict.get('package_id', False)
    resource_id = data_dict.get('resource_id', False)

    user_name = restricted_logic.restricted_get_username_from_context(context)

    if not package_id:
        raise ckan.logic.ValidationError('Missing package_id')
    if not resource_id:
        raise ckan.logic.ValidationError('Missing resource_id')

    log.debug("action.restricted_check_access: user_name = " + str(user_name))

    log.debug("checking package " + str(package_id))
    package_dict = ckan.logic.get_action('package_show')(
        dict(context, return_type='dict'), {'id': package_id})
    log.debug("checking resource")
    resource_dict = ckan.logic.get_action('resource_show')(
        dict(context, return_type='dict'), {'id': resource_id})

    return restricted_logic.restricted_check_user_resource_access(user_name, resource_dict, package_dict)


def _restricted_resource_list_hide_fields(context, resource_list):
    restricted_resources_list = []
    for resource in resource_list:
        # copy original resource
        restricted_resource = dict(resource)

        # get the restricted fields
        restricted_dict = restricted_get_restricted_dict(
            restricted_resource)

        # hide fields to unauthorized users
        # TODO this line is was not used then I commented
        # authorized = auth.restricted_resource_show(
        #     context, {'id': resource.get('id'), 'resource': resource}
        # ).get('success', False)

        # hide other fields in restricted to everyone but dataset owner(s)
        if not authz.is_authorized(
                'package_update', context, {'id': resource.get('package_id')}
        ).get('success'):

            user_name = restricted_get_username_from_context(context)

            # hide partially other allowed user_names (keep own)
            allowed_users = []
            for user in restricted_dict.get('allowed_users'):
                if len(user.strip()) > 0:
                    if user_name == user:
                        allowed_users.append(user_name)
                    else:
                        allowed_users.append(user[0:3] + '*****' + user[-2:])

            restricted_resource['level'] = restricted_dict.get(
                "level", 'public')
            restricted_resource['url'] = None
            # restricted_resource['allowed_users'] = ','.join(allowed_users)

        restricted_resources_list += [restricted_resource]
    return restricted_resources_list

# coding: utf8

from __future__ import unicode_literals
from ckan.common import _, g, config
import ckan.lib.base as base
import ckan.lib.captcha as captcha
import ckan.lib.helpers as h
import ckan.lib.mailer as mailer
import ckan.lib.navl.dictization_functions as dictization_functions
import ckan.logic as logic
import ckan.model as model
from ckanext.restricted.model import ResourceAndPackageAccessRequest
import ckan.plugins.toolkit as toolkit
import simplejson as json
from ckanext.restricted.logic import send_request_mail_to_org_admins

from flask import Blueprint, request


from logging import getLogger

log = getLogger(__name__)

DataError = dictization_functions.DataError
unflatten = dictization_functions.unflatten

render = base.render


def get_blueprints():
    # Create Blueprint for plugin
    blueprint = Blueprint('restricted', __name__)

    blueprint.add_url_rule(
        u"/dataset/<package_id>/request_access/<resource_id>",
        u"request_access",
        restricted_request_access_form,
        methods=[u'GET', u'POST']
    )

    return blueprint


def restricted_request_access_form(package_id, resource_id, data=None, errors=None, error_summary=None):
    """Redirects to form."""
    user_id = g.user
    if not user_id:
        toolkit.abort(
            401, _('Access request form is available to logged in users only.'))

    context = {'model': model,
               'session': model.Session,
               'user': user_id,
               'package_id': package_id,
               'resource_id': resource_id,
               'save': 'save' in request.form}

    data = data or {}
    errors = errors or {}
    error_summary = error_summary or {}
    pkg_dict = toolkit.get_action('package_show')(
                context, {'id': package_id})
    user = toolkit.get_action('user_show')(context, {'id': user_id})
    if (context['save']) and not data and not errors:
        return _send_request(context)

    if not data:
        data['package_id'] = package_id
        data['resource_id'] = resource_id

        try:
            data['user_id'] = user_id
            data['user_name'] = user.get('display_name', user_id)
            data['user_email'] = user.get('email', '')

            resource_name = ''

            data['package_name'] = pkg_dict.get('name')
            resources = pkg_dict.get('resources', [])
            for resource in resources:
                if resource['id'] == resource_id:
                    resource_name = resource['name']
                    break
            else:
                toolkit.abort(404, 'Dataset resource not found')
            # get mail
            contact_details = _get_contact_details(pkg_dict)
        except toolkit.ObjectNotFound:
            toolkit.abort(404, _('Dataset not found'))
        except Exception as e:
            log.warning('Exception Request Form: ' + repr(e))
            toolkit.abort(
                404, _(u'Exception retrieving dataset for the form ({})').format(str(e)))
        except Exception:
            toolkit.abort(
                404, _('Unknown exception retrieving dataset for the form'))

        data['resource_name'] = resource_name
        data['maintainer_email'] = contact_details.get('contact_email', '')
        data['maintainer_name'] = contact_details.get('contact_name', '')
    else:
        pkg_dict = data.get('pkg_dict', {})

    extra_vars = {
        'pkg_dict': pkg_dict, 'data': data,
        'errors': errors, 'error_summary': error_summary}
    return render(
        'restricted/restricted_request_access_form.html',
        extra_vars=extra_vars)

def _send_request(context):
    pkg = None
    try:
        data_dict = logic.clean_dict(unflatten(
            logic.tuplize_dict(logic.parse_params(request.form))))

        captcha.check_recaptcha(request)

    except logic.NotAuthorized:
        toolkit.abort(401, _('Not authorized to see this page'))
    except captcha.CaptchaError:
        error_msg = _('Bad Captcha. Please try again.')
        h.flash_error(error_msg)
        return restricted_request_access_form(
            package_id=data_dict.get('package_name'),
            resource_id=data_dict.get('resource'),
            data=data_dict)

    try:
        pkg = toolkit.get_action('package_show')(
            context, {'id': data_dict.get('package_name')})
        data_dict['pkg_dict'] = pkg
    except toolkit.ObjectNotFound:
        toolkit.abort(404, _('Dataset not found'))
    except Exception:
        toolkit.abort(404, _('Exception retrieving dataset to send mail'))

    # Validation
    errors = {}
    error_summary = {}
    user_id = toolkit.c.userobj.id

    if (not data_dict['message'] or not data_dict['message'].strip()):
        msg = _('Missing Value')
        errors['message'] = [msg]
        error_summary['message'] = msg

    if pkg.get('private'):
        errors['package_id'] = ['Dataset not found or private']
        error_summary['package_id'] = 'Dataset not found or private'

    is_there_request_access_already_created_for_the_user = ResourceAndPackageAccessRequest.get_by_resource_user_and_status(
        context['resource_id'], user_id, 'pending')

    if len(is_there_request_access_already_created_for_the_user) > 0:
        errors['resource_id'] = ['Request already created for this resource']
        error_summary['resource_id'] = 'Request already created for this resource'

    if len(errors) > 0:
        return restricted_request_access_form(
            data=data_dict,
            errors=errors,
            error_summary=error_summary,
            package_id=pkg.get('id'),
            resource_id=context['resource_id'])


    ResourceAndPackageAccessRequest.create(
            pkg.get('id'), user_id, pkg.get('organization').get('id'),
            logic.clean_dict(unflatten(
                logic.tuplize_dict(logic.parse_params(request.form)))).get('message'),
            context['resource_id']
        )
    data_dict['org_id'] = pkg.get('organization').get('id')
    success = send_request_mail_to_org_admins(data_dict)

    return render(
        'restricted/restricted_request_access_result.html',
        extra_vars={'data': data_dict, 'pkg_dict': pkg, 'success': success})


def _get_contact_details(pkg_dict):
    contact_email = ""
    contact_name = ""
    # Maintainer as Composite field
    try:
        contact_email = json.loads(
            pkg_dict.get('maintainer', '{}')).get('email', '')
        contact_name = json.loads(
            pkg_dict.get('maintainer', '{}')).get('name', 'Dataset Maintainer')
    except Exception:
        pass
    # Maintainer Directly defined
    if not contact_email:
        contact_email = pkg_dict.get('maintainer_email', '')
        contact_name = pkg_dict.get('maintainer', 'Dataset Maintainer')
    # 1st Author Directly defined
    if not contact_email:
        contact_email = pkg_dict.get('author_email', '')
        contact_name = pkg_dict.get('author', '')
    # First Author from Composite Repeating
    if not contact_email:
        try:
            author = json.loads(pkg_dict.get('author'))[0]
            contact_email = author.get('email', '')
            contact_name = author.get('name', 'Dataset Maintainer')
        except Exception:
            pass
    # CKAN instance Admin
    if not contact_email:
        contact_email = config.get('email_to', 'email_to_undefined')
        contact_name = 'CKAN Admin'
    return {'contact_email': contact_email, 'contact_name': contact_name}

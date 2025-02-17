from logging import getLogger
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ckan.plugins import toolkit
from ckan import model
from ckan.common import _

from ckanext.restricted import model as custom_model
from ckanext.restricted.logic import send_rejection_email_to, restricted_mail_allowed_user
from ckan.common import config
from ckanext.activity.model import activity as core_model_activity

import os
access_requests_blueprint = Blueprint('access_requests', __name__)


log = getLogger(__name__)


@access_requests_blueprint.route('/access_requests')
def access_requests_dashboard():
    """
    Dashboard to display and manage access requests for admins.
    """
    user_id = toolkit.c.userobj.id if toolkit.c.userobj else None

    if not user_id:
        flash(_("You must be logged in to view access requests."),
              category='alert-danger')
        return redirect(url_for('user.login'))

    is_sysadmin = toolkit.c.userobj.sysadmin
    org_ids = []

    if not is_sysadmin:
        user_obj = model.User.get(toolkit.c.user)
        org_memberships = model.Session.query(model.Group).\
            outerjoin(model.Member, model.Member.group_id == model.Group.id). \
            filter(model.Member.table_name == 'user').\
            filter(model.Member.table_id == user_obj.id).\
            filter(model.Group.type == 'organization').\
            filter(model.Member.state == 'active').\
            filter(model.Member.capacity == 'admin').\
            all()
        for membership in org_memberships:
            org_ids.append(membership.id)

    if not is_sysadmin and not org_ids:
        flash(_("You do not have permission to view access requests."),
              category='alert-danger')

        return redirect(url_for('home.index'))

    requests = []
    if is_sysadmin:
        requests = custom_model.ResourceAndPackageAccessRequest.get_all()
    else:
        requests.extend(custom_model.ResourceAndPackageAccessRequest.get_by_orgs(
            org_ids))

    return render_template('access_requests/access_requests_dashboard.html',
                           requests=requests,
                           is_sysadmin=is_sysadmin,
                           org_ids=org_ids)


@access_requests_blueprint.route('/access_requests/update_status', methods=['POST'])
def update_request_status():
    """
    Endpoint to handle approving, revoking or rejecting access requests.
    """

    if toolkit.current_user.is_anonymous or not is_admin_of_any_org():
        toolkit.abort(403)

    request_id = request.form.get('request_id')
    action = request.form.get('action')
    rejection_message = request.form.get('rejection_message')

    if not request_id or not action:
        flash(_("Invalid request."), category='alert-danger')
        return redirect(url_for('access_requests.access_requests_dashboard'))

    request_obj = custom_model.ResourceAndPackageAccessRequest.get(request_id)
    if not request_obj:
        flash(_("Request not found."), category='alert-danger')
        return redirect(url_for('access_requests.access_requests_dashboard'))

    approved_or_rejected_by_user_id = toolkit.c.userobj.id

    if action == 'approve':
        new_status = 'approved'
        rejection_message = None
    elif action == 'reject':
        new_status = 'rejected'
    elif action == 'revoke':
        new_status = 'revoked'
    else:
        flash(_("Invalid action."), category='alert-danger')
        return redirect(url_for('access_requests.access_requests_dashboard'))

    custom_model.ResourceAndPackageAccessRequest.update_status(
        request_id, new_status, rejection_message, approved_or_rejected_by_user_id
    )

    res = toolkit.get_action('resource_show')({'ignore_auth': True}, {
        'id': request_obj.resource_id})
    pkg = toolkit.get_action('package_show')({'ignore_auth': True}, {
        'id': res.get('package_id')})
    user = toolkit.get_action('user_show')(
        {"user": os.environ.get('CKAN_SYSADMIN_NAME')}, {'id': request_obj.user_id})

    org_id = pkg.get('organization').get('id')
    # f"Resource {res.get('name')} {new_status} by {user.get('name')}"
    # _create_resource_activity(model.User.get(toolkit.c.user), res, pkg, f'resource-{new_status}', "Resource '%s' approved by %s")

    resource_link = f"{os.environ.get('CKAN_FRONTEND_SITE_URL')}/{pkg.get('organization').get('name')}/{pkg.get('name')}"
    site_title = os.environ.get('CKAN_FRONTEND_SITE_TITLE')
    site_url = os.environ.get('CKAN_FRONTEND_SITE_URL')

    email_notification_dict = {
        'user_id': request_obj.user_id,
        'site_url': site_url,
        'site_title': site_title,
        'resource_link': resource_link,
        'user_name': user.get('full_name') or user.get('display_name') or user.get('name'),
        'user_email': user.get('email'),
        'resource_edit_link': config.get('ckan.site_url') + '/access_requests',
        'resource_name': res.get('name') or res.get('id'),
        'resource_id': res.get('id'),
        'package_id': pkg.get('id'),
        'package_name': pkg.get('name'),
        'org_id': org_id,
        'package_type': pkg.get('type'),
    }

    if action == 'approve':
        toolkit.get_action('resource_patch')({'ignore_auth': True}, {'id': res.get(
            'id'), 'allowed_users': [user.get('name'), *res.get('allowed_users')]})

        restricted_mail_allowed_user(
            user.get('id'), res, org_id, resource_link, site_title, site_url)
    else:
        if action == 'revoke':
            toolkit.get_action('resource_patch')({'ignore_auth': True}, {'id': res.get('id'), 'allowed_users': [
                allowed_user for allowed_user in res.get('allowed_users') if allowed_user != user.get('name')]})

        if rejection_message:
            rejection_message = f'''Reason:
                {rejection_message}
            '''
        send_rejection_email_to(email_notification_dict,
                                rejection_message, new_status)
    flash(
        _(f"Request {request_id} {new_status} successfully."), category='alert-success')
    return redirect(url_for('access_requests.access_requests_dashboard'))


def _create_resource_activity(user, resource, package, activity_type, message_template, extra_data=None):
    """
    Helper function to create a resource activity.
    """
    if not user:
        raise Exception("User not found.")

    activity_dict = {
        'user_id': user.get('id'),
        'object_id': resource.get('id'),
        'activity_type': activity_type,
        'data': {
            'resource_name': resource.get('name'),
            'dataset_name': package.get('name'),
            'message': message_template % (resource.get('name'), user.get('name')),
        }
    }
    if extra_data:
        activity_dict['data'].update(extra_data)
    _create_activity_record(activity_dict)


def _create_activity_record(activity_dict):
    """
    Actually creates and saves the activity record to the database.
    Used by both dataset and resource activity creators.
    """
    activity = core_model_activity.Activity(**activity_dict)
    model.Session.add(activity)
    model.Session.commit()


def get_blueprints():
    return [access_requests_blueprint]


def is_admin_of_any_org():
    if toolkit.current_user.is_anonymous:
        return False

    if toolkit.c.userobj.sysadmin:
        return True

    user_obj = model.User.get(toolkit.c.user)
    if not user_obj:
        return False

    org_memberships = model.Session.query(model.Member).\
        outerjoin(model.Group, model.Member.group_id == model.Group.id). \
        filter(model.Member.table_name == 'user').\
        filter(model.Member.table_id == user_obj.id).\
        filter(model.Group.type == 'organization').\
        filter(model.Member.state == 'active').\
        filter(model.Member.capacity == 'admin').\
        all()

    return len(org_memberships) > 0

# coding: utf8

from __future__ import unicode_literals
from ckan.common import _
from ckan.common import request
import ckan.lib.base as base
import ckan.lib.captcha as captcha
import ckan.lib.helpers as h
import ckan.lib.mailer as mailer
import ckan.logic as logic
import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.logic.action.get import member_list as core_member_list

try:
    # CKAN 2.7 and later
    from ckan.common import config
except ImportError:
    # CKAN 2.6 and earlier
    from pylons import config

import simplejson as json

from logging import getLogger
from flask.views import MethodView

log = getLogger(__name__)


render = base.render

class RestrictedView(MethodView):
    def _prepare(self, id):
        try:
            context = {
                u'model': model,
                u'session': model.Session,
                u'user': base.g.user,
                u'auth_user_obj': base.g.userobj
            }
            logic.check_access('site_read', context)
        except logic.NotAuthorized:
                base.abort(401, _('Not authorized to see this page'))

    def get(self, package_id=None, resource_id=None, data=None, errors=None, error_summary=None):
        """Redirects to form."""
        user_id = toolkit.c.user
        if not user_id:
            toolkit.abort(401, _('Access request form is available to logged in users only.'))

        context = {'model': model,
                   'session': model.Session,
                   'user': user_id
                   }
        data = data or {}
        errors = errors or {}
        error_summary = error_summary or {}

        if not data:
            data['package_id'] = package_id
            data['resource_id'] = resource_id

            try:
                user = toolkit.get_action('user_show')(context, {'id': user_id})
                data['user_id'] = user_id
                data['user_name'] = user.get('display_name', user_id)
                data['user_email'] = user.get('email', '')

                resource_name = ''

                pkg = toolkit.get_action('package_show')(context, {'id': package_id})
                data['package_name'] = pkg.get('name')
                resources = pkg.get('resources', [])
                for resource in resources:
                    if resource['id'] == resource_id:
                        resource_name = resource['name']
                        break
                else:
                    toolkit.abort(404, 'Dataset resource not found')
                # get mail
                contact_details = self._get_contact_details(pkg)
            except toolkit.ObjectNotFound:
                toolkit.abort(404, _('Dataset not found'))
            except Exception as e:
                log.warn('Exception Request Form: ' + repr(e))
                toolkit.abort(404, _(u'Exception retrieving dataset for the form ({})').format(str(e)))
            except Exception:
                toolkit.abort(404, _('Unknown exception retrieving dataset for the form'))

            data['resource_name'] = resource_name
            data['maintainer_email'] = contact_details.get('contact_email', '')
            data['maintainer_name'] = contact_details.get('contact_name', '')
        else:
            pkg = data.get('pkg_dict', {})

        extra_vars = {
            'pkg_dict': pkg, 'data': data,
            'errors': errors, 'error_summary': error_summary}
        return render(
            'restricted/restricted_request_access_form.html',
            extra_vars=extra_vars)

    def post(self, package_id = None, resource_id = None):
        data_dict = request.form

        user_id = toolkit.c.user
        if not user_id:
            toolkit.abort(401, _('Access request form is available to logged in users only.'))

        context = {
            'model': model,
            'session': model.Session,
            'user': user_id,
            'ignore_auth': True
            }   

        return self._send_request(context, data_dict.copy())


    def _send_request_mail(self, data):
        success = False
        try:

            resource_link = toolkit.url_for(
                'dataset_resource.read',
                id=data.get('package_name'),
                resource_id=data.get('resource_id'))

            resource_edit_link = toolkit.url_for(
                'dataset_resource.edit',
                id=data.get('package_name'),
                resource_id=data.get('resource_id'))

            extra_vars = {
                'site_title': config.get('ckan.site_title'),
                'site_url': config.get('ckan.site_url'),
                'maintainer_name': data.get('maintainer_name', 'Maintainer'),
                'user_id': data.get('user_id', 'the user id'),
                'user_name': data.get('user_name', ''),
                'user_email': data.get('user_email', ''),
                'resource_name': data.get('resource_name', ''),
                'resource_link': config.get('ckan.site_url') + resource_link,
                'resource_edit_link': config.get('ckan.site_url') + resource_edit_link,
                'package_name': data.get('resource_name', ''),
                'message': data.get('message', ''),
            }

            context = {
                'model': model,
                'session': model.Session,
                'ignore_auth': True
            }   

            body = base.render('restricted/emails/restricted_access_request.txt', extra_vars)

            subject = \
                _('Access Request to resource {0} ({1}) from {2}').format(
                    data.get('resource_name', ''),
                    data.get('package_name', ''),
                    data.get('user_name', ''))

            email_dict = {}

            members = core_member_list(
                context=context,
                data_dict={'id': data.get('owner_org')}
            )

            org_admin = [i[0] for i in members if i[2] == 'Admin']

            sysadmins = model.Session.query(model.User.id).filter(
                    model.User.state != model.State.DELETED,
                    model.User.sysadmin == True
                    ).all()

            # Merged org admin and sysadmin so that sysadmin also gets the email. 
            org_admin_user_ids = list(set( org_admin + [admin[0] for admin in sysadmins]))

            for admin_id in org_admin_user_ids:
                user = model.User.get(admin_id)
                if 'default' != user.name and user.email: 
                    email_dict.update({
                        user.email: user.display_name
                    })

            headers = {
                'reply-to': data.get('user_email')
                }

            # CC doesn't work and mailer cannot send to multiple addresses
            for email, name in email_dict.items():
                mailer.mail_recipient(
                    recipient_name = name, 
                    recipient_email = email, 
                    subject = subject, 
                    body = body, 
                    headers = headers
                )

            # Special copy for the user (no links)
            email = data.get('user_email')
            name = data.get('user_name', 'User')

            extra_vars['resource_link'] = '[...]'
            extra_vars['resource_edit_link'] = '[...]'
            body = base.render(
                'restricted/emails/restricted_access_request.txt', extra_vars)

            body_user = _(
                'Please find below a copy of the access '
                'request mail sent. \n\n >> {}'
            ).format(body.replace("\n", "\n >> "))

            mailer.mail_recipient(
                recipient_name = name, 
                recipient_email = email, 
                subject= 'Fwd: ' + subject, 
                body = body_user, 
                headers = headers
            )
            success = True

        except mailer.MailerException as mailer_exception:
            log.error('Can not access request mail after registration.')
            log.error(mailer_exception)

        return success

    def _send_request(self, context, data_dict):

        try:
            captcha.check_recaptcha(request)

        except logic.NotAuthorized:
            toolkit.abort(401, _('Not authorized to see this page'))
        except captcha.CaptchaError:
            error_msg = _('Bad Captcha. Please try again.')
            h.flash_error(error_msg)
            return self.get(
                package_id=data_dict.get('package_name'),
                resource_id=data_dict.get('resource'),
                data=data_dict
            )

        try:
            pkg = toolkit.get_action('package_show')(
                context, {'id': data_dict.get('package_name')})
            data_dict['pkg_dict'] = pkg
        except toolkit.ObjectNotFound:
            toolkit.abort(404, _('Dataset not found'))
        except Exception as e:
            toolkit.abort(404, _('Exception retrieving dataset to send mail'))

        # Validation
        errors = {}
        error_summary = {}

        if (data_dict['message'] == ''):
            msg = _('Missing Value')
            errors['message'] = [msg]
            error_summary['message'] = msg

        if len(errors) > 0:
            return self.get(
                package_id=data_dict.get('package_name'),
                resource_id=data_dict.get('resource'),
                data=data_dict,
                errors=errors,
                error_summary=error_summary,
            )

        success = self._send_request_mail(data_dict)

        return render(
            'restricted/restricted_request_access_result.html',
            extra_vars={'data': data_dict, 'pkg_dict': pkg, 'success': success})

    def _get_contact_details(self, pkg_dict):
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

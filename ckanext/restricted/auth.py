# coding: utf8

from __future__ import unicode_literals
import ckan.authz as authz
import ckan.logic.auth as logic_auth
import ckan.plugins.toolkit as toolkit
from ckanext.restricted import logic

from logging import getLogger
log = getLogger(__name__)


@toolkit.auth_allow_anonymous_access
def restricted_resource_show(context, data_dict=None):

    # Ensure user who can edit the package can see the resource
    resource = data_dict.get('resource', context.get('resource', {}))
    if not resource:
        resource = logic_auth.get_resource_object(context, data_dict)

    # This auth function is called once per resource whenever a dataset page
    # is rendered (CKAN calls ``resource_view_list`` to work out ``has_views``
    # for every resource), so it must be cheap. Avoid converting the resource
    # (and, worse, the package) to full dicts up-front: ``Package.as_dict()``
    # dictizes the *entire* package — every resource plus markdown rendering —
    # which is extremely slow for packages with many resources. Instead, read
    # only the restricted metadata we actually need.
    if isinstance(resource, dict):
        package_id = resource.get('package_id')
        restricted_dict = logic.restricted_get_restricted_dict(resource)
    else:
        # A model.Resource (or similar) object.
        package_id = getattr(resource, 'package_id', None)
        extras = getattr(resource, 'extras', None) or {}
        restricted_dict = logic.restricted_get_restricted_dict(
            {'extras': extras})

    # Public resources are visible to everyone, so short-circuit before any
    # further authorization or package look-up.
    level = restricted_dict.get('level', 'public')
    if not level or level == 'public':
        return ({'success': True})

    # Editors of the package can always see restricted resources.
    if authz.is_authorized(
            'package_update', context,
            {'id': package_id}).get('success'):
        return ({'success': True})

    user_name = logic.restricted_get_username_from_context(context)

    # Only restricted resources reach this point, so dictizing this single
    # resource is acceptable. Avoid ``Package.as_dict()`` entirely by reading
    # only the owner_org that ``restricted_check_user_resource_access`` needs.
    if not isinstance(resource, dict):
        resource = resource.as_dict()

    package = data_dict.get('package', {})
    if not package:
        pkg = context['model'].Package.get(package_id)
        package = {'owner_org': pkg.owner_org} if pkg else {}

    return (logic.restricted_check_user_resource_access(
        user_name, resource, package))

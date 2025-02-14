# coding: utf8

from __future__ import unicode_literals
from ckan.lib.plugins import DefaultTranslation
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckanext.restricted import action
from ckanext.restricted.blueprints.access_request_dashboard import get_blueprints
from ckanext.restricted.blueprints.request_access import get_blueprints as get_restricted_access_blueprint
from ckanext.restricted import auth
import logic as logic
from ckanext.restricted import helpers
from .model import ResourceAndPackageAccessRequest
from .validators import member_string_convert

from logging import getLogger
log = getLogger(__name__)


class RestrictedPlugin(plugins.SingletonPlugin, DefaultTranslation):
    plugins.implements(plugins.ITranslation)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IValidators)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.IResourceController, inherit=True)

    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'restricted')

    # IConfigurable
    def configure(self, config_):
        from ckan.model import meta
        if not ResourceAndPackageAccessRequest.__table__.exists(meta.engine):
            ResourceAndPackageAccessRequest.__table__.create(meta.engine)
    
      # IValidators
    def get_validators(self):
        return {'member_string_convert': member_string_convert}
    
    # IActions
    def get_actions(self):
        return {'user_create': action.restricted_user_create_and_notify,
                'resource_view_list': action.restricted_resource_view_list,
                'request_access_to_resource': action.request_access_to_resource,
                'package_show': action.restricted_package_show,
                'resource_search': action.restricted_resource_search,
                'package_search': action.restricted_package_search,
                'restricted_check_access': action.restricted_check_access}

    # ITemplateHelpers
    def get_helpers(self):
        return {'restricted_get_user_id': helpers.restricted_get_user_id}
    
    # IBlueprint
    def get_blueprint(self):
        return [*get_blueprints(), get_restricted_access_blueprint()]

    # IAuthFunctions
    def get_auth_functions(self):
        return {'resource_show': auth.restricted_resource_show,
                'resource_view_show': auth.restricted_resource_show}

    # IResourceController
    def before_update(self, context, current, resource):
        context['__restricted_previous_value'] = {'level': current.get(
            'level', 'public'), 'allowed_users': current.get('allowed_users', [])}

    def after_update(self, context, resource):
        previous_value = context.get('__restricted_previous_value')
        # logic.restricted_notify_allowed_users(previous_value, resource)

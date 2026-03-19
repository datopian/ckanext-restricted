# coding: utf8

from __future__ import unicode_literals
from ckan.lib.plugins import DefaultTranslation
import ckan.authz as authz
import ckan.logic
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckanext.restricted import action
from ckanext.restricted import auth
from ckanext.restricted import helpers
from ckanext.restricted import logic
import json

from logging import getLogger

log = getLogger(__name__)


_get_or_bust = ckan.logic.get_or_bust


class RestrictedPlugin(plugins.SingletonPlugin, DefaultTranslation):
    plugins.implements(plugins.ITranslation)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.IResourceController, inherit=True)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IBlueprint)

    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_public_directory(config_, "public")
        toolkit.add_resource("fanstatic", "restricted")

    # IActions
    def get_actions(self):
        return {
            "user_create": action.restricted_user_create_and_notify,
            "resource_view_list": action.restricted_resource_view_list,
            "resource_search": action.restricted_resource_search,
            "restricted_check_access": action.restricted_check_access,
        }

    # ITemplateHelpers
    def get_helpers(self):
        return {"restricted_get_user_id": helpers.restricted_get_user_id}

    # IAuthFunctions
    def get_auth_functions(self):
        return {
            "resource_show": auth.restricted_resource_show,
            "resource_view_show": auth.restricted_resource_show,
        }

    # IBlueprint
    def get_blueprint(self):
        from ckanext.restricted.views import get_blueprints

        return get_blueprints()

    # IPackageController
    def _filter_restricted_resources(self, package, user_name, context):
        """Filter non-public resources and mask allowed_users for a single package."""
        if "resources" not in package:
            return

        # Editor shortcut — once per package, not per resource
        if authz.is_authorized(
            "package_update", context, package
        ).get("success", False):
            return

        filtered = []
        for resource in package.get("resources", []):
            restricted_dict = logic.restricted_get_restricted_dict(resource)
            level = restricted_dict.get("level", "public")

            if not level or level == "public":
                # Mask allowed_users only if there are any to mask
                allowed_users = [
                    u for u in restricted_dict.get("allowed_users", [])
                    if u.strip()
                ]
                if allowed_users:
                    masked = [
                        user_name if u == user_name
                        else u[:3] + "*****" + u[-2:]
                        for u in allowed_users
                    ]
                    new_restricted = json.dumps({
                        "level": level,
                        "allowed_users": ",".join(masked),
                    })
                    if resource.get("extras", {}).get("restricted"):
                        resource["extras"]["restricted"] = new_restricted
                    if resource.get("restricted"):
                        resource["restricted"] = new_restricted

                filtered.append(resource)

        package["resources"] = filtered
        package["num_resources"] = len(filtered)

    def _get_user_context(self):
        """Build user_name and context from current_user."""
        user_name = "" if toolkit.current_user.is_anonymous else toolkit.current_user.name
        context = {
            "model": ckan.logic.model,
            "user": user_name,
            "auth_user_obj": toolkit.current_user,
        }
        return user_name, context

    def after_dataset_search(self, search_results, search_params):
        """Filter restricted resources in-memory instead of N+1 package_show calls."""
        user_name, context = self._get_user_context()

        for package in search_results.get("results", []):
            self._filter_restricted_resources(package, user_name, context)

        return search_results

    def after_dataset_show(self, context, pkg_dict):
        """Filter restricted resources on detail page — same logic as search."""
        user_name = context.get("user", "")
        if not user_name:
            user_name = "" if toolkit.current_user.is_anonymous else toolkit.current_user.name
        # Ensure context has required keys for authz
        if "model" not in context:
            context["model"] = ckan.logic.model
        if "auth_user_obj" not in context:
            context["auth_user_obj"] = toolkit.current_user

        self._filter_restricted_resources(pkg_dict, user_name, context)
        return pkg_dict

    # IResourceController
    def before_update(self, context, current, resource):
        context["__restricted_previous_value"] = current.get("restricted")

    def after_update(self, context, resource):
        previous_value = context.get("__restricted_previous_value")
        # logic.restricted_notify_allowed_users(previous_value, resource)

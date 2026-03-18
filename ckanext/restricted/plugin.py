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
            "package_show": action.restricted_package_show,
            "resource_search": action.restricted_resource_search,
            "package_search": action.restricted_package_search,
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
    def after_dataset_search(self, search_results, search_params):
        """Filter restricted resources in-memory instead of N+1 package_show calls."""
        # Prefer caller-supplied context (from action override via thread-local),
        # fall back to request context for direct IPackageController calls
        from ckanext.restricted.action import _search_context
        caller_context = getattr(_search_context, "context", None)
        if caller_context:
            context = caller_context
        else:
            try:
                context = {
                    "model": ckan.logic.model,
                    "user": toolkit.g.user,
                    "auth_user_obj": toolkit.g.userobj,
                }
            except (TypeError, AttributeError, RuntimeError):
                # Outside request context (CLI, tests, background jobs)
                # Skip filtering — safe default
                return search_results

        user_name = logic.restricted_get_username_from_context(context)

        for package in search_results.get("results", []):
            # Skip packages without resources (sparse results from custom fl param)
            if "resources" not in package:
                continue

            # Editor shortcut — once per package, not per resource
            if authz.is_authorized(
                "package_update", context, package
            ).get("success", False):
                continue

            # Filter resources in-memory (no DB calls)
            filtered = []
            for resource in package.get("resources", []):
                restricted_dict = logic.restricted_get_restricted_dict(resource)
                level = restricted_dict.get("level", "public")

                if not level or level == "public":
                    # Mask allowed_users for non-editors
                    allowed_users = restricted_dict.get("allowed_users", [])
                    masked = []
                    for u in allowed_users:
                        if u.strip():
                            if u == user_name:
                                masked.append(user_name)
                            else:
                                masked.append(u[:3] + "*****" + u[-2:])

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

        return search_results

    # IResourceController
    def before_update(self, context, current, resource):
        context["__restricted_previous_value"] = current.get("restricted")

    def after_update(self, context, resource):
        previous_value = context.get("__restricted_previous_value")
        # logic.restricted_notify_allowed_users(previous_value, resource)

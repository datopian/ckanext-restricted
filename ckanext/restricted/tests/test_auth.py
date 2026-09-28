"""Tests for the restricted_resource_show auth function."""
from unittest import mock

from ckanext.restricted import auth


def test_public_resource_short_circuits():
    """Public resources return True without loading the package or doing
    any package_update authorization round-trip."""
    resource = mock.MagicMock()
    resource.package_id = 'pkg-1'
    resource.extras = {'restricted': '{"level": "public"}'}

    model = mock.MagicMock()
    context = {'model': model}

    with mock.patch.object(auth.authz, 'is_authorized') as is_authorized:
        result = auth.restricted_resource_show(
            context, {'resource': resource})

    assert result['success'] is True
    is_authorized.assert_not_called()
    model.Package.get.assert_not_called()


def test_public_resource_dict_short_circuits():
    """A dictized public resource also short-circuits."""
    context = {'model': mock.MagicMock()}
    resource = {
        'id': 'res-1',
        'package_id': 'pkg-1',
        'restricted': '{"level": "public"}',
    }

    with mock.patch.object(auth.authz, 'is_authorized') as is_authorized:
        result = auth.restricted_resource_show(
            context, {'resource': resource})

    assert result['success'] is True
    is_authorized.assert_not_called()


def test_restricted_resource_still_checked():
    """Restricted resources still fall through to the full access check."""
    resource = mock.MagicMock()
    resource.package_id = 'pkg-1'
    resource.extras = {'restricted': '{"level": "registered"}'}
    resource.as_dict.return_value = {
        'id': 'res-1',
        'package_id': 'pkg-1',
        'restricted': '{"level": "registered"}',
    }

    pkg = mock.MagicMock()
    pkg.owner_org = 'org-1'
    model = mock.MagicMock()
    model.Package.get.return_value = pkg
    context = {'model': model}

    with mock.patch.object(
            auth.authz, 'is_authorized',
            return_value={'success': False}), \
            mock.patch.object(
                auth.logic,
                'restricted_get_username_from_context',
                return_value=''):
        result = auth.restricted_resource_show(
            context, {'resource': resource})

    # Anonymous users cannot see "registered" resources.
    assert result['success'] is False
    model.Package.get.assert_called_once_with('pkg-1')

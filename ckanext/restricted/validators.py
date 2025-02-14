# encoding: utf-8
from __future__ import annotations

import logging
import ckan.plugins.toolkit as tk

import re
from typing import Any

from ckanext.scheming.validation import scheming_validator
import ckan.lib.navl.dictization_functions as df
from ckan.model import (MAX_TAG_LENGTH, MIN_TAG_LENGTH)

from ckan.common import _
from ckan.types import (
    FlattenDataDict, FlattenKey, Context, FlattenErrorDict)

Invalid = df.Invalid
StopOnError = df.StopOnError
Missing = df.Missing
missing = df.missing

Invalid = tk.Invalid
_ = tk._

log = logging.getLogger(__name__)

@scheming_validator
def member_string_convert(arg1, arg2) -> Any:
    def validator(key: FlattenKey, data: FlattenDataDict,
                       errors: FlattenErrorDict, context: Context):
        '''Takes a list of members that is a comma-separated string (in data[key])
        and parses members names. They are also validated.'''
        if isinstance(data[key], str):
            members = [member.strip() \
                    for member in data[key].split(',') \
                    if member.strip()]
        else:
            members = data[key]

        for member in members:
            member_length_validator(member)
            member_name_validator(member)

        data[key] = members

    return validator

def member_length_validator(value: Any) -> Any:
    """Ensures that tag length is in the acceptable range.
    """
    if len(value) < MIN_TAG_LENGTH:
        raise Invalid(
            _('Tag "%s" length is less than minimum %s') % (value, MIN_TAG_LENGTH)
        )
    if len(value) > MAX_TAG_LENGTH:
        raise Invalid(
            _('Tag "%s" length is more than maximum %i') % (value, MAX_TAG_LENGTH)
        )
    return value

def member_name_validator(value: Any) -> Any:
    """Ensures that tag does not contain wrong characters
    """
    tagname_match = re.compile(r'[\w \-.]*$', re.UNICODE)
    if not tagname_match.match(value):
        raise Invalid(_('Tag "%s" can only contain alphanumeric '
                        'characters, spaces (" "), hyphens ("-"), '
                        'underscores ("_") or dots (".")') % (value))
    return value

# coding: utf8


from ckan.common import g


def restricted_get_user_id():
    return str(g.user) if g.user else ""

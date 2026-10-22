from django.contrib.admin.apps import AdminConfig


class RouteFuelAdminConfig(AdminConfig):
    default_site = "apps.core.admin_site.RouteFuelAdminSite"

# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

from frappe.model.document import Document


class AttendanceIntegrationSettings(Document):
    def on_update(self):
        if not self.has_value_changed("proxy_enabled") and not self.has_value_changed("proxy_port"):
            return

        from biometric_integration.proxy.detector import check_proxy_compatibility
        compat = check_proxy_compatibility()
        if not compat.get("compatible"):
            if self.proxy_enabled:
                import frappe
                frappe.throw(
                    "This server does not support UI-based proxy configuration. "
                    "Use the Generated Nginx Config section to set it up manually."
                )
            return

        from biometric_integration.proxy.configurator import (
            enable_listener_logic,
            disable_listener_logic,
        )
        import frappe as _frappe
        site = _frappe.local.site
        if self.proxy_enabled:
            ok, msg = enable_listener_logic(site, int(self.proxy_port or 8998))
            if not ok:
                _frappe.throw(msg)
        else:
            disable_listener_logic(site)

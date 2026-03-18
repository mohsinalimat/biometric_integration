// Copyright (c) 2026, Khaled Bin Amir
// SPDX-License-Identifier: MIT

// Employee list view action — "Sync to Biometric Devices"
// Only shown when sync_employee_to_devices_on_create is enabled in settings.

frappe.listview_settings['Employee'] = frappe.listview_settings['Employee'] || {};

const _existing_onload = frappe.listview_settings['Employee'].onload;

frappe.listview_settings['Employee'].onload = function (listview) {
	if (_existing_onload) _existing_onload.call(this, listview);

	frappe.call({
		method: 'biometric_integration.api.get_device_form_settings',
		callback(r) {
			if (!r.message || !r.message.sync_employee_to_devices_on_create) return;

			listview.page.add_action_item(__('Sync to Biometric Devices'), () => {
				const selected = listview.get_checked_items();
				if (!selected.length) {
					frappe.msgprint(__('Please select at least one employee.'));
					return;
				}
				frappe.confirm(
					__('Sync {0} employee(s) to biometric devices?', [selected.length]),
					() => {
						frappe.call({
							method: 'biometric_integration.api.bulk_sync_employees',
							args: { employees: selected.map(e => e.name) },
							freeze: true,
							freeze_message: __('Syncing employees…'),
							callback(r) {
								if (r.message) {
									frappe.show_alert({
										message: __('Queued sync for {0} of {1} employees', [r.message.queued, r.message.total]),
										indicator: r.message.queued > 0 ? 'green' : 'orange',
									}, 5);
								}
							},
						});
					}
				);
			});
		},
	});
};

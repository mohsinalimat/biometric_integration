// Copyright (c) 2026, Khaled Bin Amir
// SPDX-License-Identifier: MIT

frappe.ui.form.on('Employee', {
	refresh(frm) {
		_update_device_user_link(frm);
	},

	attendance_device_id(frm) {
		_update_device_user_link(frm);
	},
});

function _update_device_user_link(frm) {
	const device_id = frm.doc.attendance_device_id;
	const field = frm.get_field('attendance_device_id');
	if (!field) return;

	// Remove any existing button
	field.$wrapper.find('.btn-open-device-user').remove();

	if (!device_id || frm.is_new()) return;

	frappe.db.get_value('Attendance Device User', { user_id: device_id }, 'name')
		.then(r => {
			if (!r || !r.message || !r.message.name) return;
			const name = r.message.name;
			const btn = $(`<a class="btn-open-device-user text-xs text-muted ml-2" style="font-size:0.75rem;cursor:pointer;"
				title="${__('View Attendance Device User')}">${__('View Device User')}</a>`);
			btn.on('click', () => frappe.set_route('Form', 'Attendance Device User', name));
			field.$wrapper.find('[data-fieldname="attendance_device_id"] .control-label').append(btn);
		});
}

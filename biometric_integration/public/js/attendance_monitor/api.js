// Thin transport adapter — the only file that knows about the desk (`frappe.call`).
// A future mobile shell replaces this module with frappe-ui resources / fetch,
// keeping App.vue and PunchDialog.vue unchanged.

const M = "biometric_integration.attendance_monitor";

function call(method, args) {
	return frappe.call({ method: `${M}.${method}`, args }).then((r) => r.message);
}

export function fetchMonitor({ from_date, to_date, company, include_absent = 0 }) {
	return call("get_attendance_monitor", { from_date, to_date, company, include_absent });
}

export function addCheckin({ employee, time }) {
	return call("add_checkin", { employee, time });
}

export function updateCheckin({ name, time }) {
	return call("update_checkin", { name, time });
}

export function deleteCheckin({ name }) {
	return call("delete_checkin", { name });
}

export function fetchConfig() {
	// { can_correct, companies } — companies respects User Permission; can_correct
	// reflects the site's "Allow Check-in Corrections" toggle.
	return call("get_monitor_config", {});
}

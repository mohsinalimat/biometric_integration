frappe.pages["attendance-monitor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Attendance Monitor"),
		single_column: true,
	});
	// The Vue app lives in the bundle so the same component can be reused by a
	// mobile shell later — this file only mounts it into the desk page.
	frappe.require("attendance_monitor.bundle.js").then(() => {
		frappe.attendance_monitor = new biometric_integration.AttendanceMonitor({
			wrapper: page.main.get(0),
			page,
		});
	});
};

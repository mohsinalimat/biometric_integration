import { createApp } from "vue";
import App from "./App.vue";

// Exposed as a class so the desk page (attendance_monitor.js) — and later any
// other shell — can mount the same Vue app into an arbitrary element.
class AttendanceMonitor {
	constructor({ wrapper }) {
		this.$app = createApp(App);
		SetVueGlobals(this.$app);
		this.$app.mount(wrapper);
	}
}

frappe.provide("biometric_integration");
biometric_integration.AttendanceMonitor = AttendanceMonitor;

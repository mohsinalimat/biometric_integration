<template>
	<svg
		class="am-ico"
		:width="size"
		:height="size"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		v-html="paths[name] || ''"
	></svg>
</template>

<script>
// Minimal feather-style line icons - monochrome, inherit currentColor.
const PATHS = {
	check: '<path d="M20 6 9 17l-5-5"/>',
	alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
	dot: '<circle cx="12" cy="12" r="4.5" fill="currentColor" stroke="none"/>',
	minus: '<path d="M5 12h14"/>',
	umbrella: '<path d="M23 12a11.05 11.05 0 0 0-22 0z"/><path d="M12 12v7a3 3 0 0 1-6 0"/>',
	calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
	coffee: '<path d="M17 8h1a3 3 0 0 1 0 6h-1"/><path d="M3 8h14v7a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z"/><path d="M6 1v3M10 1v3M14 1v3"/>',
	plus: '<path d="M12 5v14M5 12h14"/>',
};
export default {
	name: "Icon",
	props: { name: { type: String, required: true }, size: { type: Number, default: 14 } },
	data() {
		return { paths: PATHS };
	},
};
</script>

<style scoped>
.am-ico {
	vertical-align: -2px;
	flex: none;
}
</style>

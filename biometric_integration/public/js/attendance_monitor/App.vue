<template>
	<div class="am-root">
		<!-- Toolbar -->
		<div class="am-toolbar">
			<div class="am-dategroup">
				<button class="am-nav" :title="__('Previous day')" @click="shiftDay(-1)">&lsaquo;</button>
				<button class="am-datebtn" @click="openPicker">
					{{ displayDate }}
					<input
						ref="picker"
						v-model="date"
						type="date"
						class="am-date-native"
						@change="load"
					/>
				</button>
				<button class="am-nav" :title="__('Next day')" @click="shiftDay(1)">&rsaquo;</button>
				<button class="am-today" :disabled="isToday" @click="goToday">{{ __("Today") }}</button>
			</div>
			<input
				v-model.trim="search"
				type="search"
				class="am-search"
				:placeholder="__('Search employees…')"
			/>
			<select v-if="departments.length > 1" v-model="department" class="am-select">
				<option value="">{{ __("All departments") }}</option>
				<option v-for="d in departments" :key="d" :value="d">{{ d }}</option>
			</select>
			<select v-if="companies.length > 1" v-model="company" class="am-select" @change="onCompanyChange">
				<option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
			</select>
		</div>

		<!-- Summary chips -->
		<div class="am-chips">
			<span class="am-chip">{{ scannedCount }} {{ __("scanned") }}</span>
			<span class="am-chip am-chip-flag" v-if="flaggedCount">⚠ {{ flaggedCount }} {{ __("flagged") }}</span>
			<span class="am-chip am-chip-now" v-if="isToday">● {{ onSiteCount }} {{ __("on site now") }}</span>
			<span class="am-chip am-chip-absent" v-if="absentCount">◌ {{ absentCount }} {{ __("no scans") }}</span>
		</div>

		<!-- Rows -->
		<div v-if="loading" class="am-empty">{{ __("Loading…") }}</div>
		<div v-else-if="!filteredRows.length" class="am-empty">
			{{ __("No scans for this day.") }}
		</div>
		<div v-else class="am-list" :style="{ '--head-w': headWidth + 'px' }">
			<!-- Hour ruler -->
			<div class="am-row am-ruler-row">
				<div class="am-rowhead">
					<span class="am-headlabel">{{ __("Employee") }}</span>
					<span class="am-resizer" @mousedown.prevent="startResize"></span>
				</div>
				<div class="am-ruler">
					<span
						v-for="h in rulerHours"
						:key="h"
						class="am-ruler-tick"
						:style="{ left: pct(hourToMs(h)) }"
						>{{ h }}:00</span
					>
				</div>
			</div>

			<div
				v-for="row in filteredRows"
				:key="row.employee + row.date"
				class="am-row"
				:class="{ 'am-row-absent': row.flag === 'no_scans' }"
			>
				<div class="am-rowhead">
					<div class="am-name" :title="row.employee">{{ row.employee_name }}</div>
					<div class="am-hours">
						<template v-if="row.flag !== 'no_scans'">
							<span class="am-work">{{ fmtH(row.work_hours) }}</span>
							<span class="am-break" v-if="row.break_hours">☕ {{ fmtH(row.break_hours) }}</span>
							<span v-if="row.flag" class="am-flagicon" :title="flagLabel(row.flag)">⚠</span>
							<span v-else-if="onSite(row)" class="am-nowicon" :title="__('On site now')">●</span>
							<span v-else class="am-okicon">✓</span>
						</template>
						<span v-else class="am-absenticon">—</span>
					</div>
				</div>
				<TimelineRow
					:row="row"
					:date="date"
					:scale-min="scale.min"
					:scale-span="scale.span"
					:is-today="isToday"
					:now-ms-abs="isToday && nowInScale ? nowMs : -1"
					@add="(p) => openAdd(row, p)"
					@edit="(p) => openEdit(row, p.checkin, p)"
					@dragsave="(p) => onDragSave(row, p)"
				/>
			</div>
		</div>

		<PunchDialog
			v-if="dialog"
			:mode="dialog.mode"
			:employee-name="dialog.employeeName"
			:date="date"
			:prefill="dialog.prefill"
			:checkin-name="dialog.checkinName"
			:busy="saving"
			:x="dialog.x"
			:y="dialog.y"
			@save="onSave"
			@remove="onRemove"
			@close="dialog = null"
		/>
	</div>
</template>

<script>
import PunchDialog from "./PunchDialog.vue";
import TimelineRow from "./TimelineRow.vue";
import * as api from "./api.js";

export default {
	name: "AttendanceMonitorApp",
	components: { PunchDialog, TimelineRow },
	data() {
		const n = new Date();
		const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
		return {
			date: today,
			company: "VGH B.V.",
			companies: [],
			department: "",
			search: "",
			rows: [],
			loading: false,
			saving: false,
			dialog: null,
			nowTick: Date.now(),
			headWidth: Number(localStorage.getItem("am_head_w")) || 230,
		};
	},
	computed: {
		isToday() {
			return this.date === this.localToday();
		},
		displayDate() {
			const [y, m, d] = this.date.split("-").map(Number);
			const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1];
			return `${String(d).padStart(2, "0")} ${mon} ${y}`;
		},
		departments() {
			return [...new Set(this.rows.map((r) => r.department).filter(Boolean))].sort();
		},
		filteredRows() {
			const q = this.search.toLowerCase();
			return this.rows.filter(
				(r) =>
					(!q || r.employee_name.toLowerCase().includes(q)) &&
					(!this.department || r.department === this.department)
			);
		},
		scannedCount() {
			return this.rows.filter((r) => r.checkins.length).length;
		},
		flaggedCount() {
			return this.rows.filter((r) => r.flag && r.flag !== "no_scans").length;
		},
		absentCount() {
			return this.rows.filter((r) => r.flag === "no_scans").length;
		},
		onSiteCount() {
			return this.rows.filter((r) => this.onSite(r)).length;
		},
		// Timeline scale: floor/ceil to the hour around all scans, min 4h span.
		scale() {
			let min = Infinity;
			let max = -Infinity;
			for (const r of this.rows) {
				for (const c of r.checkins) {
					const t = this.toMs(c.time);
					if (t < min) min = t;
					if (t > max) max = t;
				}
			}
			if (!isFinite(min)) {
				min = this.hourToMs(6);
				max = this.hourToMs(18);
			}
			min = Math.floor(min / 3600000) * 3600000;
			max = Math.ceil(max / 3600000) * 3600000;
			if (this.isToday) max = Math.max(max, Math.ceil(this.nowMsAbs() / 3600000) * 3600000);
			if (max - min < 4 * 3600000) max = min + 4 * 3600000;
			return { min, max, span: max - min };
		},
		rulerHours() {
			const startH = Math.round(this.scale.min / 3600000);
			const n = Math.round(this.scale.span / 3600000);
			const step = n > 10 ? 2 : 1;
			const hours = [];
			for (let i = 0; i <= n; i += step) hours.push(startH + i);
			return hours;
		},
		nowMs() {
			return this.nowMsAbs();
		},
		nowInScale() {
			const t = this.nowMsAbs();
			return t >= this.scale.min && t <= this.scale.max;
		},
	},
	mounted() {
		// Resolve the permitted company list first so a restricted supervisor
		// never issues a query for a company they can't access.
		api.fetchCompanies().then((list) => {
			this.companies = list;
			if (list.length && !list.includes(this.company)) {
				this.company = list[0];
			}
			this.load();
		});
		this._timer = setInterval(() => (this.nowTick = Date.now()), 60000);
	},
	beforeUnmount() {
		clearInterval(this._timer);
	},
	methods: {
		__(s) {
			return typeof __ !== "undefined" ? __(s) : s;
		},
		async load() {
			this.loading = !this.rows.length; // quiet refresh: keep rows on screen
			try {
				this.rows = (await api.fetchMonitor({
					from_date: this.date,
					to_date: this.date,
					company: this.company,
					include_absent: 1,
				})) || [];
			} finally {
				this.loading = false;
			}
		},
		localToday() {
			const d = new Date();
			return this.fmtDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
		},
		fmtDate(y, m, d) {
			return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
		},
		shiftDay(n) {
			// build the date from LOCAL parts — toISOString() would shift by the
			// UTC offset (CEST) and eat the increment.
			const [y, m, d] = this.date.split("-").map(Number);
			const nd = new Date(y, m - 1, d + n);
			this.date = this.fmtDate(nd.getFullYear(), nd.getMonth() + 1, nd.getDate());
			this.load();
		},
		goToday() {
			this.date = this.localToday();
			this.load();
		},
		openPicker() {
			const el = this.$refs.picker;
			if (el && el.showPicker) {
				try {
					el.showPicker();
					return;
				} catch (e) {
					/* fall through */
				}
			}
			el && el.focus();
		},
		onCompanyChange() {
			this.department = "";
			this.load();
		},
		// --- resizable name column ---
		startResize(ev) {
			const startX = ev.clientX;
			const startW = this.headWidth;
			const move = (e) => {
				this.headWidth = Math.max(140, Math.min(520, startW + (e.clientX - startX)));
			};
			const up = () => {
				window.removeEventListener("mousemove", move);
				window.removeEventListener("mouseup", up);
				document.body.classList.remove("am-resizing");
				localStorage.setItem("am_head_w", String(this.headWidth));
			};
			window.addEventListener("mousemove", move);
			window.addEventListener("mouseup", up);
			document.body.classList.add("am-resizing");
		},
		// --- time helpers (all relative to selected date, in ms) ---
		toMs(iso) {
			return new Date(iso).getTime() - new Date(this.date + "T00:00:00").getTime();
		},
		hourToMs(h) {
			return h * 3600000;
		},
		nowMsAbs() {
			this.nowTick; // reactive dependency
			return Date.now() - new Date(this.date + "T00:00:00").getTime();
		},
		pct(ms) {
			const p = ((ms - this.scale.min) / this.scale.span) * 100;
			return Math.max(0, Math.min(100, p)) + "%";
		},
		fmtH(h) {
			const hh = Math.floor(h);
			const mm = Math.round((h - hh) * 60);
			return `${hh}:${String(mm).padStart(2, "0")}`;
		},
		flagLabel(flag) {
			return flag === "missing_punch"
				? this.__("Missing punch — odd number of scans")
				: this.__("Unexpected number of scans");
		},
		onSite(row) {
			return this.isToday && row.checkins.length % 2 === 1;
		},
		// --- corrections ---
		openAdd(row, { time, x, y }) {
			this.dialog = {
				mode: "add",
				employee: row.employee,
				employeeName: row.employee_name,
				prefill: time,
				checkinName: null,
				x,
				y,
			};
		},
		openEdit(row, checkin, pos = {}) {
			this.dialog = {
				mode: "edit",
				employee: row.employee,
				employeeName: row.employee_name,
				prefill: checkin.time.slice(11, 16),
				checkinName: checkin.name,
				x: pos.x || window.innerWidth / 2,
				y: pos.y || 120,
			};
		},
		async onDragSave(row, { name, time }) {
			await api.updateCheckin({ name, time: `${this.date} ${time}:00` });
			if (typeof frappe !== "undefined" && frappe.show_alert) {
				frappe.show_alert({
					message: `${row.employee_name} → ${time}`,
					indicator: "green",
				}, 3);
			}
			await this.load();
		},
		async onSave({ name, time }) {
			this.saving = true;
			try {
				if (this.dialog.mode === "add") {
					await api.addCheckin({ employee: this.dialog.employee, time });
				} else {
					await api.updateCheckin({ name, time });
				}
				this.dialog = null;
				await this.load();
			} finally {
				this.saving = false;
			}
		},
		async onRemove({ name }) {
			this.saving = true;
			try {
				await api.deleteCheckin({ name });
				this.dialog = null;
				await this.load();
			} finally {
				this.saving = false;
			}
		},
	},
};
</script>

<style>
/* not scoped: global cursor while resizing the name column */
body.am-resizing,
body.am-resizing * {
	cursor: col-resize !important;
	user-select: none !important;
}
</style>

<style scoped>
.am-root {
	padding: 12px 16px 48px;
	max-width: 1400px;
}
.am-toolbar {
	display: flex;
	flex-wrap: wrap;
	gap: 10px;
	align-items: center;
	margin-bottom: 10px;
}
.am-dategroup {
	display: flex;
	gap: 6px;
	align-items: center;
}
.am-nav,
.am-today {
	border: 1px solid var(--border-color, #d1d8dd);
	background: var(--control-bg, #f4f5f6);
	border-radius: 8px;
	min-width: 38px;
	min-height: 36px;
	font-size: 16px;
	cursor: pointer;
}
.am-today {
	font-size: 13px;
	padding: 0 10px;
}
.am-datebtn {
	position: relative;
	border: 1px solid var(--border-color, #d1d8dd);
	background: var(--control-bg, #fff);
	border-radius: 8px;
	padding: 7px 12px;
	font-size: 13px;
	min-height: 36px;
	min-width: 118px;
	cursor: pointer;
	font-variant-numeric: tabular-nums;
}
.am-date-native {
	position: absolute;
	inset: 0;
	opacity: 0;
	pointer-events: none;
	width: 100%;
}
.am-search,
.am-select {
	border: 1px solid var(--border-color, #d1d8dd);
	border-radius: 8px;
	padding: 7px 10px;
	font-size: 13px;
	min-height: 36px;
	background: var(--control-bg, #fff);
}
.am-search {
	flex: 1;
	min-width: 140px;
}
.am-chips {
	display: flex;
	gap: 8px;
	margin: 2px 0 18px;
	flex-wrap: wrap;
}
.am-chip {
	background: var(--control-bg, #f4f5f6);
	border-radius: 20px;
	padding: 4px 12px;
	font-size: 12px;
}
.am-chip-flag {
	background: #fdf0e7;
	color: #b45309;
}
.am-chip-now {
	background: #e8f6ee;
	color: #1e7e46;
}
.am-empty {
	color: var(--text-muted, #6c7680);
	padding: 40px 0;
	text-align: center;
}
.am-row {
	display: flex;
	align-items: center;
	gap: 14px;
	padding: 9px 6px;
	border-bottom: 1px solid var(--border-color, #ebeef0);
	border-radius: 8px;
	transition: background 0.15s;
}
.am-row:hover {
	background: rgba(100, 116, 139, 0.05);
}
.am-rowhead {
	position: relative;
	width: var(--head-w, 230px);
	min-width: var(--head-w, 230px);
	display: flex;
	justify-content: space-between;
	align-items: baseline;
	gap: 8px;
}
.am-headlabel {
	font-size: 11px;
	font-weight: 600;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: var(--text-muted, #98a1a9);
}
.am-resizer {
	position: absolute;
	right: -8px;
	top: -4px;
	bottom: -4px;
	width: 12px;
	cursor: col-resize;
	z-index: 5;
}
.am-resizer::after {
	content: "";
	position: absolute;
	left: 5px;
	top: 4px;
	bottom: 4px;
	width: 2px;
	background: var(--border-color, #cdd5db);
	border-radius: 2px;
}
.am-resizer:hover::after {
	background: #1f6fd6;
}
.am-name {
	font-weight: 500;
	font-size: 13px;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.am-hours {
	font-size: 12px;
	display: flex;
	gap: 8px;
	align-items: baseline;
	white-space: nowrap;
}
.am-work {
	font-weight: 600;
}
.am-break {
	color: #b45309;
}
.am-flagicon {
	color: #d97706;
}
.am-nowicon {
	color: #1e9e56;
}
.am-okicon {
	color: #9aa5ad;
}
.am-absenticon {
	color: #b6bfc6;
}
.am-row-absent .am-name {
	color: var(--text-muted, #98a1a9);
	font-weight: 400;
}
.am-chip-absent {
	background: #f2f4f6;
	color: #8a949c;
	border: 1px dashed #c9d1d8;
}
.am-ruler-row {
	border-bottom: none;
	padding-bottom: 0;
}
.am-ruler {
	position: relative;
	flex: 1;
	height: 16px;
}
.am-ruler-tick {
	position: absolute;
	transform: translateX(-50%);
	font-size: 10px;
	color: var(--text-muted, #98a1a9);
}

/* --- Mobile: stack the row, larger touch targets --- */
@media (max-width: 640px) {
	.am-row {
		flex-direction: column;
		align-items: stretch;
		gap: 4px;
		padding: 10px 0;
	}
	.am-rowhead {
		width: 100%;
		min-width: 0;
	}
	.am-ruler-row {
		display: none;
	}
}
</style>

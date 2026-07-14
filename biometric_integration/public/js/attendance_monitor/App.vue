<template>
	<div class="am-root">
		<!-- Toolbar -->
		<div class="am-toolbar">
			<div class="am-dategroup">
				<button class="am-nav" @click="shiftDay(-1)">&lsaquo;</button>
				<input v-model="date" type="date" class="am-date" @change="load" />
				<button class="am-nav" @click="shiftDay(1)">&rsaquo;</button>
				<button class="am-today" :disabled="isToday" @click="goToday">{{ __("Today") }}</button>
			</div>
			<input
				v-model.trim="search"
				type="search"
				class="am-search"
				:placeholder="__('Search worker…')"
			/>
			<select v-if="companies.length > 1" v-model="company" class="am-company" @change="load">
				<option v-for="c in companies" :key="c" :value="c">{{ c }}</option>
			</select>
		</div>

		<!-- Summary chips -->
		<div class="am-chips">
			<span class="am-chip">{{ rows.length }} {{ __("scanned") }}</span>
			<span class="am-chip am-chip-flag" v-if="flaggedCount">⚠ {{ flaggedCount }} {{ __("flagged") }}</span>
			<span class="am-chip am-chip-now" v-if="isToday">● {{ onSiteCount }} {{ __("on site now") }}</span>
		</div>

		<!-- Rows -->
		<div v-if="loading" class="am-empty">{{ __("Loading…") }}</div>
		<div v-else-if="!filteredRows.length" class="am-empty">
			{{ __("No scans for this day.") }}
		</div>
		<div v-else class="am-list">
			<!-- Hour ruler -->
			<div class="am-row am-ruler-row">
				<div class="am-rowhead"></div>
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

			<div v-for="row in filteredRows" :key="row.employee + row.date" class="am-row">
				<div class="am-rowhead">
					<div class="am-name" :title="row.employee">{{ row.employee_name }}</div>
					<div class="am-hours">
						<span class="am-work">{{ fmtH(row.work_hours) }}</span>
						<span class="am-break" v-if="row.break_hours">☕ {{ fmtH(row.break_hours) }}</span>
						<span v-if="row.flag" class="am-flagicon" :title="flagLabel(row.flag)">⚠</span>
						<span v-else-if="onSite(row)" class="am-nowicon" :title="__('On site now')">●</span>
						<span v-else class="am-okicon">✓</span>
					</div>
				</div>
				<div
					class="am-bar"
					:class="{ 'am-bar-flagged': row.flag === 'missing_punch' }"
					@click="barClick($event, row)"
				>
					<div
						v-for="(s, i) in row.segments"
						:key="i"
						class="am-seg"
						:class="s.type === 'work' ? 'am-seg-work' : 'am-seg-break'"
						:style="segStyle(s)"
					></div>
					<div
						v-for="c in row.checkins"
						:key="c.name"
						class="am-dot"
						:style="{ left: pct(toMs(c.time)) }"
						:title="c.time.slice(11, 16)"
						@click.stop="openEdit(row, c)"
					></div>
					<div v-if="isToday && nowInScale" class="am-nowline" :style="{ left: pct(nowMs) }"></div>
				</div>
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
			@save="onSave"
			@remove="onRemove"
			@close="dialog = null"
		/>
	</div>
</template>

<script>
import PunchDialog from "./PunchDialog.vue";
import * as api from "./api.js";

const DAY_MS = 86400000;

export default {
	name: "AttendanceMonitorApp",
	components: { PunchDialog },
	data() {
		const today = new Date().toISOString().slice(0, 10);
		return {
			date: today,
			company: "VGH B.V.",
			companies: [],
			search: "",
			rows: [],
			loading: false,
			saving: false,
			dialog: null,
			nowTick: Date.now(),
		};
	},
	computed: {
		isToday() {
			return this.date === new Date().toISOString().slice(0, 10);
		},
		filteredRows() {
			const q = this.search.toLowerCase();
			return q
				? this.rows.filter((r) => r.employee_name.toLowerCase().includes(q))
				: this.rows;
		},
		flaggedCount() {
			return this.rows.filter((r) => r.flag).length;
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
			this.loading = true;
			try {
				this.rows = (await api.fetchMonitor({
					from_date: this.date,
					to_date: this.date,
					company: this.company,
				})) || [];
			} finally {
				this.loading = false;
			}
		},
		shiftDay(n) {
			const d = new Date(this.date + "T00:00:00");
			d.setDate(d.getDate() + n);
			this.date = d.toISOString().slice(0, 10);
			this.load();
		},
		goToday() {
			this.date = new Date().toISOString().slice(0, 10);
			this.load();
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
		segStyle(s) {
			const a = this.toMs(s.start);
			const b = this.toMs(s.end);
			return {
				left: this.pct(a),
				width: `calc(${this.pct(b)} - ${this.pct(a)})`,
			};
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
		barClick(ev, row) {
			const rect = ev.currentTarget.getBoundingClientRect();
			const frac = (ev.clientX - rect.left) / rect.width;
			const ms = this.scale.min + frac * this.scale.span;
			const rounded = Math.round(ms / 300000) * 300000; // 5-minute snap
			const hh = String(Math.floor(rounded / 3600000)).padStart(2, "0");
			const mm = String(Math.floor((rounded % 3600000) / 60000)).padStart(2, "0");
			this.dialog = {
				mode: "add",
				employee: row.employee,
				employeeName: row.employee_name,
				prefill: `${hh}:${mm}`,
				checkinName: null,
			};
		},
		openEdit(row, checkin) {
			this.dialog = {
				mode: "edit",
				employee: row.employee,
				employeeName: row.employee_name,
				prefill: checkin.time.slice(11, 16),
				checkinName: checkin.name,
			};
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

<style scoped>
.am-root {
	padding: 4px 0 40px;
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
.am-date,
.am-search,
.am-company {
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
	margin-bottom: 14px;
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
	gap: 12px;
	padding: 7px 0;
	border-bottom: 1px solid var(--border-color, #ebeef0);
}
.am-rowhead {
	width: 230px;
	min-width: 230px;
	display: flex;
	justify-content: space-between;
	align-items: baseline;
	gap: 8px;
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
.am-bar {
	position: relative;
	flex: 1;
	height: 30px;
	background: var(--control-bg, #f4f5f6);
	border-radius: 6px;
	cursor: copy;
}
.am-bar-flagged {
	outline: 1.5px dashed #e8a13c;
	outline-offset: 1px;
}
.am-seg {
	position: absolute;
	top: 6px;
	bottom: 6px;
	border-radius: 4px;
}
.am-seg-work {
	background: #4caf7d;
}
.am-seg-break {
	background: #f0b95e;
}
.am-dot {
	position: absolute;
	top: 50%;
	width: 14px;
	height: 14px;
	margin: -7px 0 0 -7px;
	border-radius: 50%;
	background: #fff;
	border: 2.5px solid #2c3e50;
	cursor: pointer;
	z-index: 2;
}
.am-dot:hover {
	transform: scale(1.25);
}
.am-nowline {
	position: absolute;
	top: -2px;
	bottom: -2px;
	width: 2px;
	background: #e74c3c;
	z-index: 1;
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
	.am-bar {
		/* in the stacked (column-flex) layout, flex-basis 0 would collapse the
		   bar to zero height — pin it */
		flex: none;
		height: 38px;
	}
	.am-dot {
		width: 18px;
		height: 18px;
		margin: -9px 0 0 -9px;
	}
	.am-ruler-row {
		display: none;
	}
}
</style>

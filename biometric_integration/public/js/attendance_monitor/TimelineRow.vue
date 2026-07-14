<template>
	<div
		class="tr-bar"
		:class="{ 'tr-bar-flagged': row.flag === 'missing_punch', 'tr-bar-empty': isEmpty }"
		ref="bar"
		@mousemove="onHover"
		@mouseleave="hoverMs = null"
		@click="onBarClick"
	>
		<span v-if="isEmpty && !hoverMs" class="tr-empty-label">{{ emptyLabel }}</span>

		<div
			v-for="(s, i) in row.segments"
			:key="'s' + i"
			class="tr-seg"
			:class="s.type === 'work' ? 'tr-seg-work' : 'tr-seg-break'"
			:style="segStyle(s)"
		></div>

		<div
			v-for="c in dots"
			:key="c.name"
			class="tr-dot"
			:class="{ 'tr-dot-drag': drag && drag.name === c.name }"
			:style="{ left: pct(c.ms) }"
			@mousedown.prevent.stop="startDrag(c, $event)"
			@click.stop
		></div>

		<!-- hover ghost: vertical line + time pill -->
		<template v-if="hoverMs !== null && !drag">
			<div class="tr-ghost" :style="{ left: pct(hoverMs) }"></div>
			<div class="tr-pill" :style="pillStyle(hoverMs)">＋ {{ fmt(hoverMs) }}</div>
		</template>

		<!-- drag feedback: line + pill with live time and recomputed work total -->
		<template v-if="drag">
			<div class="tr-ghost tr-ghost-drag" :style="{ left: pct(drag.curMs) }"></div>
			<div class="tr-pill tr-pill-drag" :style="pillStyle(drag.curMs)">
				{{ fmt(drag.curMs) }} · {{ liveTotals }}
			</div>
		</template>

		<div v-if="isToday && nowMs >= 0 && nowMs <= scaleSpan + 0" class="tr-nowline" :style="{ left: pct(nowMsAbs) }"></div>
	</div>
</template>

<script>
const SNAP = 300000; // 5 minutes

export default {
	name: "TimelineRow",
	props: {
		row: { type: Object, required: true },
		date: { type: String, required: true },
		scaleMin: { type: Number, required: true },
		scaleSpan: { type: Number, required: true },
		isToday: { type: Boolean, default: false },
		nowMsAbs: { type: Number, default: -1 },
	},
	emits: ["add", "edit", "dragsave"],
	data() {
		return { hoverMs: null, drag: null, suppressClick: false };
	},
	computed: {
		isEmpty() {
			return !this.row.checkins.length;
		},
		emptyLabel() {
			return typeof __ !== "undefined" ? __("no scans — click to add") : "no scans — click to add";
		},
		nowMs() {
			return this.nowMsAbs - this.scaleMin;
		},
		dots() {
			// during a drag, show the dragged dot at its live position
			return this.row.checkins.map((c) => ({
				name: c.name,
				ms: this.drag && this.drag.name === c.name ? this.drag.curMs : this.toMs(c.time),
			}));
		},
		liveTotals() {
			// recompute work/break locally from the live dot positions (odd/even pairing)
			const t = this.dots.map((d) => d.ms).sort((a, b) => a - b);
			let work = 0;
			let brk = 0;
			for (let i = 0; i + 1 < t.length; i += 2) {
				work += t[i + 1] - t[i];
				if (i + 3 < t.length) brk += t[i + 2] - t[i + 1];
			}
			const f = (ms) => {
				const h = Math.floor(ms / 3600000);
				const m = Math.round((ms % 3600000) / 60000);
				return `${h}:${String(m).padStart(2, "0")}`;
			};
			const wl = typeof __ !== "undefined" ? __("work") : "work";
			return brk ? `${f(work)} ${wl} · ☕ ${f(brk)}` : `${f(work)} ${wl}`;
		},
	},
	beforeUnmount() {
		this.unbindDrag();
	},
	methods: {
		toMs(iso) {
			return new Date(iso).getTime() - new Date(this.date + "T00:00:00").getTime();
		},
		pct(ms) {
			const p = ((ms - this.scaleMin) / this.scaleSpan) * 100;
			return Math.max(0, Math.min(100, p)) + "%";
		},
		fmt(ms) {
			const hh = String(Math.floor(ms / 3600000)).padStart(2, "0");
			const mm = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
			return `${hh}:${mm}`;
		},
		pillStyle(ms) {
			// keep the pill inside the bar near the edges
			const p = ((ms - this.scaleMin) / this.scaleSpan) * 100;
			if (p < 8) return { left: p + "%", transform: "translateX(0)" };
			if (p > 92) return { left: p + "%", transform: "translateX(-100%)" };
			return { left: p + "%", transform: "translateX(-50%)" };
		},
		segStyle(s) {
			const a = this.toMs(s.start);
			const b = this.toMs(s.end);
			return { left: this.pct(a), width: `calc(${this.pct(b)} - ${this.pct(a)})` };
		},
		eventMs(ev) {
			const rect = this.$refs.bar.getBoundingClientRect();
			const frac = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
			const raw = this.scaleMin + frac * this.scaleSpan;
			return Math.round(raw / SNAP) * SNAP;
		},
		onHover(ev) {
			if (this.drag) return;
			if (ev.target.classList.contains("tr-dot")) {
				this.hoverMs = null;
				return;
			}
			this.hoverMs = this.eventMs(ev);
		},
		onBarClick(ev) {
			if (this.suppressClick) {
				this.suppressClick = false;
				return;
			}
			this.$emit("add", this.fmt(this.eventMs(ev)));
		},
		// ---- drag ----
		startDrag(c, ev) {
			// only left button; touch taps come through as click-without-move
			if (ev.button !== 0) return;
			this.hoverMs = null;
			this.drag = { name: c.name, origMs: c.ms, curMs: c.ms, moved: false };
			this._onMove = (e) => this.dragMove(e);
			this._onUp = (e) => this.dragEnd(e);
			this._onKey = (e) => {
				if (e.key === "Escape") this.cancelDrag();
			};
			window.addEventListener("mousemove", this._onMove);
			window.addEventListener("mouseup", this._onUp);
			window.addEventListener("keydown", this._onKey);
			document.body.classList.add("tr-dragging");
		},
		dragMove(ev) {
			if (!this.drag) return;
			const ms = this.eventMs(ev);
			if (ms !== this.drag.curMs) {
				this.drag.curMs = ms;
				if (ms !== this.drag.origMs) this.drag.moved = true;
			}
		},
		dragEnd() {
			if (!this.drag) return;
			const { name, curMs, origMs, moved } = this.drag;
			this.unbindDrag();
			this.drag = null;
			this.suppressClick = true; // the mouseup will also fire a bar click
			if (!moved || curMs === origMs) {
				const checkin = this.row.checkins.find((c) => c.name === name);
				checkin && this.$emit("edit", checkin);
			} else {
				this.$emit("dragsave", { name, time: this.fmt(curMs) });
			}
		},
		cancelDrag() {
			this.unbindDrag();
			this.drag = null;
			this.suppressClick = true;
		},
		unbindDrag() {
			if (this._onMove) window.removeEventListener("mousemove", this._onMove);
			if (this._onUp) window.removeEventListener("mouseup", this._onUp);
			if (this._onKey) window.removeEventListener("keydown", this._onKey);
			this._onMove = this._onUp = this._onKey = null;
			document.body.classList.remove("tr-dragging");
		},
	},
};
</script>

<style>
/* not scoped: body-level drag cursor */
body.tr-dragging,
body.tr-dragging * {
	cursor: grabbing !important;
	user-select: none !important;
}
</style>

<style scoped>
.tr-bar {
	position: relative;
	flex: 1;
	height: 30px;
	background: var(--control-bg, #f4f5f6);
	border-radius: 6px;
	cursor: copy;
}
.tr-bar-flagged {
	outline: 1.5px dashed #e8a13c;
	outline-offset: 1px;
}
.tr-bar-empty {
	background: transparent;
	border: 1.5px dashed var(--border-color, #cdd5db);
}
.tr-empty-label {
	position: absolute;
	inset: 0;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: 11px;
	color: var(--text-muted, #a3adb5);
	pointer-events: none;
}
.tr-seg {
	position: absolute;
	top: 6px;
	bottom: 6px;
	border-radius: 4px;
	pointer-events: none;
}
.tr-seg-work {
	background: #4caf7d;
}
.tr-seg-break {
	background: #f0b95e;
}
.tr-dot {
	position: absolute;
	top: 50%;
	width: 14px;
	height: 14px;
	margin: -7px 0 0 -7px;
	border-radius: 50%;
	background: #fff;
	border: 2.5px solid #2c3e50;
	cursor: grab;
	z-index: 3;
	transition: transform 0.1s;
}
.tr-dot:hover {
	transform: scale(1.3);
}
.tr-dot-drag {
	transform: scale(1.35);
	border-color: #1f6fd6;
	box-shadow: 0 2px 8px rgba(31, 111, 214, 0.45);
}
.tr-ghost {
	position: absolute;
	top: -3px;
	bottom: -3px;
	width: 1.5px;
	background: #64748b;
	pointer-events: none;
	z-index: 2;
}
.tr-ghost-drag {
	background: #1f6fd6;
	width: 2px;
}
.tr-pill {
	position: absolute;
	bottom: calc(100% + 5px);
	background: #1e293b;
	color: #fff;
	font-size: 11px;
	line-height: 1;
	padding: 5px 8px;
	border-radius: 6px;
	white-space: nowrap;
	pointer-events: none;
	z-index: 10;
}
.tr-pill-drag {
	background: #1f6fd6;
	font-weight: 600;
}
.tr-nowline {
	position: absolute;
	top: -2px;
	bottom: -2px;
	width: 2px;
	background: #e74c3c;
	z-index: 1;
}
@media (max-width: 640px) {
	.tr-bar {
		flex: none;
		height: 38px;
	}
	.tr-dot {
		width: 18px;
		height: 18px;
		margin: -9px 0 0 -9px;
	}
}
</style>

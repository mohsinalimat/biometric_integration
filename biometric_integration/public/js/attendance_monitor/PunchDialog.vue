<template>
	<div ref="card" class="pd-pop" :style="popStyle" @keydown.esc="$emit('close')">
		<div class="pd-head">
			<span class="pd-title">{{ mode === "add" ? labels.add : labels.edit }}</span>
			<span class="pd-emp">{{ employeeName }}</span>
		</div>
		<div class="pd-body">
			<input
				ref="timeInput"
				v-model="time"
				type="time"
				step="60"
				class="pd-time"
				@keyup.enter="save"
			/>
			<button class="pd-btn pd-primary" :disabled="busy || !time" @click="save">
				{{ mode === "add" ? labels.add_btn : labels.save_btn }}
			</button>
			<button
				v-if="mode === 'edit'"
				class="pd-btn pd-danger"
				:disabled="busy"
				:title="labels.delete_btn"
				@click="$emit('remove', { name: checkinName })"
			>
				✕
			</button>
		</div>
	</div>
</template>

<script>
// Compact popover anchored at the click/dot position (x, y in viewport px).
// Desktop: floats under the anchor. Mobile (<640px): bottom sheet.
// Enter saves, Escape or clicking outside closes.
export default {
	name: "PunchDialog",
	props: {
		mode: { type: String, required: true },
		employeeName: { type: String, required: true },
		date: { type: String, required: true },
		prefill: { type: String, default: "" },
		checkinName: { type: String, default: null },
		busy: { type: Boolean, default: false },
		x: { type: Number, default: 0 },
		y: { type: Number, default: 0 },
	},
	emits: ["save", "remove", "close"],
	data() {
		return {
			time: this.prefill,
			labels: {
				add: __("Add punch"),
				edit: __("Edit punch"),
				add_btn: __("Add"),
				save_btn: __("Save"),
				delete_btn: __("Delete"),
			},
		};
	},
	computed: {
		popStyle() {
			if (window.innerWidth <= 640) return {}; // bottom sheet via CSS
			const W = 250;
			const left = Math.min(Math.max(this.x - W / 2, 8), window.innerWidth - W - 8);
			const top = Math.min(this.y + 14, window.innerHeight - 90);
			return { left: left + "px", top: top + "px", width: W + "px" };
		},
	},
	mounted() {
		this.$refs.timeInput && this.$refs.timeInput.focus();
		// close on outside click — deferred so the opening click doesn't self-close
		setTimeout(() => {
			this._outside = (e) => {
				if (this.$refs.card && !this.$refs.card.contains(e.target)) this.$emit("close");
			};
			document.addEventListener("mousedown", this._outside);
		}, 0);
	},
	beforeUnmount() {
		this._outside && document.removeEventListener("mousedown", this._outside);
	},
	methods: {
		save() {
			if (!this.time) return;
			this.$emit("save", { name: this.checkinName, time: `${this.date} ${this.time}:00` });
		},
	},
};
</script>

<style scoped>
.pd-pop {
	position: fixed;
	z-index: 1060;
	background: var(--card-bg, #fff);
	border: 1px solid var(--border-color, #dfe4e8);
	border-radius: 10px;
	padding: 10px 12px;
	box-shadow: 0 10px 28px rgba(15, 23, 42, 0.16);
	animation: pd-in 0.12s ease-out;
}
@keyframes pd-in {
	from {
		opacity: 0;
		transform: translateY(-4px);
	}
	to {
		opacity: 1;
		transform: translateY(0);
	}
}
.pd-head {
	display: flex;
	gap: 6px;
	align-items: baseline;
	margin-bottom: 8px;
	font-size: 12px;
}
.pd-title {
	font-weight: 600;
}
.pd-emp {
	color: var(--text-muted, #6c7680);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.pd-body {
	display: flex;
	gap: 6px;
	align-items: center;
}
.pd-time {
	flex: 1;
	min-width: 0;
	font-size: 15px;
	padding: 6px 8px;
	border: 1px solid var(--border-color, #d1d8dd);
	border-radius: 8px;
}
.pd-btn {
	border-radius: 8px;
	border: 1px solid var(--border-color, #d1d8dd);
	background: var(--control-bg, #f4f5f6);
	font-size: 13px;
	cursor: pointer;
	padding: 7px 12px;
	min-height: 34px;
}
.pd-primary {
	background: var(--primary, #171717);
	color: #fff;
	border-color: transparent;
}
.pd-danger {
	background: #fff0f0;
	color: #c0392b;
	border-color: #f1c7c2;
	padding: 7px 10px;
}
.pd-btn:disabled {
	opacity: 0.55;
}

@media (max-width: 640px) {
	.pd-pop {
		left: 0 !important;
		right: 0;
		top: auto !important;
		bottom: 0;
		width: auto !important;
		border-radius: 14px 14px 0 0;
		padding: 14px 16px calc(14px + env(safe-area-inset-bottom));
		animation: pd-up 0.16s ease-out;
	}
	@keyframes pd-up {
		from {
			transform: translateY(30%);
			opacity: 0.6;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}
	.pd-time {
		font-size: 18px;
	}
	.pd-btn {
		min-height: 42px;
	}
}
</style>

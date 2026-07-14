<template>
	<div class="pd-backdrop" @click.self="$emit('close')">
		<div class="pd-card">
			<div class="pd-title">
				{{ mode === "add" ? labels.add : labels.edit }}
				<span class="pd-emp">{{ employeeName }}</span>
			</div>
			<div class="pd-date">{{ date }}</div>
			<input
				ref="timeInput"
				v-model="time"
				type="time"
				step="60"
				class="pd-time"
				@keyup.enter="save"
			/>
			<div class="pd-actions">
				<button class="pd-btn pd-primary" :disabled="busy || !time" @click="save">
					{{ mode === "add" ? labels.add_btn : labels.save_btn }}
				</button>
				<button
					v-if="mode === 'edit'"
					class="pd-btn pd-danger"
					:disabled="busy"
					@click="remove"
				>
					{{ labels.delete_btn }}
				</button>
				<button class="pd-btn" :disabled="busy" @click="$emit('close')">
					{{ labels.cancel_btn }}
				</button>
			</div>
		</div>
	</div>
</template>

<script>
// mode "add":  employee + date + prefill time  → emits save({time})
// mode "edit": existing checkin {name, time}   → emits save({name, time}) / remove({name})
export default {
	name: "PunchDialog",
	props: {
		mode: { type: String, required: true },
		employeeName: { type: String, required: true },
		date: { type: String, required: true },
		prefill: { type: String, default: "" }, // "HH:MM"
		checkinName: { type: String, default: null },
		busy: { type: Boolean, default: false },
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
				cancel_btn: __("Cancel"),
			},
		};
	},
	mounted() {
		this.$refs.timeInput && this.$refs.timeInput.focus();
	},
	methods: {
		save() {
			if (!this.time) return;
			this.$emit("save", { name: this.checkinName, time: `${this.date} ${this.time}:00` });
		},
		remove() {
			this.$emit("remove", { name: this.checkinName });
		},
	},
};
</script>

<style scoped>
.pd-backdrop {
	position: fixed;
	inset: 0;
	background: rgba(0, 0, 0, 0.35);
	display: flex;
	align-items: center;
	justify-content: center;
	z-index: 1050;
}
.pd-card {
	background: var(--card-bg, #fff);
	border-radius: 10px;
	padding: 18px 20px;
	width: min(320px, calc(100vw - 32px));
	box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
}
.pd-title {
	font-weight: 600;
	margin-bottom: 2px;
}
.pd-emp {
	font-weight: 400;
	color: var(--text-muted, #6c7680);
	margin-left: 6px;
}
.pd-date {
	color: var(--text-muted, #6c7680);
	font-size: 12px;
	margin-bottom: 10px;
}
.pd-time {
	width: 100%;
	font-size: 22px;
	padding: 8px 10px;
	border: 1px solid var(--border-color, #d1d8dd);
	border-radius: 8px;
	margin-bottom: 14px;
}
.pd-actions {
	display: flex;
	gap: 8px;
}
.pd-btn {
	flex: 1;
	padding: 9px 0;
	border-radius: 8px;
	border: 1px solid var(--border-color, #d1d8dd);
	background: var(--control-bg, #f4f5f6);
	font-size: 13px;
	cursor: pointer;
	min-height: 38px; /* touch target */
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
}
.pd-btn:disabled {
	opacity: 0.55;
}
</style>

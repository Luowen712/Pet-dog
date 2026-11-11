<script setup lang="ts">
import { computed } from 'vue'
import type { ActionDef } from '@/constants/actions'
import { actionHex } from '@/constants/actions'
import type { ButtonState } from '@/stores/pet'

const props = defineProps<{ action: ActionDef; state: ButtonState; disabled?: boolean }>()
defineEmits<{ (event: 'click'): void }>()

const title = computed(() => {
  if (props.disabled) return `${props.action.name} · 本期未启用`
  const stateText: Record<ButtonState, string> = {
    idle: '点击下发',
    pending: '已提交，等待设备受理',
    accepted: '设备已受理，等待执行完成',
    ok: '设备已完成',
    fail: '设备拒绝或提交失败',
    unknown: '结果不明，需向后端核对',
  }
  return `${props.action.name} · 动作码 ${actionHex(props.action.code)} · ${stateText[props.state]}`
})
</script>

<template>
  <button
    type="button"
    class="action-btn"
    :class="[state, { disabled }]"
    :title="title"
    :disabled="disabled"
    @click="!disabled && $emit('click')"
  >
    <span class="row">
      <span class="code mono">{{ actionHex(action.code) }}</span>
      <span class="state-dot" />
    </span>
    <span class="label">{{ action.name }}</span>
    <span v-if="disabled" class="off mono">未启用</span>
  </button>
</template>

<style scoped>
.action-btn {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 9px;
  width: 100%;
  padding: 9px 11px 10px;
  border: 1px solid var(--hair);
  border-radius: var(--radius);
  background: var(--panel);
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.action-btn::after {
  content: '';
  position: absolute;
  left: -1px;
  right: -1px;
  bottom: -1px;
  height: 1px;
  background: var(--grad-line);
  opacity: 0;
  transition: opacity 0.18s ease;
}

.action-btn:hover {
  border-color: rgba(20, 20, 20, 0.38);
}

.action-btn:hover::after {
  opacity: 1;
}

.action-btn.disabled {
  cursor: not-allowed;
  background: rgba(247, 244, 238, 0.55);
  border-color: var(--hair-soft);
}

.action-btn.disabled .label,
.action-btn.disabled .code {
  color: var(--faint);
}

.action-btn.disabled:hover {
  border-color: var(--hair-soft);
}

.action-btn.disabled:hover::after {
  opacity: 0;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.code {
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--faint);
}

.label {
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.01em;
  color: var(--ink);
}

.off {
  position: absolute;
  right: 9px;
  bottom: 8px;
  font-size: 7.5px;
  letter-spacing: 0.1em;
  color: var(--faint);
}

.state-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(20, 20, 20, 0.18);
}

.action-btn.pending {
  background: #fbf2e3;
  border-color: rgba(154, 106, 28, 0.42);
}

.action-btn.pending .state-dot,
.action-btn.accepted .state-dot {
  background: var(--warn);
  animation: pulse 1s ease-in-out infinite;
}

.action-btn.accepted {
  background: #fbf2e3;
  border-color: rgba(154, 106, 28, 0.58);
}

.action-btn.ok {
  background: #eef3ee;
  border-color: rgba(47, 107, 79, 0.38);
}

.action-btn.ok .state-dot {
  background: var(--ok);
}

.action-btn.fail {
  background: #f8ecea;
  border-color: rgba(165, 58, 51, 0.38);
}

.action-btn.fail .state-dot {
  background: var(--danger);
}

.action-btn.unknown {
  background: #f1efe9;
  border-color: rgba(20, 20, 20, 0.24);
}

.action-btn.unknown .state-dot {
  background: rgba(20, 20, 20, 0.45);
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(154, 106, 28, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(154, 106, 28, 0);
  }
}
</style>

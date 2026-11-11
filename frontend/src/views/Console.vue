<script setup lang="ts">
import { computed } from 'vue'
import ActionButton from '@/components/ActionButton.vue'
import FaceTile from '@/components/FaceTile.vue'
import StateBar from '@/components/StateBar.vue'
import { ACTION_GROUPS, actionsOf } from '@/constants/actions'
import { FACES } from '@/constants/faces'
import { formatRelative } from '@/utils/format'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'
import type { ButtonState } from '@/stores/pet'

const deviceStore = useDeviceStore()
const pet = usePetStore()

/** 本期只启用七个动作 0x30～0x36，其余按钮保留但禁用 */
const ENABLED_ACTIONS = new Set([0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36])

const heartbeat = computed(() =>
  deviceStore.current ? formatRelative(deviceStore.current.last_heartbeat ?? undefined) : '--',
)

function isEnabled(code: number): boolean {
  return ENABLED_ACTIONS.has(code)
}

function stateOf(code: number): ButtonState {
  return pet.status[code] ?? 'idle'
}
</script>

<template>
  <div class="page console">
    <div class="page-head">
      <div>
        <div class="page-kicker">03 / Console</div>
        <h2 class="page-title">控制台</h2>
        <p class="page-sub">
          {{ deviceStore.current?.name ?? '未选择设备' }} · 点一下按钮，桌宠动一下
        </p>
      </div>
      <div class="legend">
        <span class="lg"><i class="sw pending" />已提交</span>
        <span class="lg"><i class="sw accepted" />已受理</span>
        <span class="lg"><i class="sw ok" />完成</span>
        <span class="lg"><i class="sw fail" />拒绝</span>
        <span class="lg"><i class="sw unknown" />结果不明</span>
      </div>
    </div>

    <section v-if="!deviceStore.current" class="card no-device">
      <div class="no-device-body">
        <span class="mono kicker">NO DEVICE</span>
        <h3>还没有绑定设备</h3>
        <p>先到设备页输入 6 位配对码认领一台桌宠，控制台才会连上实时通道。</p>
        <router-link to="/devices">
          <el-button type="primary">去认领设备</el-button>
        </router-link>
      </div>
    </section>

    <template v-else>
    <div class="cols">
      <div class="col">
        <section class="card">
          <div class="card-head">
            <span class="card-title">动作指令</span>
            <span class="card-meta">7 enabled · 其余本期禁用</span>
          </div>
          <div class="actions">
            <div v-for="(group, index) in ACTION_GROUPS" :key="group" class="group">
              <div class="group-title">
                <span class="mono num">{{ String(index + 1).padStart(2, '0') }}</span>
                <span>{{ group }}</span>
                <i class="mono">{{ actionsOf(group).length }}</i>
              </div>
              <div class="group-grid">
                <ActionButton
                  v-for="action in actionsOf(group)"
                  :key="action.code"
                  :action="action"
                  :state="stateOf(action.code)"
                  :disabled="!isEnabled(action.code)"
                  @click="pet.sendAction(action.code)"
                />
              </div>
            </div>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <span class="card-title">表情面板</span>
            <span class="card-meta">07 built-in · click to switch</span>
          </div>
          <div class="faces">
            <button
              v-for="face in FACES"
              :key="face.id"
              type="button"
              class="face-btn"
              :class="{ active: pet.face === face.id }"
              @click="pet.changeFace(face.id)"
            >
              <FaceTile :face="face.id" />
              <span class="face-meta">
                <span class="face-name">{{ face.name }}</span>
                <span class="mono face-id">0{{ face.id }}</span>
              </span>
            </button>
          </div>
        </section>
      </div>

      <div class="col right">
        <section class="card meta-card">
          <div class="card-head">
            <span class="card-title">设备信息</span>
            <span class="card-meta">Unit 01</span>
          </div>
          <div class="meta-list">
            <div class="meta-row">
              <span class="mono">Firmware</span>
              <span class="mono">{{ deviceStore.current?.firmware ?? '--' }}</span>
            </div>
            <div class="meta-row">
              <span class="mono">Control</span>
              <span class="mono">{{ deviceStore.current?.control_state ?? '--' }}</span>
            </div>
            <div class="meta-row">
              <span class="mono">Heartbeat</span>
              <span>{{ heartbeat }}</span>
            </div>
            <div class="meta-row">
              <span class="mono">Transport</span>
              <span class="mono">{{ pet.connected ? 'WS / ws/device' : 'OFFLINE' }}</span>
            </div>
          </div>
        </section>
      </div>
    </div>

    <StateBar />
    </template>
  </div>
</template>

<style scoped>
.legend {
  display: flex;
  align-items: center;
  gap: 16px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--faint);
}

.lg {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sw {
  width: 7px;
  height: 7px;
  display: inline-block;
  border-radius: 1px;
}

.sw.pending {
  background: var(--warn);
}

.sw.accepted {
  background: var(--warn);
  opacity: 0.6;
}

.sw.ok {
  background: var(--ok);
}

.sw.fail {
  background: var(--danger);
}

.sw.unknown {
  background: rgba(20, 20, 20, 0.42);
}

.no-device-body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 34px 28px;
}

.no-device-body .kicker {
  font-size: 9px;
  letter-spacing: 0.16em;
  color: var(--faint);
}

.no-device-body h3 {
  margin: 2px 0 0;
  font-size: 20px;
  font-weight: 500;
}

.no-device-body p {
  max-width: 520px;
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--dim);
}

.cols {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(340px, 1fr);
  gap: 18px;
  align-items: start;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 16px 20px 20px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 9px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.group-title .num {
  font-size: 8.5px;
  color: var(--faint);
  letter-spacing: 0.08em;
}

.group-title i {
  margin-left: auto;
  font-style: normal;
  font-size: 8.5px;
  color: var(--faint);
  letter-spacing: 0.1em;
}

.group + .group {
  padding-top: 16px;
  border-top: 1px solid var(--hair-soft);
}

.group-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.faces {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  padding: 16px 20px 20px;
}

.face-btn {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 7px;
  border: 1px solid var(--hair-soft);
  border-radius: var(--radius);
  background: transparent;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.face-btn:hover {
  border-color: rgba(20, 20, 20, 0.32);
}

.face-btn.active {
  border-color: var(--ink);
  background: rgba(255, 255, 255, 0.45);
}

.face-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2px;
}

.face-name {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--dim);
}

.face-btn.active .face-name {
  color: var(--ink);
}

.face-id {
  font-size: 8.5px;
  color: var(--faint);
  letter-spacing: 0.08em;
}

.meta-list {
  display: flex;
  flex-direction: column;
}

.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 20px;
  border-top: 1px solid var(--hair-soft);
  font-size: 12px;
}

.meta-row:first-child {
  border-top: 0;
}

.meta-row .mono:first-child {
  font-size: 8px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--faint);
}

.meta-row span:last-child {
  color: var(--ink);
  text-align: right;
}

@media (max-width: 1180px) {
  .cols {
    grid-template-columns: 1fr;
  }

  .right {
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: start;
  }

  .right :deep(.meta-card) {
    grid-column: 1 / -1;
  }
}

@media (max-width: 760px) {
  .group-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .faces {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .right {
    grid-template-columns: 1fr;
  }

  .legend {
    display: none;
  }
}
</style>

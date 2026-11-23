<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import ActionButton from '@/components/ActionButton.vue'
import FaceTile from '@/components/FaceTile.vue'
import RobotDog from '@/components/RobotDog.vue'
import StateBar from '@/components/StateBar.vue'
import { ACTION_GROUPS, actionsOf } from '@/constants/actions'
import type { ActionGroup } from '@/constants/actions'
import { FACES } from '@/constants/faces'
import { describeDeviceStatus } from '@/utils/format'
import { emitParticleBurst } from '@/utils/theme'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'
import type { ButtonState } from '@/stores/pet'

const deviceStore = useDeviceStore()
const pet = usePetStore()

/** 本期只启用七个动作 0x30～0x36，其余按钮保留但禁用 */
const ENABLED_ACTIONS = new Set([0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36])

const POSE_BY_ACTION: Record<number, string> = {
  0x30: 'pose-sit',
  0x31: 'pose-stand',
  0x32: 'pose-lie',
  0x33: 'pose-forward',
  0x34: 'pose-backward',
  0x35: 'pose-left',
  0x36: 'pose-right',
}

/** 每个动作分组独立抽屉收纳，默认收起 */
const openGroups = ref<Set<ActionGroup>>(new Set())

const statusView = computed(() =>
  describeDeviceStatus({
    online: pet.online,
    controlState: pet.controlState,
  }),
)

const needsReconnect = computed(() => !pet.online || pet.controlState === 'faulted')
const allExpanded = computed(() => openGroups.value.size === ACTION_GROUPS.length)
const activePose = computed(() => {
  if (!pet.online || pet.action === null) return ''
  return POSE_BY_ACTION[pet.action] ?? ''
})

function isGroupOpen(group: ActionGroup): boolean {
  return openGroups.value.has(group)
}

function toggleGroup(group: ActionGroup): void {
  const next = new Set(openGroups.value)
  if (next.has(group)) next.delete(group)
  else next.add(group)
  openGroups.value = next
}

function toggleAllGroups(): void {
  openGroups.value = allExpanded.value ? new Set() : new Set(ACTION_GROUPS)
}

function isEnabled(code: number): boolean {
  return (
    pet.connected &&
    pet.online &&
    pet.controlState === 'ready' &&
    ENABLED_ACTIONS.has(code) &&
    !!deviceStore.current?.supported_actions.includes(code)
  )
}

function enabledCount(group: ActionGroup): number {
  return actionsOf(group).filter((item) => isEnabled(item.code)).length
}

function stateOf(code: number): ButtonState {
  return pet.status[code] ?? 'idle'
}

function onFaceClick(faceId: number, event: MouseEvent): void {
  if (event.clientX > 0) emitParticleBurst(event.clientX, event.clientY, 'oled', 14)
  void pet.changeFace(faceId)
}
</script>

<template>
  <div class="page console">
    <div class="page-head">
      <div class="head-left">
        <h2 class="page-title">控制台</h2>
        <div v-if="deviceStore.current" class="device-line">
          <span class="device-name">{{ deviceStore.current.name }}</span>
          <span class="status" :class="statusView.tone">{{ statusView.label }}</span>
        </div>
      </div>

      <router-link v-if="deviceStore.current && needsReconnect" to="/devices">
        <el-button size="small">重连蓝牙</el-button>
      </router-link>
    </div>

    <section v-if="!deviceStore.current" class="card no-device">
      <div class="no-device-body">
        <h3>还没有绑定设备</h3>
        <router-link to="/devices">
          <el-button type="primary">去连接蓝牙设备</el-button>
        </router-link>
      </div>
    </section>

    <template v-else>
      <StateBar />

      <div class="cols">
        <section class="card">
          <div class="card-head">
            <span class="card-title">动作指令</span>
            <button type="button" class="toggle-all" @click="toggleAllGroups">
              {{ allExpanded ? '全部收起' : '全部展开' }}
            </button>
          </div>

          <div class="drawers">
            <div
              v-for="group in ACTION_GROUPS"
              :key="group"
              class="drawer"
              :class="{ open: isGroupOpen(group) }"
            >
              <button
                type="button"
                class="drawer-head"
                :aria-expanded="isGroupOpen(group)"
                @click="toggleGroup(group)"
              >
                <el-icon class="drawer-arrow"><ArrowRight /></el-icon>
                <span class="drawer-title">{{ group }}</span>
                <span class="drawer-meta mono">
                  <span v-if="enabledCount(group) > 0" class="avail-dot" />
                  {{ actionsOf(group).length }}
                </span>
              </button>

              <div class="drawer-body">
                <div class="drawer-inner">
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
            </div>
          </div>
        </section>

        <div class="right-stack">
          <section class="card pet-monitor">
            <RobotDog
              :face="pet.face"
              :online="pet.online"
              :pose="activePose"
              compact
              class="monitor-dog"
            />
          </section>

          <section class="card">
            <div class="card-head">
              <span class="card-title">表情</span>
              <router-link to="/faces" class="face-lib-link">
                进入表情库 <span class="mono">↗</span>
              </router-link>
            </div>
            <div class="faces">
              <button
                v-for="face in FACES"
                :key="face.id"
                type="button"
                class="face-btn"
                :class="{ active: pet.face === face.id, sending: pet.switchingFace === face.id }"
                :disabled="
                  !pet.connected ||
                  !pet.online ||
                  !['ready', 'busy'].includes(pet.controlState) ||
                  pet.switchingFace !== null
                "
                @click="onFaceClick(face.id, $event)"
              >
                <FaceTile :face="face.id" />
                <span class="face-name">{{ face.name }}</span>
              </button>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.head-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.device-line {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.device-name {
  font-size: 13.5px;
  color: var(--dim);
}

.no-device-body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
  padding: 32px 26px;
}

.no-device-body h3 {
  font-size: 18px;
  font-weight: 600;
}

.cols {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 1fr);
  gap: 18px;
  align-items: start;
}

.right-stack {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.pet-monitor {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px 20px 14px;
  background: var(--bg-stage);
}

.monitor-dog {
  max-width: 248px;
}

.toggle-all,
.face-lib-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  font-family: var(--sans);
  font-size: 12px;
  font-weight: 500;
  color: var(--dim);
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.16s ease;
}

.toggle-all:hover,
.face-lib-link:hover {
  color: var(--ink);
}

.drawers {
  display: flex;
  flex-direction: column;
}

.drawer {
  border-top: 1px solid var(--hair-soft);
}

.drawer:first-child {
  border-top: 0;
}

.drawer-head {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 15px 20px;
  border: 0;
  background: transparent;
  color: var(--ink);
  font-family: var(--sans);
  text-align: left;
  cursor: pointer;
  transition: background-color 0.16s ease;
}

.drawer-head:hover {
  background: var(--surface-2);
}

.drawer-arrow {
  font-size: 12px;
  color: var(--faint);
  transition:
    transform 0.24s var(--ease-out),
    color 0.18s ease;
}

.drawer.open .drawer-arrow {
  transform: rotate(90deg);
  color: var(--accent-1);
}

.drawer-title {
  font-size: 13.5px;
  font-weight: 600;
}

.drawer-meta {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
  font-size: 11px;
  color: var(--dim);
}

.avail-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok);
}

.drawer-body {
  display: grid;
  grid-template-rows: 0fr;
  opacity: 0;
  transition:
    grid-template-rows 0.25s var(--ease-out),
    opacity 0.2s ease;
}

.drawer.open .drawer-body {
  grid-template-rows: 1fr;
  opacity: 1;
}

.drawer-inner {
  overflow: hidden;
}

.group-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 9px;
  padding: 4px 20px 18px;
}

.faces {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 16px 18px 18px;
}

.face-btn {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 8px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.18s var(--ease-out),
    background-color 0.18s var(--ease-out),
    transform 0.18s var(--ease-out);
}

.face-btn:hover:not(:disabled) {
  border-color: var(--hair-strong);
  transform: translateY(-2px);
}

.face-btn.active {
  border-color: var(--ok-border);
  background: var(--ok-soft);
}

.face-btn.sending {
  border-color: var(--warn-border);
  background: var(--warn-soft);
}

.face-btn:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.face-name {
  padding: 0 2px;
  font-size: 12px;
  font-weight: 500;
  color: var(--dim);
}

.face-btn.active .face-name {
  color: var(--ink);
}

@media (max-width: 1080px) {
  .cols {
    grid-template-columns: 1fr;
  }

  .faces {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .group-grid,
  .faces {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

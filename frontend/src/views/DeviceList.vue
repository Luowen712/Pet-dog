<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { EditPen, Link, Refresh, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import FaceTile from '@/components/FaceTile.vue'
import HeartbeatWave from '@/components/HeartbeatWave.vue'
import RobotDog from '@/components/RobotDog.vue'
import StageParticles from '@/components/StageParticles.vue'
import { actionName } from '@/constants/actions'
import { faceName } from '@/constants/faces'
import type { BleDevice, Device } from '@/types'
import { describeDeviceStatus, formatRelative } from '@/utils/format'
import { emitParticleBurst } from '@/utils/theme'
import { useAuthStore } from '@/stores/auth'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'

const router = useRouter()
const auth = useAuthStore()
const deviceStore = useDeviceStore()
const pet = usePetStore()

const renameVisible = ref(false)
const renameValue = ref('')
const renameSaving = ref(false)
let renameTarget: Device | null = null

const selectedAddress = ref<string | null>(null)
const connecting = ref(false)
const blePanelOpen = ref(false)

const selectedBle = computed(
  () => deviceStore.bleDevices.find((item) => item.address === selectedAddress.value) ?? null,
)
const showBlePanel = computed(() => deviceStore.devices.length === 0 || blePanelOpen.value)

onMounted(async () => {
  if (auth.uid) deviceStore.bindUser(auth.uid)
  if (!deviceStore.loaded) await deviceStore.load()
  if (deviceStore.loaded && deviceStore.devices.length === 0) await deviceStore.scanBle()
})

watch(
  () => [deviceStore.loaded, deviceStore.devices.length] as const,
  ([loaded, count]) => {
    if (loaded && count === 0 && deviceStore.bleDevices.length === 0 && !deviceStore.scanning) {
      void deviceStore.scanBle()
    }
  },
)

function enter(device: Device): void {
  deviceStore.select(device.id)
  pet.connect(device.id)
  void router.push('/console')
}

function refresh(event?: MouseEvent): void {
  if (event && event.clientX > 0) emitParticleBurst(event.clientX, event.clientY, 'accent', 12)
  void deviceStore.load()
  if (showBlePanel.value) void deviceStore.scanBle()
}

async function openBleReconnect(): Promise<void> {
  blePanelOpen.value = true
  selectedAddress.value = null
  await deviceStore.scanBle()
}

async function scan(event?: MouseEvent): Promise<void> {
  if (event && event.clientX > 0) emitParticleBurst(event.clientX, event.clientY, 'oled', 16)
  if (auth.uid) deviceStore.bindUser(auth.uid)
  selectedAddress.value = null
  await deviceStore.scanBle()
}

async function connectSelected(event?: MouseEvent): Promise<void> {
  if (!selectedBle.value || connecting.value) return
  if (event && event.clientX > 0) emitParticleBurst(event.clientX, event.clientY, 'oled', 20)
  const wasBound = !!selectedBle.value.bound_to_me
  connecting.value = true
  try {
    const device = await deviceStore.connectBle(selectedBle.value.address, selectedBle.value.name)
    selectedAddress.value = null
    blePanelOpen.value = false
    ElMessage.success(wasBound ? `已重新连接「${device.name}」` : `已连接并绑定「${device.name}」`)
    pet.connect(device.id)
    await router.push('/console')
  } catch {
    // 错误提示由 request 层统一处理
  } finally {
    connecting.value = false
  }
}

function openRename(device: Device): void {
  renameTarget = device
  renameValue.value = device.name
  renameVisible.value = true
}

async function submitRename(): Promise<void> {
  const name = renameValue.value.trim()
  if (!name) {
    ElMessage.warning('名字不能为空')
    return
  }
  if (name.length > 64) {
    ElMessage.warning('名字不能超过 64 个字符')
    return
  }
  if (!renameTarget) return

  renameSaving.value = true
  try {
    await deviceStore.rename(renameTarget.id, name)
    ElMessage.success('名字已更新')
    renameVisible.value = false
  } catch {
    // 错误提示由 request 层统一弹出
  } finally {
    renameSaving.value = false
  }
}

async function unbind(device: Device): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '解绑不是急停：已经发出去的动作可能还会继续执行。解绑后将断开蓝牙连接，可重新扫描低功耗蓝牙绑定。',
      `解绑「${device.name}」`,
      {
        type: 'warning',
        confirmButtonText: '仍然解绑',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  try {
    await deviceStore.unbind(device.id)
    pet.reset()
    ElMessage.success('设备已解绑')
  } catch {
    // 错误提示由 request 层统一处理
  }
}

function isCurrentConnected(device: Device): boolean {
  return device.id === deviceStore.currentId && pet.connected
}

function deviceStatusView(device: Device) {
  const live = isCurrentConnected(device)
  return describeDeviceStatus({
    online: live ? pet.online : device.online,
    controlState: live ? pet.controlState : device.control_state,
  })
}

function isDeviceOnline(device: Device): boolean {
  return isCurrentConnected(device) ? pet.online : device.online
}

function isDeviceBusy(device: Device): boolean {
  const state = isCurrentConnected(device) ? pet.controlState : device.control_state
  return state === 'busy'
}

function liveBattery(device: Device): number | null {
  return isCurrentConnected(device) && pet.battery !== null ? pet.battery : device.battery
}

function liveVoltage(device: Device): number | null {
  return isCurrentConnected(device) ? pet.voltage : null
}

function liveFace(device: Device): number {
  return isCurrentConnected(device) && pet.face !== null ? pet.face : 5
}

function liveAction(device: Device): number | null {
  return isCurrentConnected(device) ? pet.action : null
}

function batteryLitCount(batt: number | null): number {
  if (batt === null) return 0
  return Math.max(0, Math.min(10, Math.round(batt / 10)))
}

function batteryTone(batt: number | null): string {
  if (batt === null) return ''
  if (batt > 50) return 'ok'
  if (batt > 20) return 'warn'
  return 'bad'
}

function voltagePercent(volt: number | null): number {
  if (volt === null) return 0
  // 适配单节 3.3–4.2V 或双节 6.4–8.4V 常见锂电范围
  const [min, max] = volt > 5 ? [6.4, 8.4] : [3.3, 4.2]
  return Math.max(6, Math.min(100, ((volt - min) / (max - min)) * 100))
}

function rssiBars(rssi: number | null): number {
  if (rssi === null) return 2
  if (rssi > -55) return 4
  if (rssi > -68) return 3
  if (rssi > -80) return 2
  return 1
}

function blipPosition(item: BleDevice, index: number): { left: string; top: string } {
  const total = Math.max(1, deviceStore.bleDevices.length)
  const angle = (index / total) * Math.PI * 2 - Math.PI / 3
  const strength = item.rssi !== null ? Math.max(0, Math.min(1, (-item.rssi - 35) / 55)) : 0.55
  const radius = 18 + strength * 24
  return {
    left: `${(50 + Math.cos(angle) * radius).toFixed(1)}%`,
    top: `${(50 + Math.sin(angle) * radius).toFixed(1)}%`,
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="page-title">我的设备</h2>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="deviceStore.loading" @click="refresh($event)">
          刷新
        </el-button>
      </div>
    </div>

    <el-skeleton v-if="deviceStore.loading && !deviceStore.loaded" :rows="5" animated />

    <template v-else>
      <div v-if="deviceStore.devices.length > 0" class="stage-list">
        <article
          v-for="device in deviceStore.devices"
          :key="device.id"
          class="hero-grid"
          :class="{ offline: !isDeviceOnline(device) }"
        >
          <!-- 左侧：实时桌宠互动舞台 -->
          <section class="card pet-stage">
            <div class="stage-viewport">
              <StageParticles :online="isDeviceOnline(device)" :busy="isDeviceBusy(device)" />
              <div class="dog-slot">
                <RobotDog
                  :face="liveFace(device)"
                  :online="isDeviceOnline(device)"
                  class="stage-dog"
                />
              </div>
            </div>

            <div class="stage-footer">
              <div class="name-main">
                <div class="name-head">
                  <h3 class="name" :title="device.name">{{ device.name }}</h3>
                  <button
                    type="button"
                    class="rename"
                    title="修改桌宠名字"
                    @click="openRename(device)"
                  >
                    <el-icon><EditPen /></el-icon>
                  </button>
                </div>
                <span class="status" :class="deviceStatusView(device).tone">
                  {{ deviceStatusView(device).label }}
                </span>
              </div>

              <el-button class="enter" type="primary" @click="enter(device)">
                进入控制台 <span class="arrow mono">↗</span>
              </el-button>
            </div>
          </section>

          <!-- 右侧：真实硬件遥测与蓝牙控制 -->
          <div class="telemetry-col">
            <div class="metrics-grid">
              <div class="card metric-card">
                <span class="metric-label">电量</span>
                <div class="metric-value mono">
                  {{ liveBattery(device) === null ? '—' : liveBattery(device) }}
                  <small v-if="liveBattery(device) !== null">%</small>
                </div>
                <div class="energy-segs" aria-hidden="true">
                  <span
                    v-for="idx in 10"
                    :key="idx"
                    class="energy-seg"
                    :class="[
                      idx <= batteryLitCount(liveBattery(device))
                        ? ['lit', batteryTone(liveBattery(device))]
                        : '',
                    ]"
                  />
                </div>
              </div>

              <div class="card metric-card">
                <span class="metric-label">电压</span>
                <div class="metric-value mono">
                  {{ liveVoltage(device) === null ? '—' : liveVoltage(device)!.toFixed(2) }}
                  <small v-if="liveVoltage(device) !== null">V</small>
                </div>
                <div class="volt-track" aria-hidden="true">
                  <div
                    class="volt-fill"
                    :style="{ width: `${voltagePercent(liveVoltage(device))}%` }"
                  />
                </div>
              </div>

              <div class="card metric-card">
                <span class="metric-label">固件</span>
                <div class="metric-value mono fw-val">{{ device.firmware || '—' }}</div>
              </div>

              <div class="card metric-card">
                <div class="metric-top">
                  <span class="metric-label">最近心跳</span>
                  <span class="hb-time">
                    {{ formatRelative(device.last_heartbeat ?? undefined) }}
                  </span>
                </div>
                <HeartbeatWave :online="isDeviceOnline(device)" />
              </div>
            </div>

            <div class="card mirror-card">
              <div class="mirror-oled">
                <FaceTile :face="liveFace(device)" />
              </div>
              <div class="mirror-rows">
                <div class="mirror-row">
                  <span>当前表情</span>
                  <strong>{{ faceName(liveFace(device)) }}</strong>
                </div>
                <div class="mirror-row">
                  <span>当前动作</span>
                  <strong>
                    {{ liveAction(device) === null ? '—' : actionName(liveAction(device)!) }}
                  </strong>
                </div>
              </div>
            </div>

            <div class="card link-bar">
              <div class="link-actions">
                <el-button :icon="Link" @click="openBleReconnect">重连蓝牙</el-button>
                <el-button class="unbind" :icon="SwitchButton" @click="unbind(device)">
                  解绑
                </el-button>
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- 低功耗蓝牙扫描雷达面板 -->
      <section v-if="showBlePanel" class="card ble-panel">
        <div class="ble-radar-col" :class="{ scanning: deviceStore.scanning }">
          <div class="radar-disc" aria-hidden="true">
            <span class="radar-cross-h" />
            <span class="radar-cross-v" />
            <div class="radar-sweep" />
            <div class="radar-center" />
            <button
              v-for="(item, idx) in deviceStore.bleDevices"
              :key="item.address"
              type="button"
              class="radar-blip"
              :class="{ selected: selectedAddress === item.address }"
              :style="blipPosition(item, idx)"
              :title="item.name"
              @click="selectedAddress = item.address"
            />
          </div>
        </div>

        <div class="ble-main">
          <div class="claim-head">
            <div>
              <span class="claim-kicker mono">BLE / ECB02H2</span>
              <h3>{{ deviceStore.devices.length === 0 ? '连接蓝牙桌宠' : '扫描并重连低功耗蓝牙' }}</h3>
            </div>
            <el-button v-if="deviceStore.devices.length > 0" size="small" @click="blePanelOpen = false">
              收起
            </el-button>
          </div>

          <div v-if="deviceStore.bleDevices.length > 0" class="claimable-list">
            <button
              v-for="item in deviceStore.bleDevices"
              :key="item.address"
              type="button"
              class="claimable"
              :class="{ active: selectedAddress === item.address }"
              @click="selectedAddress = item.address"
            >
              <div class="claimable-top">
                <span class="claimable-name">{{ item.name }}</span>
                <span class="rssi-bars" aria-hidden="true">
                  <span
                    v-for="(barH, bIdx) in [5, 8, 10, 13]"
                    :key="barH"
                    class="rssi-bar"
                    :class="{ lit: bIdx < rssiBars(item.rssi) }"
                    :style="{ height: `${barH}px` }"
                  />
                </span>
              </div>
              <span class="mono device-id">
                {{ item.address }}
                <template v-if="item.rssi !== null"> · {{ item.rssi }} dBm</template>
                <template v-if="item.bound_to_me"> · 已绑定</template>
              </span>
            </button>
          </div>
          <EmptyState
            v-else
            title="暂未发现可用蓝牙设备"
            hint="确认桌宠已通电后重新扫描"
          />

          <div class="claim-form">
            <el-button :icon="Refresh" :loading="deviceStore.scanning" @click="scan($event)">
              扫描蓝牙
            </el-button>
            <el-button
              type="primary"
              :disabled="!selectedBle"
              :loading="connecting"
              @click="connectSelected($event)"
            >
              {{ selectedBle?.bound_to_me ? '重新连接蓝牙' : '直接连接并绑定' }}
            </el-button>
          </div>
        </div>
      </section>
    </template>

    <el-dialog v-model="renameVisible" title="修改桌宠名字" width="360px">
      <el-input
        v-model="renameValue"
        maxlength="64"
        show-word-limit
        placeholder="给桌宠起个名字"
        autofocus
        @keyup.enter="submitRename"
      />
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" :loading="renameSaving" @click="submitRename">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stage-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.22fr) minmax(330px, 0.98fr);
  gap: 18px;
  align-items: stretch;
}

.pet-stage {
  display: flex;
  flex-direction: column;
  min-height: 440px;
}

.stage-viewport {
  position: relative;
  flex: 1;
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 28px 18px;
  background: var(--bg-stage);
  overflow: hidden;
}

.dog-slot {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 390px;
  display: flex;
  justify-content: center;
}

.stage-dog {
  width: 100%;
}

.stage-footer {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 18px 22px;
  border-top: 1px solid var(--hair-soft);
}

.name-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.name-head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.name {
  overflow: hidden;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hero-grid.offline .name {
  color: var(--dim);
}

.rename {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--hair);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--dim);
  cursor: pointer;
  flex-shrink: 0;
  transition:
    color 0.16s ease,
    border-color 0.16s ease,
    background-color 0.16s ease;
}

.rename:hover {
  border-color: var(--hair-strong);
  background: var(--surface-3);
  color: var(--ink);
}

.enter {
  height: 38px;
  padding: 0 18px;
  background: var(--grad-line);
  border-color: transparent;
  color: #101214;
  font-weight: 600;
}

.enter:hover {
  background: var(--grad-line);
  border-color: transparent;
  color: #101214;
  filter: brightness(1.06);
}

.arrow {
  margin-left: 4px;
}

/* 右侧遥测列 */
.telemetry-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
  min-height: 112px;
  padding: 16px 18px;
}

.metric-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.metric-label {
  font-size: 12px;
  color: var(--dim);
}

.hb-time {
  font-size: 12px;
  font-weight: 500;
  color: var(--ink-2);
  white-space: nowrap;
}

.metric-value {
  font-size: 25px;
  font-weight: 600;
  line-height: 1.05;
  letter-spacing: -0.03em;
  color: var(--ink);
}

.metric-value small {
  font-size: 12px;
  font-weight: 400;
  color: var(--dim);
  margin-left: 3px;
}

.fw-val {
  font-size: 21px;
}

.energy-segs {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 4px;
  height: 7px;
}

.energy-seg {
  border-radius: 2px;
  background: var(--hair);
  transition: background-color 0.25s ease;
}

.energy-seg.lit.ok {
  background: var(--ok);
}

.energy-seg.lit.warn {
  background: var(--warn);
}

.energy-seg.lit.bad {
  background: var(--danger);
}

.volt-track {
  height: 6px;
  border-radius: var(--radius-pill);
  background: var(--hair);
  overflow: hidden;
}

.volt-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--grad-line);
  transition: width 0.45s var(--ease-out);
}

.mirror-card {
  display: grid;
  grid-template-columns: 148px minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  padding: 15px 18px;
}

.mirror-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.mirror-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--hair-soft);
}

.mirror-row:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.mirror-row span {
  color: var(--dim);
}

.mirror-row strong {
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}

.link-bar {
  padding: 14px 18px;
}

.link-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.unbind:hover {
  border-color: var(--danger-border);
  background: var(--danger-soft);
  color: var(--danger);
}

/* 蓝牙扫描雷达面板 */
.ble-panel {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
}

.ble-radar-col {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 20px;
  border-right: 1px solid var(--hair-soft);
  background: var(--surface-2);
}

.radar-disc {
  position: relative;
  width: 170px;
  height: 170px;
  border-radius: 50%;
  border: 1px solid var(--hair-strong);
  background:
    radial-gradient(circle, var(--accent-soft) 0%, transparent 66%),
    repeating-radial-gradient(circle, transparent 0 27px, var(--hair-soft) 27px 28px);
  overflow: hidden;
}

.radar-cross-h,
.radar-cross-v {
  position: absolute;
  background: var(--hair-soft);
}

.radar-cross-h {
  left: 0;
  right: 0;
  top: 50%;
  height: 1px;
}

.radar-cross-v {
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
}

.radar-sweep {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 276deg, var(--accent-1) 360deg);
  opacity: 0.24;
  animation: radarSpin 5.5s linear infinite;
}

.ble-radar-col.scanning .radar-sweep {
  opacity: 0.42;
  animation-duration: 1.8s;
}

@keyframes radarSpin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.radar-center {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 8px;
  height: 8px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: var(--accent-1);
}

.radar-blip {
  position: absolute;
  width: 10px;
  height: 10px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: var(--oled-glow);
  transform: translate(-50%, -50%);
  cursor: pointer;
}

.radar-blip::after {
  content: '';
  position: absolute;
  inset: -5px;
  border-radius: 50%;
  border: 1px solid var(--oled-glow);
  animation: blipRing 2.1s ease-out infinite;
}

.radar-blip.selected {
  background: var(--accent-2);
  transform: translate(-50%, -50%) scale(1.25);
}

.radar-blip.selected::after {
  border-color: var(--accent-2);
}

@keyframes blipRing {
  0% {
    transform: scale(0.7);
    opacity: 0.85;
  }
  100% {
    transform: scale(2.1);
    opacity: 0;
  }
}

.ble-main {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
}

.claim-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.claim-kicker {
  font-size: 10px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.claim-head h3 {
  margin-top: 6px;
  font-size: 18px;
  font-weight: 600;
}

.claimable-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.claimable {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 13px 14px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease,
    transform 0.18s ease;
}

.claimable:hover {
  border-color: var(--hair-strong);
  transform: translateY(-1px);
}

.claimable.active {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}

.claimable-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.claimable-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.device-id {
  font-size: 10.5px;
  letter-spacing: 0.05em;
  color: var(--dim);
}

.rssi-bars {
  display: inline-flex;
  align-items: flex-end;
  gap: 2.5px;
  height: 13px;
}

.rssi-bar {
  width: 3px;
  border-radius: 1px;
  background: var(--hair-strong);
}

.rssi-bar.lit {
  background: var(--ok);
}

.claim-form {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

@media (max-width: 1080px) {
  .hero-grid,
  .ble-panel {
    grid-template-columns: 1fr;
  }

  .ble-radar-col {
    border-right: 0;
    border-bottom: 1px solid var(--hair-soft);
  }
}

@media (max-width: 680px) {
  .metrics-grid,
  .mirror-card {
    grid-template-columns: 1fr;
  }

  .stage-footer {
    padding: 14px 16px;
  }
}
</style>

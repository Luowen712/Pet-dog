<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { EditPen, Link, Refresh, SwitchButton } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import PetCharm from '@/components/PetCharm.vue'
import type { Device } from '@/types'
import { formatDateTime, formatRelative } from '@/utils/format'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'

const router = useRouter()
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
  if (!deviceStore.loaded) await deviceStore.load()
  if (deviceStore.devices.length === 0) await deviceStore.scanBle()
})

function enter(device: Device): void {
  deviceStore.select(device.id)
  pet.connect(device.id)
  void router.push('/console')
}

function refresh(): void {
  void deviceStore.load()
  if (showBlePanel.value) void deviceStore.scanBle()
}

async function openBleReconnect(): Promise<void> {
  blePanelOpen.value = true
  selectedAddress.value = null
  await deviceStore.scanBle()
}

async function scan(): Promise<void> {
  selectedAddress.value = null
  await deviceStore.scanBle()
}

async function connectSelected(): Promise<void> {
  if (!selectedBle.value || connecting.value) return
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

function stateText(device: Device): string {
  const state = device.control_state
  if (state === 'faulted') return 'Faulted'
  if (state === 'handover_required') return 'Handover'
  if (!device.online) return 'Offline'
  const map: Record<string, string> = {
    ready: 'Ready',
    busy: 'Busy',
    handover_required: 'Handover',
    recovery_required: 'Recovery',
    faulted: 'Faulted',
    unconfigured: 'Unconfigured',
    offline: 'Offline',
  }
  return (state && map[state]) || state || 'Online'
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="page-kicker">02 / Devices</div>
        <h2 class="page-title">我的设备</h2>
        <p class="page-sub">每个账号只看得到自己的设备</p>
      </div>
      <el-button class="ghost" :icon="Refresh" :loading="deviceStore.loading" @click="refresh">
        刷新
      </el-button>
    </div>

    <el-skeleton v-if="deviceStore.loading && !deviceStore.loaded" :rows="4" animated />

    <template v-else>
      <section v-if="showBlePanel" class="card claim">
        <div class="claim-head">
          <div>
            <span class="claim-kicker mono">BLE / ECB02H2</span>
            <h3>{{ deviceStore.devices.length === 0 ? '连接低功耗蓝牙桌宠' : '扫描并重连低功耗蓝牙' }}</h3>
            <p>扫描附近的低功耗蓝牙设备（ECB02H2），点选后直接建立连接并绑定到当前账号，无需配对码。</p>
          </div>
          <el-icon class="claim-icon"><Link /></el-icon>
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
            <span class="mono device-id">
              {{ item.transport.toUpperCase() }} · {{ item.address }}
              <template v-if="item.rssi !== null"> · {{ item.rssi }} dBm</template>
              <template v-if="item.bound_to_me"> · 已绑定</template>
            </span>
            <span class="claimable-name">{{ item.name }}</span>
            <span class="claimable-dot" />
          </button>
        </div>
        <EmptyState
          v-else
          title="暂未发现可用蓝牙设备"
          hint="请确认桌宠已通电且 ECB02H2 处于可被扫描状态，点击下方按钮重新扫描"
        />

        <div class="claim-form">
          <el-button class="ghost" :icon="Refresh" :loading="deviceStore.scanning" @click="scan">
            扫描蓝牙
          </el-button>
          <el-button
            type="primary"
            :disabled="!selectedBle"
            :loading="connecting"
            @click="connectSelected"
          >
            {{ selectedBle?.bound_to_me ? '重新连接蓝牙' : '直接连接并绑定' }}
          </el-button>
          <el-button v-if="deviceStore.devices.length > 0" @click="blePanelOpen = false">
            收起
          </el-button>
        </div>
        <p v-if="!selectedBle" class="claim-hint">先从上方扫描结果点选一台蓝牙设备，再点击连接。</p>
      </section>

      <div v-if="deviceStore.devices.length > 0" class="grid">
        <article
          v-for="(device, index) in deviceStore.devices"
          :key="device.id"
          class="device card"
          :class="{ offline: !device.online }"
        >
          <div class="top">
            <span class="index mono">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="status" :class="device.online ? 'ok' : ''">{{ stateText(device) }}</span>
          </div>

          <div class="name-row">
            <h3 class="name" :title="device.name">{{ device.name }}</h3>
            <PetCharm class="charm" :online="device.online" />
            <button type="button" class="rename" title="修改桌宠名字" @click="openRename(device)">
              <el-icon><EditPen /></el-icon>
            </button>
          </div>

          <div class="meta">
            <div class="meta-cell">
              <span class="meta-label mono">Firmware</span>
              <span class="meta-value mono">{{ device.firmware || '—' }}</span>
            </div>
            <div class="meta-cell">
              <span class="meta-label mono">Battery</span>
              <span class="meta-value mono">
                {{ device.battery === null ? '—' : `${device.battery}%` }}
              </span>
            </div>
            <div class="meta-cell">
              <span class="meta-label mono">Control</span>
              <span class="meta-value mono">{{ device.control_state }}</span>
            </div>
            <div class="meta-cell">
              <span class="meta-label mono">Heartbeat</span>
              <span class="meta-value">{{ formatRelative(device.last_heartbeat ?? undefined) }}</span>
            </div>
          </div>

          <div class="foot">
            <span class="heart mono">{{ formatDateTime(device.last_heartbeat ?? undefined) }}</span>
            <div class="foot-actions">
              <el-button class="ghost" :icon="Link" @click="openBleReconnect">重连蓝牙</el-button>
              <el-button class="unbind" :icon="SwitchButton" @click="unbind(device)">解绑</el-button>
              <el-button class="enter" @click="enter(device)">
                进入控制台 <span class="arrow">↗</span>
              </el-button>
            </div>
          </div>
        </article>
      </div>
    </template>

    <el-dialog v-model="renameVisible" title="修改桌宠名字" width="380px">
      <div class="rename-body">
        <span class="field-label mono">Pet name</span>
        <el-input
          v-model="renameValue"
          maxlength="64"
          show-word-limit
          placeholder="给桌宠起个名字"
          autofocus
          @keyup.enter="submitRename"
        />
        <p class="rename-hint">1–64 个字符，保存后同步到设备列表。</p>
      </div>
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" :loading="renameSaving" @click="submitRename">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ghost {
  border-color: var(--hair);
  background: transparent;
  color: var(--ink);
}

.ghost:hover {
  border-color: var(--ink);
  background: transparent;
  color: var(--ink);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(460px, 1fr));
  gap: 14px;
}

.device {
  display: flex;
  flex-direction: column;
  padding: 16px 18px 14px;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.device:hover {
  border-color: rgba(20, 20, 20, 0.36);
}

.device.offline {
  background: rgba(247, 244, 238, 0.6);
}

.device.offline .name {
  color: var(--dim);
}

.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.index {
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--faint);
}

.name-row {
  display: flex;
  align-items: flex-start;
  min-height: 64px;
  margin: 4px 0 8px;
}

.name {
  max-width: calc(100% - 114px);
  padding-top: 9px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.charm {
  margin: -6px 0 0 8px;
}

.rename {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin: 8px 0 0 3px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--faint);
  opacity: 0.6;
  cursor: pointer;
  transition:
    opacity 0.16s ease,
    color 0.16s ease,
    border-color 0.16s ease;
}

.device:hover .rename {
  opacity: 1;
}

.rename:hover {
  border-color: var(--hair);
  color: var(--ink);
}

.meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--hair-soft);
  border: 1px solid var(--hair-soft);
}

.meta-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 11px;
  background: var(--panel);
}

.meta-label {
  font-size: 8px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--faint);
}

.meta-value {
  font-size: 12.5px;
  font-weight: 500;
}

.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--hair-soft);
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.heart {
  font-size: 8.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.enter {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--ink);
  background: transparent;
  color: var(--ink);
  font-size: 12px;
  letter-spacing: 0.03em;
}

.enter:hover {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}

.unbind {
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--hair);
  background: transparent;
  color: var(--dim);
  font-size: 12px;
}

.unbind:hover {
  border-color: var(--danger);
  color: var(--danger);
}

.arrow {
  font-family: var(--mono);
  margin-left: 4px;
}

.claim {
  padding: 22px;
}

.claim-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.claim-kicker {
  font-size: 9px;
  letter-spacing: 0.16em;
  color: var(--faint);
}

.claim-head h3 {
  margin: 8px 0 6px;
  font-size: 20px;
  font-weight: 500;
}

.claim-head p {
  max-width: 560px;
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--dim);
}

.claim-icon {
  font-size: 26px;
  color: var(--faint);
}

.claimable-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
  margin-top: 20px;
}

.claimable {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--hair);
  border-radius: var(--radius);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.claimable.active {
  border-color: var(--ink);
  background: rgba(255, 255, 255, 0.5);
}

.device-id {
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.claimable-name {
  font-size: 13px;
  font-weight: 500;
}

.claimable-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(20, 20, 20, 0.18);
}

.claimable.active .claimable-dot {
  background: var(--ok);
}

.claim-form {
  display: flex;
  gap: 10px;
  margin-top: 18px;
  max-width: 420px;
}

.claim-hint {
  margin: 10px 0 0;
  font-size: 11px;
  color: var(--faint);
}

.rename-body {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.field-label {
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.rename-hint {
  font-size: 11px;
  color: var(--faint);
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>

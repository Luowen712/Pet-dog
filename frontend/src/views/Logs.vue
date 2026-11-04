<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import type { CommandLog, CommandState } from '@/types'
import { listLogs } from '@/api/log'
import { actionHex } from '@/constants/actions'
import { useDeviceStore } from '@/stores/device'
import { formatCost, formatDateTime } from '@/utils/format'

const deviceStore = useDeviceStore()

const loading = ref(false)
const rows = ref<CommandLog[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const status = ref('ALL')
const deviceId = ref<number | 'ALL'>('ALL')

const STATUS_OPTIONS = [
  { value: 'ALL', label: '全部状态' },
  { value: 'OK', label: '成功' },
  { value: 'TIMEOUT', label: '超时' },
  { value: 'ERROR', label: '错误' },
  { value: 'PENDING', label: '等待中' },
]

const STATUS_TEXT: Record<CommandState, string> = {
  OK: '成功',
  TIMEOUT: '超时',
  ERROR: '错误',
  PENDING: '等待中',
}

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function statusClass(value: CommandState): string {
  if (value === 'OK') return 'ok'
  if (value === 'TIMEOUT') return 'warn'
  if (value === 'ERROR') return 'bad'
  return ''
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const result = await listLogs({
      page: page.value,
      size: size.value,
      status: status.value === 'ALL' ? undefined : status.value,
      device_id: deviceId.value === 'ALL' ? undefined : deviceId.value,
    })
    rows.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function onFilter(): void {
  page.value = 1
  void load()
}

function onSizeChange(): void {
  page.value = 1
  void load()
}

onMounted(() => {
  if (!deviceStore.loaded) void deviceStore.load()
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="page-kicker">04 / Logs</div>
        <h2 class="page-title">指令日志</h2>
        <p class="page-sub">每条动作从发出到应答都落库，共 {{ total }} 条记录</p>
      </div>
      <el-button class="ghost" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </div>

    <section class="card">
      <div class="filters">
        <label class="filter">
          <span class="filter-label mono">Device</span>
          <el-select v-model="deviceId" class="filter-select" @change="onFilter">
            <el-option label="全部设备" value="ALL" />
            <el-option
              v-for="device in deviceStore.devices"
              :key="device.id"
              :label="device.name"
              :value="device.id"
            />
          </el-select>
        </label>

        <label class="filter">
          <span class="filter-label mono">Status</span>
          <el-select v-model="status" class="filter-select" @change="onFilter">
            <el-option
              v-for="option in STATUS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </label>

        <span class="filters-note mono">Filters apply live</span>
      </div>

      <el-table v-loading="loading" :data="rows" class="table" row-key="id">
        <el-table-column label="时间" width="172">
          <template #default="{ row }">
            <span class="mono time">{{ formatDateTime(row.time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="动作" min-width="120">
          <template #default="{ row }">{{ row.action_name }}</template>
        </el-table-column>
        <el-table-column label="动作码" width="88">
          <template #default="{ row }">
            <span class="mono faint">{{ actionHex(row.action) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="seq" width="70">
          <template #default="{ row }">
            <span class="mono">{{ row.seq }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <span class="status" :class="statusClass(row.status)">
              {{ STATUS_TEXT[row.status as CommandState] }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="96">
          <template #default="{ row }">
            <span class="mono">{{ formatCost(row.cost_ms) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="应答结果" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="response">{{ row.response }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <span class="pager-note mono">Page {{ page }} / {{ totalPages }}</span>
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          background
          layout="total, sizes, prev, pager, next"
          :page-sizes="[10, 20, 50]"
          :total="total"
          @current-change="load"
          @size-change="onSizeChange"
        />
      </div>
    </section>
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

.filters {
  display: flex;
  align-items: flex-end;
  gap: 22px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--hair);
  flex-wrap: wrap;
}

.filter {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.filter-label {
  font-size: 8px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--faint);
}

.filter-select {
  width: 170px;
}

.filters-note {
  margin-left: auto;
  padding-bottom: 6px;
  font-size: 8px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--faint);
}

.table {
  width: 100%;
}

.time {
  font-size: 11.5px;
  letter-spacing: 0.02em;
}

.response {
  color: var(--dim);
  font-size: 12px;
}

.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
}

.pager-note {
  font-size: 8.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--faint);
}

@media (max-width: 760px) {
  .filters-note {
    display: none;
  }

  .filter-select {
    width: 140px;
  }

  .pager {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>

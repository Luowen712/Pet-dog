<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { CommandLog, TelemetryPoint } from '@/types'
import { listLogs } from '@/api/log'
import { listTelemetry } from '@/api/telemetry'
import { useDeviceStore } from '@/stores/device'
import { formatCost, formatShortTime } from '@/utils/format'

const deviceStore = useDeviceStore()

const loading = ref(true)
const points = ref<TelemetryPoint[]>([])
const logs = ref<CommandLog[]>([])
const totalLogs = ref(0)

const batteryEl = ref<HTMLDivElement>()
const donutEl = ref<HTMLDivElement>()
const barEl = ref<HTMLDivElement>()

let batteryChart: echarts.ECharts | null = null
let donutChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null

const axisColor = 'rgba(20,20,20,.42)'
const hairColor = 'rgba(20,20,20,.08)'
const mono = "'IBM Plex Mono', monospace"

const okCount = computed(() => logs.value.filter((log) => log.status === 'OK').length)
const timeoutCount = computed(() => logs.value.filter((log) => log.status === 'TIMEOUT').length)
const errorCount = computed(() => logs.value.filter((log) => log.status === 'ERROR').length)
const successRate = computed(() => {
  if (logs.value.length === 0) return 0
  return Math.round((okCount.value / logs.value.length) * 1000) / 10
})
const avgCost = computed(() => {
  const measured = logs.value.filter((log) => log.status !== 'PENDING')
  if (measured.length === 0) return 0
  return Math.round(measured.reduce((sum, log) => sum + log.cost_ms, 0) / measured.length)
})

const tooltip = {
  backgroundColor: '#f7f4ee',
  borderColor: 'rgba(20,20,20,.16)',
  borderWidth: 1,
  padding: [8, 11],
  textStyle: { color: '#141414', fontSize: 10.5, fontFamily: mono },
  extraCssText: 'box-shadow: 0 10px 30px rgba(20,20,20,.10); border-radius: 2px;',
}

function renderBattery(): void {
  if (!batteryEl.value) return
  batteryChart = batteryChart ?? echarts.init(batteryEl.value)
  const option: EChartsOption = {
    grid: { left: 48, right: 22, top: 28, bottom: 34 },
    tooltip: { ...tooltip, trigger: 'axis', valueFormatter: (value) => `${value}%` },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.value.map((point) => formatShortTime(point.time)),
      axisLine: { lineStyle: { color: hairColor } },
      axisTick: { show: false },
      axisLabel: { color: axisColor, fontSize: 9, fontFamily: mono, margin: 12 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { lineStyle: { color: hairColor } },
      axisLabel: { color: axisColor, fontSize: 9, fontFamily: mono, formatter: '{value}' },
    },
    series: [
      {
        name: 'Battery',
        type: 'line',
        smooth: true,
        symbol: 'none',
        data: points.value.map((point) => point.battery),
        lineStyle: {
          width: 2,
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#ffb347' },
            { offset: 0.5, color: '#ff5a5f' },
            { offset: 1, color: '#ff3d8b' },
          ]),
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(255,90,95,0.11)' },
            { offset: 1, color: 'rgba(255,90,95,0)' },
          ]),
        },
      },
    ],
  }
  batteryChart.setOption(option)
}

function renderDonut(): void {
  if (!donutEl.value) return
  donutChart = donutChart ?? echarts.init(donutEl.value)
  const option: EChartsOption = {
    tooltip: { ...tooltip, trigger: 'item' },
    legend: {
      bottom: 4,
      icon: 'rect',
      itemWidth: 7,
      itemHeight: 7,
      itemGap: 18,
      textStyle: { color: 'rgba(20,20,20,.5)', fontSize: 9, fontFamily: mono },
    },
    series: [
      {
        type: 'pie',
        radius: ['58%', '76%'],
        center: ['50%', '43%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#f7f4ee', borderWidth: 3 },
        label: { show: false },
        data: [
          { value: okCount.value, name: '成功', itemStyle: { color: '#141414' } },
          { value: timeoutCount.value, name: '超时', itemStyle: { color: '#c98a2e' } },
          { value: errorCount.value, name: '错误', itemStyle: { color: '#a53a33' } },
        ],
      },
    ],
  }
  donutChart.setOption(option)
}

function renderBar(): void {
  if (!barEl.value) return
  barChart = barChart ?? echarts.init(barEl.value)
  const counts = new Map<string, number>()
  logs.value.forEach((log) => {
    counts.set(log.action_name, (counts.get(log.action_name) ?? 0) + 1)
  })
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).reverse()
  const option: EChartsOption = {
    grid: { left: 76, right: 26, top: 16, bottom: 26 },
    tooltip: { ...tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: hairColor } },
      axisLabel: { color: axisColor, fontSize: 9, fontFamily: mono },
    },
    yAxis: {
      type: 'category',
      data: sorted.map(([name]) => name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: 'rgba(20,20,20,.62)', fontSize: 10, fontFamily: mono },
    },
    series: [
      {
        type: 'bar',
        data: sorted.map(([, value]) => value),
        barWidth: 10,
        itemStyle: {
          borderRadius: [0, 2, 2, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: '#ffb347' },
            { offset: 0.55, color: '#ff5a5f' },
            { offset: 1, color: '#ff3d8b' },
          ]),
        },
      },
    ],
  }
  barChart.setOption(option)
}

function renderAll(): void {
  renderBattery()
  renderDonut()
  renderBar()
}

function onResize(): void {
  batteryChart?.resize()
  donutChart?.resize()
  barChart?.resize()
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [telemetry, logPage] = await Promise.all([
      listTelemetry(),
      listLogs({ page: 1, size: 200 }),
    ])
    points.value = telemetry
    logs.value = logPage.items
    totalLogs.value = logPage.total
    await nextTick()
    renderAll()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!deviceStore.loaded) void deviceStore.load()
  await load()
  // 等字体加载完再画一次，避免坐标轴先渲染成 fallback 字体
  if (document.fonts) {
    await document.fonts.ready
    renderAll()
  }
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  batteryChart?.dispose()
  donutChart?.dispose()
  barChart?.dispose()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="page-kicker">05 / Analytics</div>
        <h2 class="page-title">数据看板</h2>
        <p class="page-sub">最近 24 小时的电量、指令成功率与动作分布</p>
      </div>
      <el-button class="ghost" :loading="loading" @click="load">刷新数据</el-button>
    </div>

    <section class="stats">
      <div class="stat">
        <span class="stat-label mono">Total commands</span>
        <span class="stat-value mono">{{ totalLogs }}</span>
        <span class="stat-sub mono">All history</span>
      </div>
      <div class="stat">
        <span class="stat-label mono">Success rate</span>
        <span class="stat-value mono">{{ successRate }}<i>%</i></span>
        <span class="stat-sub mono">Last {{ logs.length }}</span>
      </div>
      <div class="stat">
        <span class="stat-label mono">Avg latency</span>
        <span class="stat-value mono">{{ formatCost(avgCost) }}</span>
        <span class="stat-sub mono">Includes timeouts</span>
      </div>
      <div class="stat">
        <span class="stat-label mono">Devices online</span>
        <span class="stat-value mono">{{ deviceStore.onlineCount }}<i>/{{ deviceStore.devices.length }}</i></span>
        <span class="stat-sub mono">Heartbeat &lt; 30s</span>
      </div>
    </section>

    <section class="card chart-card" v-loading="loading">
      <div class="card-head">
        <span class="card-title">电量曲线</span>
        <span class="card-meta">24h · one sample per hour</span>
      </div>
      <div ref="batteryEl" class="chart chart-lg" />
    </section>

    <div class="two">
      <section class="card chart-card" v-loading="loading">
        <div class="card-head">
          <span class="card-title">指令成功率</span>
          <span class="card-meta">ok / timeout / error</span>
        </div>
        <div ref="donutEl" class="chart chart-md" />
      </section>

      <section class="card chart-card" v-loading="loading">
        <div class="card-head">
          <span class="card-title">动作分布</span>
          <span class="card-meta">top 8 actions</span>
        </div>
        <div ref="barEl" class="chart chart-md" />
      </section>
    </div>
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

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  background: var(--panel);
  border: 1px solid var(--hair);
  border-radius: var(--radius);
  overflow: hidden;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 16px 20px 17px;
  border-left: 1px solid var(--hair-soft);
}

.stat:first-child {
  border-left: 0;
}

.stat-label {
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.stat-value {
  font-size: 28px;
  font-weight: 300;
  line-height: 1.1;
  letter-spacing: -0.02em;
}

.stat-value i {
  font-style: normal;
  font-size: 12px;
  color: var(--faint);
  margin-left: 2px;
}

.stat-sub {
  font-size: 8px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--faint);
}

.chart {
  width: 100%;
}

.chart-lg {
  height: 320px;
}

.chart-md {
  height: 280px;
}

.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 1000px) {
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stat:nth-child(3) {
    border-left: 0;
    border-top: 1px solid var(--hair-soft);
  }

  .stat:nth-child(4) {
    border-top: 1px solid var(--hair-soft);
  }

  .two {
    grid-template-columns: 1fr;
  }
}
</style>

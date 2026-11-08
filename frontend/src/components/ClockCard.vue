<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import WeatherIcon from './WeatherIcon.vue'
import { WEATHER_LOCATION, weatherMeta } from '@/constants/weather'
import { formatClock, formatDateLabel, formatShortTime } from '@/utils/format'
import { usePetStore } from '@/stores/pet'

const pet = usePetStore()

const now = ref(new Date())
let timer: number | null = null

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})

const clock = computed(() => formatClock(now.value))
const dateLabel = computed(() => formatDateLabel(now.value))

const meta = computed(() => weatherMeta(pet.weather?.code ?? 9))
const tempText = computed(() =>
  typeof pet.weather?.temp === 'number' ? `${pet.weather.temp}` : '--',
)
const updatedText = computed(() =>
  pet.weather?.updated_at ? `UPD ${formatShortTime(pet.weather.updated_at)}` : 'AWAITING FEED',
)
const locationText = computed(() => pet.weather?.location ?? WEATHER_LOCATION.name)
const sourceText = computed(() =>
  pet.weather?.source ? `数据源 ${pet.weather.source}` : '',
)
</script>

<template>
  <div class="clock-card card">
    <div class="head">
      <span class="eyebrow">Device Time</span>
      <span class="updated mono">{{ updatedText }}</span>
    </div>

    <div class="body">
      <div class="left">
        <div class="time mono">{{ clock }}</div>
        <div class="date mono">{{ dateLabel }}</div>
      </div>

      <div class="weather" :title="sourceText">
        <WeatherIcon :code="pet.weather?.code ?? 9" :size="34" />
        <div class="weather-text">
          <div class="temp mono">{{ tempText }}<span class="unit">℃</span></div>
          <div class="desc mono">{{ meta.text }}</div>
          <div class="loc mono">{{ locationText }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.clock-card {
  padding: 17px 20px 16px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.head .eyebrow::before {
  width: 10px;
}

.updated {
  font-size: 8.5px;
  letter-spacing: 0.12em;
  color: var(--faint);
}

.body {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.time {
  font-size: clamp(38px, 3.6vw, 50px);
  font-weight: 300;
  line-height: 0.95;
  letter-spacing: -0.045em;
  color: var(--ink);
}

.date {
  margin-top: 8px;
  font-size: 9.5px;
  letter-spacing: 0.16em;
  color: var(--dim);
}

.weather {
  display: flex;
  align-items: center;
  gap: 9px;
  padding-left: 16px;
  border-left: 1px solid var(--hair);
  flex-shrink: 0;
}

.temp {
  font-size: 25px;
  font-weight: 400;
  line-height: 1;
  letter-spacing: -0.02em;
}

.unit {
  font-size: 11px;
  margin-left: 2px;
  color: var(--faint);
}

.desc {
  margin-top: 4px;
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--dim);
}

.loc {
  margin-top: 1px;
  max-width: 126px;
  overflow: hidden;
  font-size: 8px;
  letter-spacing: 0.04em;
  color: var(--faint);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

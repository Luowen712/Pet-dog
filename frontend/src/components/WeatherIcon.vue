<script setup lang="ts">
import { computed } from 'vue'
import { weatherMeta } from '@/constants/weather'

const props = defineProps<{ code: number; size?: number }>()

const meta = computed(() => weatherMeta(props.code))
const px = computed(() => props.size ?? 26)
</script>

<template>
  <svg
    class="weather-icon"
    :width="px"
    :height="px"
    viewBox="0 0 32 32"
    role="img"
    :aria-label="meta.text"
  >
    <g v-if="meta.icon === 'sun'">
      <circle cx="16" cy="16" r="6.2" fill="#f6b73c" />
      <g stroke="#f6b73c" stroke-width="2.1" stroke-linecap="round">
        <line x1="16" y1="2.6" x2="16" y2="6" />
        <line x1="16" y1="26" x2="16" y2="29.4" />
        <line x1="2.6" y1="16" x2="6" y2="16" />
        <line x1="26" y1="16" x2="29.4" y2="16" />
        <line x1="6.7" y1="6.7" x2="9.1" y2="9.1" />
        <line x1="22.9" y1="22.9" x2="25.3" y2="25.3" />
        <line x1="6.7" y1="25.3" x2="9.1" y2="22.9" />
        <line x1="22.9" y1="9.1" x2="25.3" y2="6.7" />
      </g>
    </g>

    <g v-else-if="meta.icon === 'partly'">
      <circle cx="11.5" cy="11" r="4.6" fill="#f6b73c" />
      <g stroke="#f6b73c" stroke-width="1.9" stroke-linecap="round">
        <line x1="11.5" y1="2.6" x2="11.5" y2="4.8" />
        <line x1="3.2" y1="11" x2="5.4" y2="11" />
        <line x1="5.6" y1="5.1" x2="7.2" y2="6.7" />
        <line x1="5.6" y1="16.9" x2="7.2" y2="15.3" />
      </g>
      <g fill="#c9d4e6">
        <circle cx="13" cy="20" r="4.6" />
        <circle cx="20.5" cy="17.5" r="6" />
        <circle cx="25" cy="21.5" r="4" />
        <rect x="11" y="20" width="16" height="5.4" rx="2.7" />
      </g>
    </g>

    <g v-else-if="meta.icon === 'cloud'">
      <g fill="#c9d4e6">
        <circle cx="12" cy="18" r="5" />
        <circle cx="19.5" cy="15.5" r="6.4" />
        <circle cx="24.5" cy="19.5" r="4.4" />
        <rect x="10" y="18" width="17" height="6" rx="3" />
      </g>
    </g>

    <g v-else-if="meta.icon === 'drizzle' || meta.icon === 'rain' || meta.icon === 'heavy-rain'">
      <g fill="#c9d4e6">
        <circle cx="12" cy="16" r="4.6" />
        <circle cx="19.5" cy="13.8" r="5.8" />
        <circle cx="24.5" cy="17.4" r="4" />
        <rect x="10" y="16" width="17" height="5.4" rx="2.7" />
      </g>
      <g
        :stroke="meta.icon === 'heavy-rain' ? '#3f7fd6' : '#5f9ae8'"
        :stroke-width="meta.icon === 'heavy-rain' ? 2.4 : 2"
        stroke-linecap="round"
      >
        <line x1="12.5" y1="24" x2="11.3" y2="28.4" />
        <line
          v-if="meta.icon !== 'drizzle'"
          x1="19"
          y1="24"
          x2="17.8"
          y2="28.4"
        />
        <line
          v-if="meta.icon === 'rain' || meta.icon === 'heavy-rain'"
          x1="25"
          y1="24"
          x2="23.8"
          y2="28.4"
        />
        <line v-if="meta.icon === 'heavy-rain'" x1="15.8" y1="25.4" x2="14.6" y2="29.8" />
      </g>
    </g>

    <g v-else-if="meta.icon === 'thunder'">
      <g fill="#b9c6dc">
        <circle cx="12" cy="16" r="4.6" />
        <circle cx="19.5" cy="13.8" r="5.8" />
        <circle cx="24.5" cy="17.4" r="4" />
        <rect x="10" y="16" width="17" height="5.4" rx="2.7" />
      </g>
      <path
        d="M18.4 22.6 L13.8 28.2 H17.2 L15.4 31.6"
        stroke="#f0b429"
        stroke-width="2.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        fill="none"
      />
    </g>

    <g v-else-if="meta.icon === 'snow'">
      <g fill="#c9d4e6">
        <circle cx="12" cy="16" r="4.6" />
        <circle cx="19.5" cy="13.8" r="5.8" />
        <circle cx="24.5" cy="17.4" r="4" />
        <rect x="10" y="16" width="17" height="5.4" rx="2.7" />
      </g>
      <g fill="#8cb8e8">
        <circle cx="13" cy="27" r="1.5" />
        <circle cx="19.5" cy="29" r="1.5" />
        <circle cx="25" cy="26.6" r="1.5" />
        <circle cx="19.5" cy="24.6" r="1.2" />
      </g>
    </g>

    <g v-else-if="meta.icon === 'fog'">
      <g fill="#c9d4e6" opacity="0.85">
        <circle cx="12" cy="14" r="4.6" />
        <circle cx="19.5" cy="12" r="5.6" />
        <circle cx="24.5" cy="15.4" r="4" />
        <rect x="10" y="14" width="17" height="5.2" rx="2.6" />
      </g>
      <g stroke="#9fb0c8" stroke-width="2.2" stroke-linecap="round">
        <line x1="8" y1="24" x2="24" y2="24" />
        <line x1="11" y1="27.6" x2="22" y2="27.6" />
        <line x1="7" y1="31" x2="19" y2="31" />
      </g>
    </g>

    <g v-else>
      <text
        x="16"
        y="23"
        text-anchor="middle"
        font-size="15"
        font-weight="700"
        fill="#9fb0c8"
      >
        ?
      </text>
    </g>
  </svg>
</template>

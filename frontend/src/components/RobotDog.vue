<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

const props = withDefaults(defineProps<{ celebrating?: boolean }>(), { celebrating: false })

const local = ref(false)
let timer: number | null = null

const active = computed(() => props.celebrating || local.value)

function poke(): void {
  local.value = true
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    local.value = false
    timer = null
  }, 1500)
}

onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})
</script>

<template>
  <svg
    class="dog"
    :class="{ 'is-celebrating': active }"
    viewBox="0 0 320 250"
    role="button"
    tabindex="0"
    aria-label="点击让机器狗摇尾巴"
    @click="poke"
    @keydown.enter="poke"
    @keydown.space.prevent="poke"
  >
    <defs>
      <linearGradient id="dogGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#ffb347" />
        <stop offset="0.5" stop-color="#ff5a5f" />
        <stop offset="1" stop-color="#ff3d8b" />
      </linearGradient>
      <filter id="dogGlow" x="-80%" y="-80%" width="260%" height="260%">
        <feGaussianBlur stdDeviation="2.4" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
      <radialGradient id="dogFloor" cx="50%" cy="50%" r="50%">
        <stop offset="0" stop-color="rgba(20,20,20,.16)" />
        <stop offset="1" stop-color="rgba(20,20,20,0)" />
      </radialGradient>
    </defs>

    <!-- 背景轨道 -->
    <g class="orbit">
      <circle cx="228" cy="104" r="86" fill="none" stroke="rgba(20,20,20,.12)" stroke-dasharray="2 7" />
      <path
        d="M148 38a86 86 0 0 1 80 50"
        fill="none"
        stroke="url(#dogGrad)"
        stroke-width="1.6"
        stroke-linecap="round"
      />
    </g>

    <!-- 地面与底座 -->
    <ellipse cx="160" cy="208" rx="80" ry="7" fill="url(#dogFloor)" />
    <rect x="46" y="206" width="228" height="26" rx="5" fill="#262523" />
    <path d="M46 211h228" stroke="rgba(255,255,255,.15)" stroke-width="1" />
    <text x="54" y="245" font-family="IBM Plex Mono, monospace" font-size="6.5" letter-spacing="1.2" fill="rgba(20,20,20,.3)">
      UNIT 01
    </text>
    <text x="240" y="245" font-family="IBM Plex Mono, monospace" font-size="6.5" letter-spacing="1.2" fill="rgba(20,20,20,.3)">
      STM32
    </text>

    <!-- 会摇的整体 -->
    <g class="rig">
      <!-- 尾巴 -->
      <g class="tail-group">
        <path
          class="tail"
          d="M76 152C58 148 47 132 53 113"
          fill="none"
          stroke="#141414"
          stroke-width="2.4"
          stroke-linecap="round"
        />
        <circle cx="53" cy="113" r="3.2" fill="#141414" />
      </g>

      <!-- 身体 -->
      <g class="torso">
        <!-- 腿 -->
        <rect x="82" y="186" width="17" height="22" rx="8.5" fill="#f1ede5" stroke="#141414" stroke-width="1.2" />
        <rect x="106" y="189" width="16" height="19" rx="8" fill="#f1ede5" stroke="#141414" stroke-width="1.2" />
        <rect x="146" y="189" width="16" height="19" rx="8" fill="#f1ede5" stroke="#141414" stroke-width="1.2" />
        <rect x="168" y="186" width="17" height="22" rx="8.5" fill="#f1ede5" stroke="#141414" stroke-width="1.2" />

        <!-- 身体主体 -->
        <rect x="74" y="124" width="120" height="72" rx="28" fill="#f7f4ee" stroke="#141414" stroke-width="1.4" />
        <path d="M90 139h40" stroke="rgba(20,20,20,.3)" stroke-width="1" stroke-linecap="round" />

        <!-- 胸口指示灯 -->
        <circle cx="96" cy="154" r="2.6" fill="#ff8a3d" />
        <circle cx="105" cy="154" r="2.6" fill="#ff5a5f" />
        <circle cx="114" cy="154" r="2.6" fill="#ff3d8b" />

        <!-- 散热缝 -->
        <path d="M93 171h30M93 178h22" stroke="rgba(20,20,20,.2)" stroke-width="1.4" stroke-linecap="round" />

        <!-- 脖子 -->
        <rect x="166" y="118" width="20" height="20" fill="#141414" opacity=".88" />
      </g>

      <!-- 头 -->
      <g class="head-group">
        <!-- 耳朵 -->
        <rect x="182" y="36" width="23" height="24" rx="11" fill="#f7f4ee" stroke="#141414" stroke-width="1.3" />
        <rect x="253" y="36" width="23" height="24" rx="11" fill="#f7f4ee" stroke="#141414" stroke-width="1.3" />

        <!-- 天线 -->
        <path d="M230 50c0-8 6-10 2-16" fill="none" stroke="#141414" stroke-width="1.2" stroke-linecap="round" />
        <circle cx="232" cy="33" r="2.4" fill="#141414" />

        <!-- 头壳 -->
        <rect x="176" y="50" width="108" height="94" rx="30" fill="#f7f4ee" stroke="#141414" stroke-width="1.4" />

        <!-- 面屏 -->
        <rect x="194" y="72" width="72" height="52" rx="14" fill="#141414" />
        <g class="eyes">
          <ellipse cx="214" cy="98" rx="4.6" ry="5.8" fill="#ffb347" filter="url(#dogGlow)" />
          <ellipse cx="246" cy="98" rx="4.6" ry="5.8" fill="#ff5a5f" filter="url(#dogGlow)" />
        </g>

        <!-- 腮红 -->
        <ellipse cx="198" cy="132" rx="6" ry="2.6" fill="#ff5a5f" opacity=".35" />
        <ellipse cx="262" cy="132" rx="6" ry="2.6" fill="#ff5a5f" opacity=".35" />

        <!-- 电缆 -->
        <path
          d="M176 138c-14 8-26 10-40 8"
          fill="none"
          stroke="rgba(20,20,20,.4)"
          stroke-width="1.2"
          stroke-linecap="round"
          stroke-dasharray="2 3"
        />
      </g>
    </g>

    <!-- 成功时的小星光 -->
    <g class="sparkles" aria-hidden="true">
      <path d="M162 32l2.4 5 5 2.4-5 2.4-2.4 5-2.4-5-5-2.4 5-2.4z" fill="#ffb347" />
      <path d="M302 92l1.8 3.8 3.8 1.8-3.8 1.8-1.8 3.8-1.8-3.8-3.8-1.8 3.8-1.8z" fill="#ff5a5f" />
      <path d="M296 158l1.4 3 3 1.4-3 1.4-1.4 3-1.4-3-3-1.4 3-1.4z" fill="#ff3d8b" />
    </g>
  </svg>
</template>

<style scoped>
.dog {
  display: block;
  width: 100%;
  height: auto;
  max-width: 380px;
  cursor: pointer;
  overflow: visible;
  outline: none;
  -webkit-tap-highlight-color: transparent;
}

.dog:focus-visible {
  outline: 1px dashed rgba(20, 20, 20, 0.35);
  outline-offset: 6px;
}

.rig,
.tail-group,
.head-group,
.eyes {
  transform-box: view-box;
}

.rig {
  transform-origin: 160px 226px;
  animation: bob 3.6s ease-in-out infinite;
}

.tail-group {
  transform-origin: 76px 152px;
  animation: tailIdle 4.2s ease-in-out infinite;
}

.head-group {
  transform-origin: 230px 145px;
  animation: headSway 5.4s ease-in-out infinite;
}

.eyes {
  transform-origin: 230px 98px;
  animation: blink 5.6s ease-in-out infinite;
}

.sparkles {
  opacity: 0;
}

/* 悬停：尾巴先摇起来 */
.dog:hover .tail-group {
  animation: tailWag 0.55s ease-in-out infinite;
}

.dog:hover .head-group {
  animation: headPerk 2.2s ease-in-out infinite;
}

/* 点击 / 登录成功：整只左右摆，尾巴快速摇 */
.dog.is-celebrating .rig {
  animation: wiggle 0.46s ease-in-out 3;
}

.dog.is-celebrating .tail-group {
  animation: tailWag 0.16s ease-in-out 10;
}

.dog.is-celebrating .head-group {
  animation: headNod 0.42s ease-in-out 4;
}

.dog.is-celebrating .sparkles {
  animation: sparkle 1.5s ease-out 1;
}

@keyframes bob {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-2px);
  }
}

@keyframes tailIdle {
  0%,
  100% {
    transform: rotate(-5deg);
  }
  50% {
    transform: rotate(7deg);
  }
}

@keyframes tailWag {
  0%,
  100% {
    transform: rotate(-20deg);
  }
  50% {
    transform: rotate(24deg);
  }
}

@keyframes headSway {
  0%,
  100% {
    transform: rotate(-3.5deg);
  }
  50% {
    transform: rotate(1.5deg);
  }
}

@keyframes headPerk {
  0%,
  100% {
    transform: rotate(-7deg) translateY(0);
  }
  50% {
    transform: rotate(2deg) translateY(-2px);
  }
}

@keyframes headNod {
  0%,
  100% {
    transform: rotate(-5deg);
  }
  50% {
    transform: rotate(5deg) translateY(-2px);
  }
}

@keyframes wiggle {
  0%,
  100% {
    transform: rotate(-3deg);
  }
  50% {
    transform: rotate(3deg);
  }
}

@keyframes blink {
  0%,
  90%,
  100% {
    transform: scaleY(1);
  }
  94% {
    transform: scaleY(0.12);
  }
}

@keyframes sparkle {
  0% {
    opacity: 0;
    transform: translateY(4px);
  }
  35% {
    opacity: 1;
  }
  100% {
    opacity: 0;
    transform: translateY(-6px);
  }
}
</style>

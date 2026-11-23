<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId } from 'vue'
import { FACES, FACE_BY_ID } from '@/constants/faces'
import { emitParticleBurst } from '@/utils/theme'

const props = withDefaults(
  defineProps<{
    celebrating?: boolean
    face?: number | null
    online?: boolean
    pose?: string
    compact?: boolean
  }>(),
  {
    celebrating: false,
    face: 5,
    online: true,
    pose: '',
    compact: false,
  },
)

const uid = useId()
const gradId = `dog-grad-${uid}`
const floorId = `dog-floor-${uid}`
const clipId = `dog-visor-${uid}`

const local = ref(false)
let timer: number | null = null

const active = computed(() => props.celebrating || local.value)
const faceDef = computed(() => FACE_BY_ID.get(props.face ?? 5) ?? FACE_BY_ID.get(5) ?? FACES[0])
const faceTransform = computed(() => {
  const ty = faceDef.value.mouth === 'none' ? 85.4 : 82.8
  return `translate(175, ${ty}) scale(0.86)`
})

function poke(event?: MouseEvent | KeyboardEvent): void {
  local.value = true
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    local.value = false
    timer = null
  }, 1500)

  if (event && 'clientX' in event && event.clientX > 0) {
    emitParticleBurst(event.clientX, event.clientY, 'accent', 20)
  } else if (event?.currentTarget instanceof Element) {
    const rect = event.currentTarget.getBoundingClientRect()
    emitParticleBurst(rect.left + rect.width * 0.5, rect.top + rect.height * 0.45, 'accent', 20)
  }
}

onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})
</script>

<template>
  <svg
    class="dog"
    :class="[{ 'is-celebrating': active, 'is-offline': !online }, pose]"
    viewBox="0 0 320 242"
    role="button"
    tabindex="0"
    aria-label="点击让机器狗摇尾巴"
    @click="poke($event)"
    @keydown.enter="poke($event)"
    @keydown.space.prevent="poke($event)"
  >
    <defs>
      <linearGradient :id="gradId" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--accent-1)" />
        <stop offset="52%" stop-color="var(--accent-2)" />
        <stop offset="100%" stop-color="var(--accent-3)" />
      </linearGradient>
      <radialGradient :id="floorId" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="var(--accent-2)" stop-opacity="0.32" />
        <stop offset="100%" stop-color="var(--accent-2)" stop-opacity="0" />
      </radialGradient>
      <clipPath :id="clipId">
        <rect x="193" y="71" width="74" height="52" rx="13" />
      </clipPath>
    </defs>

    <!-- 背景轨道 -->
    <g :opacity="compact ? 0.55 : 0.85">
      <circle
        cx="222"
        cy="102"
        r="88"
        fill="none"
        stroke="var(--hair-strong)"
        stroke-dasharray="3 8"
      />
      <path
        d="M144 38a88 88 0 0 1 114 14"
        fill="none"
        :stroke="`url(#${gradId})`"
        stroke-width="2"
        stroke-linecap="round"
      />
    </g>

    <!-- 地面与底座 -->
    <ellipse cx="160" cy="210" rx="92" ry="11" :fill="`url(#${floorId})`" />
    <rect
      x="44"
      y="206"
      width="232"
      height="24"
      rx="7"
      fill="var(--dog-base)"
      stroke="var(--hair-strong)"
      stroke-width="1"
    />
    <path
      d="M56 212h208"
      :stroke="`url(#${gradId})`"
      stroke-width="1.4"
      stroke-linecap="round"
      opacity="0.72"
    />

    <!-- 整体活动骨架 -->
    <g class="rig">
      <!-- 尾巴 -->
      <g class="tail-group">
        <path
          d="M76 152C56 147 45 130 53 111"
          fill="none"
          stroke="var(--dog-stroke)"
          stroke-width="2.6"
          stroke-linecap="round"
        />
        <circle cx="53" cy="111" r="3.8" :fill="`url(#${gradId})`" />
      </g>

      <!-- 身体 -->
      <g class="torso">
        <rect
          x="82"
          y="184"
          width="17"
          height="24"
          rx="8.5"
          fill="var(--dog-body-deep)"
          stroke="var(--dog-stroke)"
          stroke-width="1.3"
        />
        <rect
          x="106"
          y="187"
          width="16"
          height="21"
          rx="8"
          fill="var(--dog-body-deep)"
          stroke="var(--dog-stroke)"
          stroke-width="1.3"
        />
        <rect
          x="146"
          y="187"
          width="16"
          height="21"
          rx="8"
          fill="var(--dog-body-deep)"
          stroke="var(--dog-stroke)"
          stroke-width="1.3"
        />
        <rect
          x="168"
          y="184"
          width="17"
          height="24"
          rx="8.5"
          fill="var(--dog-body-deep)"
          stroke="var(--dog-stroke)"
          stroke-width="1.3"
        />

        <rect
          x="74"
          y="122"
          width="122"
          height="74"
          rx="28"
          fill="var(--dog-body)"
          stroke="var(--dog-stroke)"
          stroke-width="1.5"
        />
        <path
          d="M92 138h44"
          stroke="var(--dog-detail)"
          stroke-width="1.2"
          stroke-linecap="round"
        />

        <!-- 胸口指示灯 -->
        <circle cx="96" cy="154" r="3" fill="var(--accent-1)" />
        <circle cx="106" cy="154" r="3" fill="var(--accent-2)" />
        <circle cx="116" cy="154" r="3" fill="var(--accent-3)" />

        <!-- 散热缝 -->
        <path
          d="M93 171h32M93 178h22"
          stroke="var(--dog-detail)"
          stroke-width="1.6"
          stroke-linecap="round"
        />

        <!-- 脖子 -->
        <rect
          x="166"
          y="118"
          width="20"
          height="20"
          rx="4"
          fill="var(--dog-base)"
          stroke="var(--dog-stroke)"
          stroke-width="1"
        />
      </g>

      <!-- 头部与 OLED 面屏（无腮红） -->
      <g class="head-group">
        <rect
          x="182"
          y="36"
          width="23"
          height="24"
          rx="11"
          fill="var(--dog-body)"
          stroke="var(--dog-stroke)"
          stroke-width="1.4"
        />
        <rect
          x="253"
          y="36"
          width="23"
          height="24"
          rx="11"
          fill="var(--dog-body)"
          stroke="var(--dog-stroke)"
          stroke-width="1.4"
        />

        <!-- 天线 -->
        <path
          d="M230 50c0-8 6-10 2-17"
          fill="none"
          stroke="var(--dog-stroke)"
          stroke-width="1.3"
          stroke-linecap="round"
        />
        <circle cx="232" cy="31" r="3.2" :fill="online ? 'var(--oled-glow)' : 'var(--faint)'" />

        <!-- 头壳 -->
        <rect
          x="176"
          y="50"
          width="108"
          height="94"
          rx="30"
          fill="var(--dog-body)"
          stroke="var(--dog-stroke)"
          stroke-width="1.5"
        />

        <!-- OLED 面屏 -->
        <rect
          x="192"
          y="70"
          width="76"
          height="54"
          rx="14"
          fill="var(--oled-bg)"
          stroke="var(--oled-screen-border)"
          stroke-width="1.2"
        />

        <g :clip-path="`url(#${clipId})`">
          <g
            v-if="!online"
            stroke="rgba(228, 244, 238, 0.36)"
            stroke-width="2.6"
            stroke-linecap="round"
          >
            <line x1="206" y1="97" x2="220" y2="97" />
            <line x1="240" y1="97" x2="254" y2="97" />
          </g>

          <g v-else :transform="faceTransform">
            <g class="dog-oled-face">
              <g class="oled-pixel">
                <template v-if="faceDef.eyes === 'round'">
                  <circle cx="44" cy="12" r="4.6" class="solid" />
                  <circle cx="84" cy="12" r="4.6" class="solid" />
                </template>
                <template v-else-if="faceDef.eyes === 'line'">
                  <line x1="37" y1="13" x2="51" y2="13" />
                  <line x1="77" y1="13" x2="91" y2="13" />
                </template>
                <template v-else-if="faceDef.eyes === 'slant'">
                  <line x1="37" y1="8" x2="51" y2="16" />
                  <line x1="77" y1="16" x2="91" y2="8" />
                </template>
                <template v-else-if="faceDef.eyes === 'big'">
                  <circle cx="44" cy="12" r="6.8" />
                  <circle cx="44" cy="12" r="2.6" class="solid" />
                  <circle cx="84" cy="12" r="6.8" />
                  <circle cx="84" cy="12" r="2.6" class="solid" />
                </template>
                <template v-else-if="faceDef.eyes === 'capsule'">
                  <rect class="solid" x="36" y="4.5" width="15" height="20" rx="7.5" />
                  <rect class="solid" x="77" y="4.5" width="15" height="20" rx="7.5" />
                </template>
                <template v-else-if="faceDef.eyes === 'chevron'">
                  <path d="M38 6 L50 13 L38 20" />
                  <path d="M90 6 L78 13 L90 20" />
                </template>
                <template v-else>
                  <path
                    class="solid"
                    d="M44 5.5 L46.6 11 L52 13 L46.6 15 L44 20.5 L41.4 15 L36 13 L41.4 11 Z"
                  />
                  <path
                    class="solid"
                    d="M84 5.5 L86.6 11 L92 13 L86.6 15 L84 20.5 L81.4 15 L76 13 L81.4 11 Z"
                  />
                </template>

                <template v-if="faceDef.mouth === 'smile'">
                  <path d="M55 20 Q64 28.5 73 20" />
                </template>
                <template v-else-if="faceDef.mouth === 'frown'">
                  <path d="M55 27 Q64 19.5 73 27" />
                </template>
                <template v-else-if="faceDef.mouth === 'o'">
                  <ellipse cx="64" cy="24" rx="3.6" ry="4.4" />
                </template>
                <template v-else-if="faceDef.mouth === 'cat'">
                  <path d="M57 22 Q60.5 26.5 64 22 Q67.5 26.5 71 22" />
                </template>
                <template v-else-if="faceDef.mouth === 'omega'">
                  <path d="M55 22.5 Q59.5 27.5 64 22.5 Q68.5 27.5 73 22.5" />
                </template>
              </g>
            </g>
          </g>
        </g>

        <!-- 电缆 -->
        <path
          d="M176 138c-14 8-26 10-40 8"
          fill="none"
          stroke="var(--dog-detail)"
          stroke-width="1.3"
          stroke-linecap="round"
          stroke-dasharray="2.5 3.5"
        />
      </g>
    </g>

    <!-- 互动星光 -->
    <g class="sparkles" aria-hidden="true">
      <path d="M162 32l2.4 5 5 2.4-5 2.4-2.4 5-2.4-5-5-2.4 5-2.4z" fill="var(--accent-1)" />
      <path d="M302 92l1.8 3.8 3.8 1.8-3.8 1.8-1.8 3.8-1.8-3.8-3.8-1.8 3.8-1.8z" fill="var(--accent-2)" />
      <path d="M296 158l1.4 3 3 1.4-3 1.4-1.4 3-1.4-3-3-1.4 3-1.4z" fill="var(--accent-3)" />
    </g>
  </svg>
</template>

<style scoped>
.dog {
  display: block;
  width: 100%;
  height: auto;
  max-width: 390px;
  cursor: pointer;
  overflow: visible;
  outline: none;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
  transition: filter 0.32s ease;
}

.dog.is-offline {
  filter: saturate(0.28) brightness(0.84);
}

.dog:focus-visible {
  outline: 1.5px dashed var(--accent-2);
  outline-offset: 6px;
}

.oled-pixel {
  fill: none;
  stroke: var(--oled-glow);
  stroke-width: 3.4;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 0 4px rgba(100, 240, 184, 0.52));
}

.oled-pixel .solid {
  fill: var(--oled-glow);
  stroke: none;
}

.rig,
.tail-group,
.head-group {
  transform-box: view-box;
}

.rig {
  transform-origin: 160px 210px;
  animation: bob 3.5s ease-in-out infinite;
  transition: transform 0.38s var(--ease-spring);
}

.tail-group {
  transform-origin: 76px 152px;
  animation: tailIdle 4s ease-in-out infinite;
}

.head-group {
  transform-origin: 230px 145px;
  animation: headSway 5.2s ease-in-out infinite;
}

.dog-oled-face {
  transform-box: fill-box;
  transform-origin: center;
  animation: blink 5.4s ease-in-out infinite;
}

.dog.is-offline .rig,
.dog.is-offline .tail-group,
.dog.is-offline .head-group,
.dog.is-offline .dog-oled-face {
  animation-play-state: paused;
}

.sparkles {
  opacity: 0;
}

.dog:hover .tail-group {
  animation: tailWag 0.45s ease-in-out infinite;
}

.dog:hover .head-group {
  animation: headPerk 1.9s ease-in-out infinite;
}

.dog.is-celebrating .rig {
  animation: wiggle 0.44s ease-in-out 3;
}

.dog.is-celebrating .tail-group {
  animation: tailWag 0.15s ease-in-out 10;
}

.dog.is-celebrating .head-group {
  animation: headNod 0.38s ease-in-out 4;
}

.dog.is-celebrating .sparkles {
  animation: sparkle 1.45s ease-out 1;
}

.dog.pose-sit .rig {
  transform: translateY(10px) rotate(-6deg);
}
.dog.pose-stand .rig {
  transform: translateY(-6px);
}
.dog.pose-lie .rig {
  transform: translateY(18px) scaleY(0.92);
}
.dog.pose-forward .rig {
  animation: stepFwd 0.55s ease-in-out 2;
}
.dog.pose-backward .rig {
  animation: stepBack 0.55s ease-in-out 2;
}
.dog.pose-left .rig {
  transform: rotate(-9deg) translateX(-10px);
}
.dog.pose-right .rig {
  transform: rotate(9deg) translateX(10px);
}

@keyframes bob {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-3px);
  }
}

@keyframes tailIdle {
  0%,
  100% {
    transform: rotate(-6deg);
  }
  50% {
    transform: rotate(8deg);
  }
}

@keyframes tailWag {
  0%,
  100% {
    transform: rotate(-22deg);
  }
  50% {
    transform: rotate(26deg);
  }
}

@keyframes headSway {
  0%,
  100% {
    transform: rotate(-3.5deg);
  }
  50% {
    transform: rotate(1.8deg);
  }
}

@keyframes headPerk {
  0%,
  100% {
    transform: rotate(-7deg) translateY(0);
  }
  50% {
    transform: rotate(2deg) translateY(-2.5px);
  }
}

@keyframes headNod {
  0%,
  100% {
    transform: rotate(-5.5deg);
  }
  50% {
    transform: rotate(5.5deg) translateY(-2.5px);
  }
}

@keyframes wiggle {
  0%,
  100% {
    transform: rotate(-3.2deg) translateY(-2px);
  }
  50% {
    transform: rotate(3.2deg) translateY(-5px);
  }
}

@keyframes blink {
  0%,
  91%,
  100% {
    transform: scaleY(1);
  }
  95% {
    transform: scaleY(0.12);
  }
}

@keyframes stepFwd {
  0%,
  100% {
    transform: translateX(0) translateY(0);
  }
  40% {
    transform: translateX(14px) translateY(-6px) rotate(3deg);
  }
  70% {
    transform: translateX(8px) translateY(0);
  }
}

@keyframes stepBack {
  0%,
  100% {
    transform: translateX(0) translateY(0);
  }
  40% {
    transform: translateX(-14px) translateY(-5px) rotate(-3deg);
  }
  70% {
    transform: translateX(-8px) translateY(0);
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

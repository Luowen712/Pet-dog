<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { onParticleBurst, useTheme } from '@/utils/theme'
import type { BurstTone, ThemeId } from '@/utils/theme'

interface AmbientParticle {
  x: number
  y: number
  vx: number
  vy: number
  r: number
  depth: number
  phase: number
  tone: 'a' | 'b' | 'c'
}

interface BurstParticle {
  x: number
  y: number
  vx: number
  vy: number
  r: number
  life: number
  decay: number
  rgb: [number, number, number]
}

interface Palette {
  a: [number, number, number]
  b: [number, number, number]
  c: [number, number, number]
  line: [number, number, number]
  baseAlpha: number
}

const PALETTES: Record<ThemeId, Palette> = {
  porcelain: {
    a: [230, 84, 59],
    b: [235, 142, 42],
    c: [33, 115, 79],
    line: [120, 72, 42],
    baseAlpha: 0.36,
  },
  phosphor: {
    a: [94, 242, 184],
    b: [45, 212, 191],
    c: [255, 179, 71],
    line: [94, 242, 184],
    baseAlpha: 0.56,
  },
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
const { theme } = useTheme()

let rafId = 0
let stopBurst = () => {}
let cleanupListeners = () => {}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas || typeof window === 'undefined') return
  if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent)) return
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

  let ctx: CanvasRenderingContext2D | null = null
  try {
    ctx = canvas.getContext('2d')
  } catch {
    return
  }
  if (!ctx) return

  const context = ctx
  let width = 0
  let height = 0
  let dpr = 1
  const particles: AmbientParticle[] = []
  const bursts: BurstParticle[] = []
  const pointer = { x: -9999, y: -9999, active: false }

  function targetCount(): number {
    return width < 720 ? 36 : 68
  }

  function createParticle(): AmbientParticle {
    const depth = 0.35 + Math.random() * 0.65
    return {
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.26 * depth,
      vy: (-0.11 - Math.random() * 0.22) * depth,
      r: (1.0 + Math.random() * 1.8) * depth,
      depth,
      phase: Math.random() * Math.PI * 2,
      tone: Math.random() < 0.55 ? 'a' : Math.random() < 0.8 ? 'b' : 'c',
    }
  }

  function resize(): void {
    if (!canvas) return
    dpr = Math.min(window.devicePixelRatio || 1, 2)
    width = window.innerWidth
    height = window.innerHeight
    canvas.width = width * dpr
    canvas.height = height * dpr
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
    const count = targetCount()
    while (particles.length < count) particles.push(createParticle())
    if (particles.length > count) particles.length = count
  }

  function spawnBurst(x: number, y: number, count: number, tone: BurstTone): void {
    const pal = PALETTES[theme.value]
    const primary = tone === 'oled' ? pal.b : Math.random() > 0.4 ? pal.a : pal.c
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.35
      const speed = 1.3 + Math.random() * 3.1
      bursts.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 0.45,
        r: 1.4 + Math.random() * 2.0,
        life: 1,
        decay: 0.022 + Math.random() * 0.018,
        rgb: i % 3 === 0 ? pal.b : primary,
      })
    }
  }

  function onPointerMove(e: PointerEvent): void {
    pointer.x = e.clientX
    pointer.y = e.clientY
    pointer.active = true
  }

  function onPointerLeave(): void {
    pointer.active = false
  }

  function render(now: number): void {
    context.clearRect(0, 0, width, height)
    const t = now * 0.001
    const pal = PALETTES[theme.value]

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i]
      p.x += p.vx + Math.sin(t * 0.6 + p.phase) * 0.11
      p.y += p.vy

      if (pointer.active) {
        const dx = p.x - pointer.x
        const dy = p.y - pointer.y
        const distSq = dx * dx + dy * dy
        if (distSq < 21000 && distSq > 1) {
          const dist = Math.sqrt(distSq)
          const push = (1 - dist / 145) * 0.52
          p.x += (dx / dist) * push
          p.y += (dy / dist) * push
        }
      }

      if (p.y < -12) {
        p.y = height + 12
        p.x = Math.random() * width
      }
      if (p.x < -12) p.x = width + 12
      if (p.x > width + 12) p.x = -12

      const rgb = pal[p.tone]
      const twinkle = 0.55 + 0.45 * Math.sin(t * 1.5 + p.phase)
      const alpha = pal.baseAlpha * p.depth * twinkle

      context.beginPath()
      context.arc(p.x, p.y, p.r, 0, Math.PI * 2)
      context.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha.toFixed(3)})`
      context.fill()
    }

    context.lineWidth = 0.8
    for (let i = 0; i < particles.length; i++) {
      const a = particles[i]
      if (pointer.active) {
        const dp = Math.hypot(a.x - pointer.x, a.y - pointer.y)
        if (dp < 150) {
          const la = (1 - dp / 150) * 0.24
          context.strokeStyle = `rgba(${pal.line[0]},${pal.line[1]},${pal.line[2]},${la.toFixed(3)})`
          context.beginPath()
          context.moveTo(a.x, a.y)
          context.lineTo(pointer.x, pointer.y)
          context.stroke()
        }
      }
      for (let j = i + 1; j < particles.length; j++) {
        const b = particles[j]
        const d = Math.hypot(a.x - b.x, a.y - b.y)
        if (d < 94) {
          const la = (1 - d / 94) * 0.11
          context.strokeStyle = `rgba(${pal.line[0]},${pal.line[1]},${pal.line[2]},${la.toFixed(3)})`
          context.beginPath()
          context.moveTo(a.x, a.y)
          context.lineTo(b.x, b.y)
          context.stroke()
        }
      }
    }

    for (let i = bursts.length - 1; i >= 0; i--) {
      const b = bursts[i]
      b.x += b.vx
      b.y += b.vy
      b.vx *= 0.96
      b.vy = b.vy * 0.96 + 0.04
      b.life -= b.decay
      if (b.life <= 0) {
        bursts.splice(i, 1)
        continue
      }
      context.beginPath()
      context.arc(b.x, b.y, b.r * b.life, 0, Math.PI * 2)
      context.fillStyle = `rgba(${b.rgb[0]},${b.rgb[1]},${b.rgb[2]},${b.life.toFixed(3)})`
      context.fill()
    }

    rafId = window.requestAnimationFrame(render)
  }

  resize()
  window.addEventListener('resize', resize)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerleave', onPointerLeave)
  stopBurst = onParticleBurst((d) => spawnBurst(d.x, d.y, d.count, d.tone))
  cleanupListeners = () => {
    window.removeEventListener('resize', resize)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerleave', onPointerLeave)
  }

  rafId = window.requestAnimationFrame(render)
})

onBeforeUnmount(() => {
  if (rafId && typeof window !== 'undefined') window.cancelAnimationFrame(rafId)
  stopBurst()
  cleanupListeners()
})
</script>

<template>
  <canvas ref="canvasRef" class="particle-backdrop" aria-hidden="true" />
</template>

<style scoped>
.particle-backdrop {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
  pointer-events: none;
}
</style>

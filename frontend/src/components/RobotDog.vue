<template>
  <svg class="dog" viewBox="0 0 320 250" role="img" aria-label="线稿机器狗">
    <defs>
      <linearGradient id="dogGrad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#ffb347" />
        <stop offset="0.5" stop-color="#ff5a5f" />
        <stop offset="1" stop-color="#ff3d8b" />
      </linearGradient>
      <filter id="dogGlow" x="-70%" y="-70%" width="240%" height="240%">
        <feGaussianBlur stdDeviation="2.2" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>

    <!-- 轨道虚线 -->
    <circle cx="228" cy="108" r="84" fill="none" stroke="rgba(20,20,20,.12)" stroke-dasharray="2 7" />
    <path
      d="M150 40a84 84 0 0 1 78 48"
      fill="none"
      stroke="url(#dogGrad)"
      stroke-width="1.6"
      stroke-linecap="round"
    />

    <!-- 影子与底座 -->
    <ellipse cx="160" cy="207" rx="74" ry="6" fill="rgba(20,20,20,.10)" />
    <rect x="48" y="207" width="224" height="24" rx="4" fill="#262523" />
    <path d="M48 211h224" stroke="rgba(255,255,255,.14)" stroke-width="1" />

    <!-- 尾巴 -->
    <path
      d="M78 150c-18-4-28-20-22-34"
      fill="none"
      stroke="#141414"
      stroke-width="2"
      stroke-linecap="round"
    />
    <circle cx="56" cy="114" r="3" fill="#141414" />

    <!-- 身体 -->
    <rect
      x="76"
      y="128"
      width="118"
      height="68"
      rx="18"
      fill="#f7f4ee"
      stroke="#141414"
      stroke-width="1.4"
    />
    <path d="M88 140h44" stroke="rgba(20,20,20,.35)" stroke-width="1" />
    <circle cx="94" cy="158" r="2.6" fill="#ff8a3d" />
    <circle cx="103" cy="158" r="2.6" fill="#ff5a5f" />
    <circle cx="112" cy="158" r="2.6" fill="#ff3d8b" />
    <path d="M94 174h34M94 180h26" stroke="rgba(20,20,20,.22)" stroke-width="1.2" />

    <!-- 腿 -->
    <rect x="142" y="190" width="18" height="19" rx="6" fill="#f7f4ee" stroke="#141414" stroke-width="1.3" />
    <rect x="112" y="190" width="18" height="19" rx="6" fill="#f7f4ee" stroke="#141414" stroke-width="1.3" />
    <rect x="88" y="192" width="16" height="17" rx="6" fill="#f1ede5" stroke="#141414" stroke-width="1.2" />
    <rect x="160" y="192" width="16" height="17" rx="6" fill="#f1ede5" stroke="#141414" stroke-width="1.2" />

    <!-- 脖子 -->
    <path d="M172 128h18v14h-18z" fill="#141414" opacity=".85" />

    <!-- 头 -->
    <rect
      x="178"
      y="56"
      width="104"
      height="90"
      rx="22"
      fill="#f7f4ee"
      stroke="#141414"
      stroke-width="1.4"
    />
    <!-- 耳朵 -->
    <rect x="188" y="43" width="20" height="18" rx="6" fill="#f7f4ee" stroke="#141414" stroke-width="1.3" />
    <rect x="254" y="43" width="20" height="18" rx="6" fill="#f7f4ee" stroke="#141414" stroke-width="1.3" />
    <!-- 天线 -->
    <path d="M230 56V46" stroke="#141414" stroke-width="1.2" stroke-linecap="round" />
    <circle cx="230" cy="44" r="2.2" fill="#141414" />

    <!-- 面屏 -->
    <rect x="196" y="76" width="68" height="46" rx="10" fill="#141414" />
    <circle cx="216" cy="99" r="4.6" fill="#ffb347" filter="url(#dogGlow)" />
    <circle cx="244" cy="99" r="4.6" fill="#ff5a5f" filter="url(#dogGlow)" />

    <!-- 电缆 -->
    <path
      d="M178 132c-14 8-24 10-38 8"
      fill="none"
      stroke="rgba(20,20,20,.45)"
      stroke-width="1.2"
      stroke-linecap="round"
      stroke-dasharray="2 3"
    />

    <!-- 标注 -->
    <text x="76" y="246" font-family="IBM Plex Mono, monospace" font-size="7" letter-spacing="1.4" fill="rgba(20,20,20,.34)">
      UNIT 01 / DESK PET
    </text>
    <text x="252" y="246" font-family="IBM Plex Mono, monospace" font-size="7" letter-spacing="1.4" fill="rgba(20,20,20,.34)">
      STM32
    </text>
  </svg>
</template>

<style scoped>
.dog {
  display: block;
  width: 100%;
  height: auto;
  max-width: 380px;
}
</style>

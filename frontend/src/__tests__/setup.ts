import { config } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import * as ElementPlusIcons from '@element-plus/icons-vue'
import type { Component } from 'vue'

// 组件测试里没有 main.ts，手动把 Element Plus 和全局图标装上
config.global.plugins = [ElementPlus]

const icons: Record<string, Component> = {}
for (const [name, component] of Object.entries(ElementPlusIcons)) {
  icons[name] = component as Component
}
config.global.components = icons

class ResizeObserverMock {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver

// jsdom 没有实现 scrollTo，路由的 scrollBehavior 会调用它
window.scrollTo = (() => {}) as unknown as typeof window.scrollTo

if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

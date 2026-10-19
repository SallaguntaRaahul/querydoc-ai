import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, expect } from 'vitest'
import * as axeMatchers from 'vitest-axe/matchers'

expect.extend(axeMatchers)
afterEach(() => cleanup())

// jsdom lacks these browser APIs used by Radix / layout code.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({ matches: query.includes('dark'), media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false }) as MediaQueryList
}
class RO { observe() {} unobserve() {} disconnect() {} }
;(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver ??= RO
Element.prototype.scrollIntoView ??= () => {}
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.scrollTo ??= () => {}

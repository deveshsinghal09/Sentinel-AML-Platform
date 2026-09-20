import {
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useEffect,
  useMemo,
  useState,
} from 'react'

function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useCountUp(value: number, duration = 650) {
  const [displayValue, setDisplayValue] = useState(
    prefersReducedMotion() ? value : 0,
  )

  useEffect(() => {
    if (prefersReducedMotion()) {
      setDisplayValue(value)
      return
    }

    let animationFrame = 0
    const startedAt = performance.now()

    const tick = (now: number) => {
      const progress = Math.min((now - startedAt) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplayValue(Math.round(value * eased))

      if (progress < 1) {
        animationFrame = requestAnimationFrame(tick)
      }
    }

    animationFrame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animationFrame)
  }, [duration, value])

  return displayValue
}

export function useMagneticButton<T extends HTMLElement>(
  ref: RefObject<T | null>,
) {
  return useMemo(() => ({
    onPointerMove(event: ReactPointerEvent<T>) {
      if (
        event.pointerType === 'touch'
        || prefersReducedMotion()
        || (
          typeof window.matchMedia === 'function'
          && !window.matchMedia('(hover: hover)').matches
        )
      ) {
        return
      }

      const element = ref.current
      if (!element) return

      const bounds = element.getBoundingClientRect()
      const x = (event.clientX - bounds.left - bounds.width / 2) * 0.12
      const y = (event.clientY - bounds.top - bounds.height / 2) * 0.18
      element.style.setProperty('--magnetic-x', `${x.toFixed(2)}px`)
      element.style.setProperty('--magnetic-y', `${y.toFixed(2)}px`)
    },
    onPointerLeave() {
      const element = ref.current
      if (!element) return
      element.style.setProperty('--magnetic-x', '0px')
      element.style.setProperty('--magnetic-y', '0px')
    },
  }), [ref])
}

export function useRevealOnScroll(routeKey: string) {
  useEffect(() => {
    if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
      return
    }

    const selector = [
      '.workspace-page > section',
      '.workspace-page > article',
      '.results > section',
      '.results > .results-heading',
    ].join(',')

    const observed = new WeakSet<Element>()
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return
          entry.target.classList.add('is-visible')
          observer.unobserve(entry.target)
        })
      },
      { threshold: 0.08, rootMargin: '0px 0px -32px' },
    )

    const observeNewElements = () => {
      document.querySelectorAll(selector).forEach((element) => {
        if (observed.has(element)) return
        observed.add(element)
        element.classList.add('reveal-on-scroll')
        observer.observe(element)
      })
    }

    observeNewElements()
    const mutations = new MutationObserver(observeNewElements)
    mutations.observe(document.body, { childList: true, subtree: true })

    return () => {
      mutations.disconnect()
      observer.disconnect()
    }
  }, [routeKey])
}

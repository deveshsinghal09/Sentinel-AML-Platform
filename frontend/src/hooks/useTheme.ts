import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'aml-theme'

function getInitialTheme(): Theme {
  if (typeof document === 'undefined') {
    return 'light'
  }

  const activeTheme = document.documentElement.getAttribute('data-theme')
  if (activeTheme === 'light' || activeTheme === 'dark') {
    return activeTheme
  }

  try {
    const storedTheme = localStorage.getItem(STORAGE_KEY)
    return storedTheme === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)

    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // The selected theme still applies when storage is unavailable.
    }
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((currentTheme) => (
      currentTheme === 'light' ? 'dark' : 'light'
    ))
  }, [])

  return { theme, toggleTheme }
}

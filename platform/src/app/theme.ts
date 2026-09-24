import { useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';
const KEY = 'itles_theme';

export function getTheme(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

export function setTheme(t: Theme) {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    // private mode: keep in memory only
  }
  document.documentElement.classList.toggle('dark', t === 'dark');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', t === 'dark' ? '#000000' : '#f6f6f7');
  window.dispatchEvent(new CustomEvent('itles-theme', { detail: t }));
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [t, setT] = useState<Theme>(getTheme);
  useEffect(() => {
    const f = (e: Event) => setT((e as CustomEvent<Theme>).detail);
    window.addEventListener('itles-theme', f);
    return () => window.removeEventListener('itles-theme', f);
  }, []);
  return [t, setTheme];
}

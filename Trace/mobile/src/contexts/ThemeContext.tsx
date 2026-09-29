import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { Appearance } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { LIGHT_THEME, DARK_THEME, ThemePalette } from '@/theme/palette';
import { THEME_STORAGE_KEY } from '@/config';
import type { ThemeMode } from '@/types';

interface ThemeContextType {
  mode: ThemeMode;
  setMode: (m: ThemeMode) => void;
  isDark: boolean;
  colors: ThemePalette;
}

const ThemeContext = createContext<ThemeContextType>({
  mode: 'system',
  setMode: () => {},
  isDark: false,
  colors: LIGHT_THEME,
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>('system');
  const [systemDark, setSystemDark] = useState(Appearance.getColorScheme() === 'dark');

  useEffect(() => {
    AsyncStorage.getItem(THEME_STORAGE_KEY).then((v) => {
      if (v === 'light' || v === 'dark' || v === 'system') setModeState(v);
    });
    const sub = Appearance.addChangeListener(({ colorScheme }) => setSystemDark(colorScheme === 'dark'));
    return () => sub.remove();
  }, []);

  const setMode = (m: ThemeMode) => {
    setModeState(m);
    AsyncStorage.setItem(THEME_STORAGE_KEY, m);
  };

  const isDark = mode === 'dark' || (mode === 'system' && systemDark);
  const colors = isDark ? DARK_THEME : LIGHT_THEME;

  return <ThemeContext.Provider value={{ mode, setMode, isDark, colors }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

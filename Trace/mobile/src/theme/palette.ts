import type { RiskLevel } from '@/types';

export type { RiskLevel };

export interface ThemePalette {
  background: string;
  foreground: string;
  card: string;
  cardForeground: string;
  primary: string;
  primaryForeground: string;
  secondary: string;
  secondaryForeground: string;
  muted: string;
  mutedForeground: string;
  accent: string;
  border: string;

  statusLow: string;
  statusLowBg: string;
  statusElevated: string;
  statusElevatedBg: string;
  statusHigh: string;
  statusHighBg: string;
  statusCritical: string;
  statusCriticalBg: string;
}

export const LIGHT_THEME: ThemePalette = {
  background: '#F5F3EF',
  foreground: '#18171A',
  card: '#FFFFFF',
  cardForeground: '#18171A',
  primary: '#1D3557',
  primaryForeground: '#FFFFFF',
  secondary: '#ECEAE5',
  secondaryForeground: '#454240',
  muted: '#ECEAE5',
  mutedForeground: '#8A8782',
  accent: '#1D3557',
  border: '#D9D6D0',

  statusLow: '#2A7845',
  statusLowBg: '#EAF4EE',
  statusElevated: '#B56B08',
  statusElevatedBg: '#FDF2E0',
  statusHigh: '#BE4C00',
  statusHighBg: '#FDEEE6',
  statusCritical: '#BA2020',
  statusCriticalBg: '#FDEAEA',
};

export const DARK_THEME: ThemePalette = {
  background: '#0E0E0D',
  foreground: '#E4E1DB',
  card: '#191917',
  cardForeground: '#E4E1DB',
  primary: '#4A90C4',
  primaryForeground: '#FFFFFF',
  secondary: '#242420',
  secondaryForeground: '#A8A5A0',
  muted: '#242420',
  mutedForeground: '#767370',
  accent: '#4A90C4',
  border: '#2C2C29',

  statusLow: '#3AAD62',
  statusLowBg: '#0D2419',
  statusElevated: '#D4901A',
  statusElevatedBg: '#281C05',
  statusHigh: '#E06520',
  statusHighBg: '#271305',
  statusCritical: '#E03535',
  statusCriticalBg: '#271010',
};

export function riskColor(theme: ThemePalette, risk: RiskLevel): { text: string; bg: string } {
  switch (risk) {
    case 'LOW':
    case 'NORMAL':
      return { text: theme.statusLow, bg: theme.statusLowBg };
    case 'ELEVATED':
      return { text: theme.statusElevated, bg: theme.statusElevatedBg };
    case 'HIGH':
      return { text: theme.statusHigh, bg: theme.statusHighBg };
    case 'CRITICAL':
      return { text: theme.statusCritical, bg: theme.statusCriticalBg };
  }
}

import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { TOKEN_KEY } from '@/config';

/** SecureStore is native-only; web uses localStorage so auth does not crash. */
export async function getStoredToken(): Promise<string | null> {
  if (Platform.OS === 'web') {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  }
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function setStoredToken(token: string | null): Promise<void> {
  if (Platform.OS === 'web') {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      // ignore quota / private mode
    }
    return;
  }
  if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
  else await SecureStore.deleteItemAsync(TOKEN_KEY);
}

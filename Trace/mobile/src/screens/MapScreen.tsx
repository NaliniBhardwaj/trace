import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, RefreshControl } from 'react-native';
import Svg, { Rect, Text as SvgText, Path } from 'react-native-svg';
import { Navigation, Users } from 'lucide-react-native';
import { useTheme } from '@/contexts/ThemeContext';
import { useLanguage } from '@/contexts/LanguageContext';
import { useOffline } from '@/contexts/OfflineContext';
import { api, ZoneResponse } from '@/api/client';
import { getZoneStatsLocal, seedPastWeekScansIfEmpty } from '@/db/sqlite';
import { Card } from '@/components/Card';
import { EmptyState } from '@/components/ScreenState';
import { RiskBadge } from '@/components/RiskBadge';
import { riskColor, RiskLevel } from '@/theme/palette';
import { ZONE_LAYOUT, FLOOR_LEVELS, SAFE_ROUTE_PATH } from '@/data/plant';

type LevelFilter = number | 'ALL';

export function MapScreen() {
  const { colors } = useTheme();
  const { t } = useLanguage();
  const { isOnline } = useOffline();
  const [zones, setZones] = useState<ZoneResponse[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRoute, setShowRoute] = useState(false);
  const [levelFilter, setLevelFilter] = useState<LevelFilter>('ALL');

  const loadLocal = useCallback(async () => {
    try {
      await seedPastWeekScansIfEmpty();
      const stats = await getZoneStatsLocal();
      const mapped: ZoneResponse[] = stats.map((s) => ({
        id: s.zone_code,
        code: s.zone_code,
        name: ZONE_LAYOUT[s.zone_code]?.label ?? s.zone_code,
        risk_level: s.risk_level,
        worker_count: s.worker_count,
        avg_ppm: s.avg_ppm,
        floor_level: ZONE_LAYOUT[s.zone_code]?.floor_level ?? 0,
        floor_label: ZONE_LAYOUT[s.zone_code]?.floor_label ?? 'GROUND',
        is_synthetic: true,
      }));
      setZones(mapped);
      setError(null);
    } catch {
      setError('Could not load zone data.');
    }
  }, []);

  const load = useCallback(async () => {
    if (isOnline) {
      try {
        const z = await api.zones();
        if (z.length > 0) {
          setZones(z);
          setError(null);
          return;
        }
      } catch {
        // fall through
      }
    }
    await loadLocal();
  }, [isOnline, loadLocal]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const floorOf = (z: ZoneResponse): number =>
    z.floor_level ?? ZONE_LAYOUT[z.code]?.floor_level ?? 0;

  const labelOfFloor = (level: number): string => {
    const meta = FLOOR_LEVELS.find((f) => f.level === level);
    if (!meta) return `${t('map_level')} ${level}`;
    return t(meta.labelKey as any) || meta.fallback;
  };

  const levelsPresent = useMemo(() => {
    const set = new Set<number>();
    zones.forEach((z) => set.add(floorOf(z)));
    Object.values(ZONE_LAYOUT).forEach((l) => set.add(l.floor_level));
    return Array.from(set).sort((a, b) => a - b);
  }, [zones]);

  const zonesForLevel = (level: number) =>
    Object.entries(ZONE_LAYOUT).filter(([, def]) => def.floor_level === level);

  const selectedZone = zones.find((z) => z.code === selected);
  const totalWorkers = zones.reduce((sum, z) => sum + (z.worker_count || 0), 0);

  const renderLevelStrip = (level: number, minHeight: number) => {
    const entries = zonesForLevel(level);
    const contentBottom = entries.reduce((max, [code, def]) => {
      const zoneData = zones.find((z) => z.code === code);
      return Math.max(max, (zoneData?.map_y ?? def.y) + def.h);
    }, 0);
    const height = Math.max(minHeight, contentBottom + 12);
    return (
      <View key={`lvl-${level}`} style={{ marginBottom: 12 }}>
        <Text style={{ color: colors.mutedForeground, fontSize: 12, fontWeight: '700', marginBottom: 6 }}>
          ── {labelOfFloor(level)} ──
        </Text>
        <Svg width="100%" height={height} viewBox={`0 0 360 ${height}`}>
          <Rect x={0} y={0} width={360} height={height} fill={colors.card} rx={8} />
          {entries.map(([code, def]) => {
            const zoneData = zones.find((z) => z.code === code);
            const risk = (zoneData?.risk_level as RiskLevel) ?? 'NORMAL';
            const c = riskColor(colors, risk);
            const isSelected = selected === code;
            const x = zoneData?.map_x ?? def.x;
            const y = zoneData?.map_y ?? def.y;
            return (
              <React.Fragment key={code}>
                <Rect
                  x={x}
                  y={y}
                  width={def.w}
                  height={def.h}
                  fill={c.bg}
                  stroke={isSelected ? colors.primary : c.text}
                  strokeWidth={isSelected ? 3 : 1.5}
                  rx={6}
                  onPress={() => setSelected(code)}
                />
                <SvgText
                  x={x + def.w / 2}
                  y={y + def.h / 2 - 4}
                  fill={c.text}
                  fontSize={11}
                  fontWeight="700"
                  textAnchor="middle"
                  onPress={() => setSelected(code)}
                >
                  {def.label.length > 14 ? def.label.slice(0, 12) + '…' : def.label}
                </SvgText>
                <SvgText
                  x={x + def.w / 2}
                  y={y + def.h / 2 + 12}
                  fill={c.text}
                  fontSize={10}
                  textAnchor="middle"
                  onPress={() => setSelected(code)}
                >
                  {risk === 'NORMAL' || risk === 'LOW' ? 'SAFE' : risk}
                </SvgText>
              </React.Fragment>
            );
          })}
          {showRoute && level === 0 && (
            <Path d={SAFE_ROUTE_PATH} stroke={colors.primary} strokeWidth={3} strokeDasharray="6,4" fill="none" />
          )}
        </Svg>
      </View>
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <View style={[styles.header, { borderColor: colors.border }]}>
        <Text style={[styles.title, { color: colors.foreground }]}>{t('map_title')}</Text>
        <Text style={[styles.subtitle, { color: colors.mutedForeground }]}>
          {t('map_live')} · {totalWorkers} {t('map_on_shift')}
        </Text>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={{ maxHeight: 48, flexShrink: 0, borderBottomWidth: 1, borderColor: colors.border }}
        contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 8, gap: 8, alignItems: 'center' }}
      >
        <TouchableOpacity
          onPress={() => setLevelFilter('ALL')}
          style={[
            styles.levelChip,
            {
              borderColor: colors.border,
              backgroundColor: levelFilter === 'ALL' ? colors.primary : colors.card,
            },
          ]}
        >
          <Text
            style={{
              color: levelFilter === 'ALL' ? '#fff' : colors.foreground,
              fontSize: 12,
              fontWeight: '600',
            }}
          >
            {t('map_all_levels')}
          </Text>
        </TouchableOpacity>
        {FLOOR_LEVELS.map((f) => (
          <TouchableOpacity
            key={f.level}
            onPress={() => setLevelFilter(f.level)}
            style={[
              styles.levelChip,
              {
                borderColor: colors.border,
                backgroundColor: levelFilter === f.level ? colors.primary : colors.card,
              },
            ]}
          >
            <Text
              style={{
                color: levelFilter === f.level ? '#fff' : colors.foreground,
                fontSize: 12,
                fontWeight: '600',
              }}
            >
              {t(f.labelKey as any) || f.fallback}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <ScrollView
        contentContainerStyle={{ padding: 16 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        {levelFilter === 'ALL'
          ? levelsPresent.map((lvl) => renderLevelStrip(lvl, 180))
          : renderLevelStrip(levelFilter, 220)}

        <TouchableOpacity
          style={[styles.routeToggle, { borderColor: colors.border, backgroundColor: colors.card }]}
          onPress={() => setShowRoute((s) => !s)}
        >
          <Navigation size={16} color={colors.primary} />
          <Text style={{ color: colors.foreground, marginLeft: 8, fontWeight: '600', fontSize: 13 }}>
            {t('map_show_route')}
          </Text>
        </TouchableOpacity>
        {showRoute && (
          <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 4, textAlign: 'center' }}>
            Suggested safer route — not a guaranteed safe route.
          </Text>
        )}

        {selectedZone && (
          <Card style={{ marginTop: 16 }}>
            <View style={styles.rowBetween}>
              <Text style={[styles.zoneName, { color: colors.foreground }]}>{selectedZone.name}</Text>
              <RiskBadge risk={(selectedZone.risk_level as RiskLevel) ?? 'NORMAL'} size="sm" />
            </View>
            <Text style={{ color: colors.mutedForeground, fontSize: 12, marginTop: 4 }}>
              {t('map_floor')}: {selectedZone.floor_label || labelOfFloor(floorOf(selectedZone))}
            </Text>
            <View style={[styles.rowBetween, { marginTop: 10 }]}>
              <View style={styles.metaRow}>
                <Users size={14} color={colors.mutedForeground} />
                <Text style={{ color: colors.mutedForeground, marginLeft: 6, fontSize: 12 }}>
                  {selectedZone.worker_count} {t('common_workers').toLowerCase()}
                </Text>
              </View>
              <Text style={{ color: colors.mutedForeground, fontSize: 12 }}>
                H₂S {selectedZone.avg_ppm.toFixed(1)} ppm
              </Text>
            </View>
            <Text style={{ color: colors.mutedForeground, fontSize: 11, marginTop: 6 }}>
              Risk from Safety Engine
              {selectedZone.is_synthetic ? ' · synthetic H₂S input' : ''}
              {selectedZone.updated_at
                ? ` · updated ${new Date(selectedZone.updated_at).toLocaleTimeString()}`
                : ''}
            </Text>
          </Card>
        )}

        {zones.length === 0 && (
          <View style={{ marginTop: 16 }}>
            <EmptyState title={t('map_empty')} body={error ?? undefined} />
          </View>
        )}

        <View style={styles.legendRow}>
          {(['NORMAL', 'ELEVATED', 'HIGH', 'CRITICAL'] as RiskLevel[]).map((r) => {
            const c = riskColor(colors, r);
            return (
              <View key={r} style={styles.legendItem}>
                <View style={[styles.legendDot, { backgroundColor: c.text }]} />
                <Text style={{ color: colors.mutedForeground, fontSize: 11 }}>
                  {r === 'NORMAL' || r === 'LOW' ? 'SAFE' : r}
                </Text>
              </View>
            );
          })}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingTop: 56, paddingHorizontal: 20, paddingBottom: 12, borderBottomWidth: 1 },
  title: { fontSize: 18, fontWeight: '700' },
  subtitle: { fontSize: 12, marginTop: 3 },
  levelChip: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  routeToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    marginTop: 14,
  },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  zoneName: { fontSize: 15, fontWeight: '700' },
  metaRow: { flexDirection: 'row', alignItems: 'center' },
  legendRow: { flexDirection: 'row', justifyContent: 'center', gap: 16, marginTop: 18 },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
});

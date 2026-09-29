import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, ActivityIndicator, RefreshControl,
} from 'react-native';
import { api } from '@/api/client';

/**
 * DEVELOPMENT/ADMIN tool — visualizes Phase 12 synthetic operational foundation
 * + Phase 12.2 cleaning priority + Phase 13 worker rotation optimizer (explainable decision-support).
 * Not certified safety guidance. Not a trained ML model.
 */
export function AIFoundationScreen({ onBack }: { onBack?: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scenarioType, setScenarioType] = useState('CLEANING_COMPETING_TASKS');
  const [types, setTypes] = useState<string[]>([]);
  const [scenario, setScenario] = useState<any>(null);
  const [features, setFeatures] = useState<any>(null);
  const [priority, setPriority] = useState<any>(null);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [selectedWorker, setSelectedWorker] = useState<string | null>(null);
  const [validation, setValidation] = useState<any>(null);
  const [distance, setDistance] = useState<any>(null);
  const seed = 42;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await api.aiScenarios();
      setTypes(list.scenario_types || []);
      const sc = await api.aiScenario(scenarioType, seed);
      setScenario(sc);
      const feat = await api.aiFeatures(scenarioType, seed);
      setFeatures(feat);
      const pri = await api.aiCleaningPriority(scenarioType, seed);
      setPriority(pri);
      setSelectedZone(sc.zones?.[0]?.zone_id || null);
      setSelectedWorker(sc.workers?.[0]?.worker_id || null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load AI foundation data');
      setScenario(null);
      setPriority(null);
    } finally {
      setLoading(false);
    }
  }, [scenarioType]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selectedWorker || !selectedZone) return;
    api.aiValidateAssignment({
      scenario_type: scenarioType, seed, worker_id: selectedWorker, zone_id: selectedZone,
    }).then(setValidation).catch(() => setValidation(null));
    api.aiDistance(selectedWorker, selectedZone, scenarioType, seed)
      .then(setDistance).catch(() => setDistance(null));
  }, [selectedWorker, selectedZone, scenarioType]);

  const zones = scenario?.zones || [];
  const workers = scenario?.workers || [];
  const critical = zones.filter((z: any) => z.risk_level === 'CRITICAL').length;
  const high = zones.filter((z: any) => z.risk_level === 'HIGH').length;
  const cleaning = (scenario?.cleaning_tasks || []).length;
  const elevated = workers.filter((w: any) => (w.cumulative_exposure_ppm_min || 0) > 100).length;
  const unavailable = workers.filter((w: any) => w.availability !== 'AVAILABLE').length;
  const restricted = zones.filter((z: any) =>
    z.evacuation_status === 'EVACUATED' || z.evacuation_status === 'EVACUATION_REQUIRED').length;
  const zone = zones.find((z: any) => z.zone_id === selectedZone);
  const worker = workers.find((w: any) => w.worker_id === selectedWorker);
  const zoneFeat = (features?.zone_features || []).find((z: any) => z.zone_id === selectedZone);
  const queue = priority?.queue || [];
  const recommended = priority?.recommended_next;

  return (
    <ScrollView style={styles.root} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
      <View style={styles.header}>
        {onBack ? (
          <TouchableOpacity onPress={onBack}><Text style={styles.back}>← Back</Text></TouchableOpacity>
        ) : null}
        <Text style={styles.title}>AI OPERATIONAL FOUNDATION</Text>
        <Text style={styles.sub}>Dev tool · synthetic data · explainable optimizer (not trained ML)</Text>
      </View>

      {error ? <Text style={styles.err}>{error}</Text> : null}
      {loading && !scenario ? <ActivityIndicator style={{ margin: 24 }} /> : null}

      {scenario ? (
        <>
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Scenario</Text>
            <Text style={styles.body}>Type: {scenario.scenario_type}</Text>
            <Text style={styles.body}>Seed: {scenario.seed}</Text>
            <Text style={styles.body}>ID: {scenario.scenario_id}</Text>
            <ScrollView horizontal style={{ marginTop: 8 }}>
              {(types.length ? types : [scenarioType]).map((t) => (
                <TouchableOpacity key={t} style={[styles.chip, t === scenarioType && styles.chipOn]} onPress={() => setScenarioType(t)}>
                  <Text style={styles.chipText}>{t}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Summary</Text>
            <Text style={styles.body}>Workers: {workers.length} · Zones: {zones.length}</Text>
            <Text style={styles.body}>Critical: {critical} · High: {high}</Text>
            <Text style={styles.body}>Cleaning tasks: {cleaning}</Text>
            <Text style={styles.body}>Elevated exposure workers: {elevated}</Text>
            <Text style={styles.body}>Unavailable: {unavailable} · Restricted/evac zones: {restricted}</Text>
          </View>

          {/* Phase 12.2 — Cleaning Priority */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>CLEANING PRIORITY</Text>
            <Text style={styles.sub}>Rank · Zone · Band · Execution · Workers</Text>
            {recommended ? (
              <Text style={[styles.body, { marginTop: 6, color: '#9cf' }]}>
                Next: {recommended.zone_id || '—'} ({recommended.execution_status || '—'}) · {recommended.note || ''}
              </Text>
            ) : null}
            {queue.length === 0 ? (
              <Text style={[styles.body, { marginTop: 8 }]}>No cleaning tasks in this scenario</Text>
            ) : (
              queue.map((item: any) => (
                <View key={item.task_id} style={styles.priorityRow}>
                  <Text style={styles.rank}>#{item.priority_rank}</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.prioTitle}>
                      {item.zone_code || item.zone_id} · {item.priority_band}
                    </Text>
                    <Text style={styles.body}>
                      Risk: {item.risk_level} · H₂S: {item.h2s_ppm} · Sev: {item.cleaning_severity}
                    </Text>
                    <Text style={[
                      styles.body,
                      { color: item.execution_status === 'ELIGIBLE' ? '#3c3' : '#f66', fontWeight: '700' },
                    ]}>
                      {item.execution_status}
                      {item.blocking_reasons?.length
                        ? ` · ${(item.blocking_reasons || []).join(', ')}`
                        : ''}
                    </Text>
                    <Text style={styles.body}>
                      Eligible workers: {item.eligible_worker_count ?? (item.eligible_workers || []).length}
                      {(item.eligible_workers || []).slice(0, 3).map((w: any) => ` ${w.employee_code || w.worker_id}`).join('')}
                    </Text>
                    {item.explanation ? (
                      <Text style={styles.mono}>{item.explanation}</Text>
                    ) : null}
                  </View>
                </View>
              ))
            )}
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Zone Inspector</Text>
            <ScrollView horizontal>
              {zones.map((z: any) => (
                <TouchableOpacity key={z.zone_id} style={[styles.chip, z.zone_id === selectedZone && styles.chipOn]} onPress={() => setSelectedZone(z.zone_id)}>
                  <Text style={styles.chipText}>{z.code || z.zone_id}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            {zone ? (
              <View style={{ marginTop: 8 }}>
                <Text style={styles.body}>{zone.name} · Risk: {zone.risk_level} · H₂S: {zone.h2s_ppm}</Text>
                <Text style={styles.body}>Cleaning: {String(zone.cleaning_required)} ({zone.cleaning_severity}) {zone.estimated_cleaning_duration_min}m</Text>
                <Text style={styles.body}>Evac: {zone.evacuation_status} · Cap: {zone.current_occupancy}/{zone.capacity}</Text>
                <Text style={styles.body}>Adjacent: {(zone.adjacent_zone_ids || []).join(', ')}</Text>
                {zoneFeat?.cleaning_priority_feature_vector ? (
                  <Text style={styles.mono}>{JSON.stringify(zoneFeat.cleaning_priority_feature_vector)}</Text>
                ) : null}
              </View>
            ) : null}
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Worker Inspector</Text>
            <ScrollView horizontal>
              {workers.slice(0, 12).map((w: any) => (
                <TouchableOpacity key={w.worker_id} style={[styles.chip, w.worker_id === selectedWorker && styles.chipOn]} onPress={() => setSelectedWorker(w.worker_id)}>
                  <Text style={styles.chipText}>{w.employee_code || w.worker_id}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            {worker ? (
              <View style={{ marginTop: 8 }}>
                <Text style={styles.body}>{worker.employee_code} · {worker.role} · {worker.availability}</Text>
                <Text style={styles.body}>Skills: {(worker.skills || []).join(', ')}</Text>
                <Text style={styles.body}>Zone: {worker.physical_zone_id} · Permit: {worker.permit_status}</Text>
                <Text style={styles.body}>Exposure cum: {worker.cumulative_exposure_ppm_min} · current: {worker.current_exposure_ppm_min}</Text>
                {distance ? (
                  <Text style={styles.body}>Distance to selected zone: {distance.reachable ? `${distance.distance} hops` : 'unreachable'}</Text>
                ) : null}
              </View>
            ) : null}
          </View>

          <View style={styles.card}>
            <Text style={styles.cardTitle}>Assignment Validation</Text>
            <Text style={styles.body}>{selectedWorker} → {selectedZone}</Text>
            {validation ? (
              <Text style={{ color: validation.allowed ? '#0a0' : '#c00', fontWeight: '700', marginTop: 6 }}>
                {validation.allowed ? 'VALID' : 'BLOCKED'} {(validation.reasons || []).join(', ')}
              </Text>
            ) : (
              <Text style={styles.sub}>Select worker and zone</Text>
            )}
          </View>
        </>
      ) : null}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0f1419' },
  header: { padding: 16, paddingTop: 48 },
  back: { color: '#6cf', marginBottom: 8 },
  title: { color: '#fff', fontSize: 18, fontWeight: '800' },
  sub: { color: '#8a9', fontSize: 12, marginTop: 4 },
  body: { color: '#cde', fontSize: 13 },
  err: { color: '#f66', padding: 16 },
  card: { backgroundColor: '#1a222c', marginHorizontal: 12, marginBottom: 12, padding: 12, borderRadius: 10 },
  cardTitle: { color: '#9cf', fontWeight: '700', marginBottom: 6 },
  chip: { backgroundColor: '#243040', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, marginRight: 6 },
  chipOn: { backgroundColor: '#2a6' },
  chipText: { color: '#fff', fontSize: 11 },
  mono: { color: '#8a9', fontSize: 10, marginTop: 6, fontFamily: 'monospace' },
  priorityRow: { flexDirection: 'row', marginTop: 10, borderTopWidth: 1, borderTopColor: '#2a3540', paddingTop: 8 },
  rank: { color: '#9cf', fontWeight: '800', fontSize: 16, width: 36 },
  prioTitle: { color: '#fff', fontWeight: '700', fontSize: 14 },
});

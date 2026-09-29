/**
 * Lightweight self-check for RSSI smoothing + deterministic DemoBLE.
 * Not a Jest suite — Phase 1 project has no jest config.
 */
import { RssiSmoother, signalFromRssi, confidenceFromObservations } from '../rssiProcessing';
import { DemoBLEService } from '../DemoBLEService';
import { resolveBeaconIdFromDevice, KNOWN_BEACON_IDS } from '../beaconConfig';

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

export function runRssiSelfCheck(): void {
  assert(signalFromRssi(-45) === 'VERY_STRONG', 'rssi -45');
  assert(signalFromRssi(-60) === 'STRONG', 'rssi -60');
  assert(signalFromRssi(-75) === 'MEDIUM', 'rssi -75');
  assert(signalFromRssi(-90) === 'WEAK', 'rssi -90');

  const c = confidenceFromObservations(-55, 5, true);
  assert(c > 0.5 && c <= 0.98, `confidence ${c}`);

  const s = new RssiSmoother();
  const now = Date.now();
  for (let i = 0; i < 4; i++) {
    s.add([{ beacon_id: 'BEACON-UNIT-A', rssi: -54 + i, timestamp: now + i * 100 }]);
  }
  const stable = s.selectStable(null);
  assert(stable !== null && stable!.beacon_id === 'BEACON-UNIT-A', 'stable select');

  s.add([
    { beacon_id: 'BEACON-UNIT-A', rssi: -55, timestamp: now + 500 },
    { beacon_id: 'BEACON-UNIT-B', rssi: -58, timestamp: now + 500 },
  ]);
  s.add([
    { beacon_id: 'BEACON-UNIT-A', rssi: -54, timestamp: now + 600 },
    { beacon_id: 'BEACON-UNIT-B', rssi: -57, timestamp: now + 600 },
  ]);
  s.add([
    { beacon_id: 'BEACON-UNIT-A', rssi: -53, timestamp: now + 700 },
    { beacon_id: 'BEACON-UNIT-B', rssi: -56, timestamp: now + 700 },
  ]);
  const stillA = s.selectStable('BEACON-UNIT-A');
  assert(stillA !== null && stillA!.beacon_id === 'BEACON-UNIT-A', 'hysteresis holds');

  console.log('rssiProcessing self-check OK');
}

export function runDeterministicDemoCheck(): void {
  // Same RSSI sequence every run
  assert(DemoBLEService.rssiFor('BEACON-UNIT-A', 0) === -54, 'A0');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-A', 1) === -56, 'A1');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-A', 2) === -55, 'A2');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-A', 3) === -53, 'A3');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-A', 4) === -55, 'A4');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-A', 5) === -54, 'A wraps');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-B', 0) === -62, 'B0');
  assert(DemoBLEService.rssiFor('BEACON-UNIT-B', 1) === -60, 'B1');

  const demo = new DemoBLEService();
  demo.resetDeterministicState();
  const seen: number[] = [];
  const unsub = demo.subscribe((beacons) => {
    if (beacons[0]) seen.push(beacons[0].rssi);
  });
  // Manually tick via advance + start
  void demo.startScanning().then(async () => {
    // first tick already ran in startScanning
    assert(seen.length >= 1, 'got observation');
    assert(seen[0] === -54, `first RSSI deterministic got ${seen[0]}`);
    await demo.stopScanning();
    unsub();
    demo.destroy();
    console.log('deterministic DemoBLE self-check OK');
  });
}

export function runBeaconIdCheck(): void {
  assert(KNOWN_BEACON_IDS.has('BEACON-UNIT-A'), 'known set');
  assert(
    resolveBeaconIdFromDevice({ localName: 'BEACON-UNIT-A', name: null }) === 'BEACON-UNIT-A',
    'exact localName',
  );
  assert(
    resolveBeaconIdFromDevice({ localName: null, name: 'SENTINEL-BEACON-PUMP' }) === 'BEACON-PUMP',
    'prefixed name',
  );
  assert(
    resolveBeaconIdFromDevice({ localName: 'RandomHeadphones', name: 'AirPods' }) === null,
    'unknown ignored',
  );
  console.log('beacon identification self-check OK');
}

export function runAllLocationSelfChecks(): void {
  runRssiSelfCheck();
  runBeaconIdCheck();
  runDeterministicDemoCheck();
}

if (typeof require !== 'undefined' && typeof module !== 'undefined' && require.main === module) {
  runAllLocationSelfChecks();
}

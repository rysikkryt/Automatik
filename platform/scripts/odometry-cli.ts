/**
 * Runs the production odometry code on tracks produced elsewhere (Python simulator, real datasets).
 * stdin: JSON array of { profile: {chassis, rotatingUpper, category}, fixes: [{t, lat, lon, speedKmh, hdop, sats, accM}] }
 * stdout: JSON array of { km, transportKm, used, rejected, outliers, naiveKm }
 */
import { naiveDistanceKm, robustDistance, type Fix, type MachineProfile } from '../server/domain/odometry.js';

const chunks: Buffer[] = [];
// optional per-job `override` lets validation scripts sweep parameters
process.stdin.on('data', (c) => chunks.push(Buffer.from(c)));
process.stdin.on('end', () => {
  const jobs = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Array<{ profile: MachineProfile; fixes: Fix[]; override?: Record<string, unknown> }>;
  const out = jobs.map((j) => ({ ...robustDistance(j.fixes, j.profile, j.override as any), naiveKm: naiveDistanceKm(j.fixes) }));
  process.stdout.write(JSON.stringify(out));
});

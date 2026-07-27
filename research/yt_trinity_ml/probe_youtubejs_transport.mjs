#!/usr/bin/env node

/**
 * Probe caption and audio transports that were not exercised by the original
 * yt-dlp / youtube-transcript-api harvest.  The probe is deliberately small:
 * three channel representatives plus one historical positive control.
 *
 * A transport passes only when it returns non-empty timestamped transcript
 * content or a non-empty range of a public audio stream.  Metadata alone is
 * never counted as recovery.
 */

import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { Innertube, Platform } from 'youtubei.js';

const OUTPUT = path.resolve(process.argv[2] ?? 'artifact/youtubejs');
const MAX_AUDIO_BYTES = 1024 * 1024;

const SAMPLES = [
  { channel_slug: 'chartbro', video_id: '0h9lpMUBSlE' },
  { channel_slug: 'swipalnam', video_id: '-Tp2fhvVVGM' },
  { channel_slug: 'indicator_sensei', video_id: '2U0s_i07vMY' },
  { channel_slug: 'known_previous_success', video_id: 'F6wDs1HRTSo' },
];

const CLIENTS = ['WEB', 'ANDROID', 'TV'];

// Current YouTube.js requires an explicit interpreter for player JavaScript.
// The probe runs repository-owned code in an isolated GitHub runner.
Platform.shim.eval = async (data) => new Function(data.output)();

function errorRecord(error) {
  const value = error instanceof Error ? error : new Error(String(error));
  return {
    name: value.name,
    message: value.message,
    stack_tail: String(value.stack ?? '').split('\n').slice(-8).join('\n'),
  };
}

function plain(value) {
  if (value == null) return value;
  try {
    if (typeof value.toJSON === 'function') return value.toJSON();
  } catch {
    // Fall through to JSON serialization.
  }
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    return { serialization_failed: true, type: typeof value };
  }
}

function textValue(value) {
  if (typeof value === 'string') return value;
  if (!value || typeof value !== 'object') return '';
  if (typeof value.text === 'string') return value.text;
  if (typeof value.toString === 'function') {
    const rendered = value.toString();
    if (rendered !== '[object Object]') return rendered;
  }
  return '';
}

function collectTranscriptSegments(root) {
  const rows = [];
  const seen = new Set();

  function visit(node) {
    if (node == null) return;
    if (Array.isArray(node)) {
      for (const item of node) visit(item);
      return;
    }
    if (typeof node !== 'object' || seen.has(node)) return;
    seen.add(node);

    const start = node.start_ms ?? node.startMs ?? node.start_time_ms ?? node.start_time ?? node.start;
    const end = node.end_ms ?? node.endMs ?? node.end_time_ms ?? node.end_time ?? node.end;
    const duration = node.duration_ms ?? node.durationMs ?? node.duration;
    const snippet = textValue(node.snippet ?? node.text ?? node.content ?? node.runs);

    if (snippet && (start !== undefined || end !== undefined || duration !== undefined)) {
      rows.push({
        start_ms: start ?? null,
        end_ms: end ?? null,
        duration_ms: duration ?? null,
        text: snippet,
      });
    }

    for (const value of Object.values(node)) visit(value);
  }

  visit(root);

  const deduped = [];
  const keys = new Set();
  for (const row of rows) {
    const key = `${row.start_ms}|${row.end_ms}|${row.duration_ms}|${row.text}`;
    if (!keys.has(key)) {
      keys.add(key);
      deduped.push(row);
    }
  }
  return deduped;
}

async function readAudioProbe(info) {
  const stream = await info.download({
    type: 'audio',
    quality: 'bestefficiency',
    format: 'any',
    range: { start: 0, end: MAX_AUDIO_BYTES - 1 },
  });
  const reader = stream.getReader();
  let bytes = 0;
  let chunks = 0;
  try {
    while (bytes < MAX_AUDIO_BYTES) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        bytes += value.byteLength;
        chunks += 1;
      }
    }
  } finally {
    await reader.cancel('transport probe complete').catch(() => undefined);
  }
  return { bytes, chunks };
}

async function buildClients() {
  const clients = new Map();
  for (const clientType of CLIENTS) {
    try {
      const started = Date.now();
      const innertube = await Innertube.create({
        lang: 'ko',
        location: 'KR',
        client_type: clientType,
        retrieve_player: true,
        generate_session_locally: true,
        enable_session_cache: false,
        fast_fail: false,
      });
      clients.set(clientType, innertube);
      console.error(`session ${clientType} ready in ${Date.now() - started}ms`);
    } catch (error) {
      console.error(`session ${clientType} failed: ${errorRecord(error).message}`);
      clients.set(clientType, { __session_error: errorRecord(error) });
    }
  }
  return clients;
}

async function main() {
  await mkdir(OUTPUT, { recursive: true });
  const clients = await buildClients();
  const result = {
    schema_version: 1,
    generated_at_utc: new Date().toISOString(),
    runtime: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      github_run_id: process.env.GITHUB_RUN_ID ?? null,
      github_sha: process.env.GITHUB_SHA ?? null,
    },
    clients: CLIENTS,
    samples: [],
  };

  for (const sample of SAMPLES) {
    const sampleResult = { ...sample, attempts: [] };
    let recovered = false;

    for (const clientType of CLIENTS) {
      const innertube = clients.get(clientType);
      const attempt = {
        client_type: clientType,
        metadata_ok: false,
        transcript_ok: false,
        transcript_segment_count: 0,
        audio_ok: false,
        audio_probe_bytes: 0,
      };
      const started = Date.now();

      if (innertube?.__session_error) {
        attempt.session_error = innertube.__session_error;
        sampleResult.attempts.push(attempt);
        continue;
      }

      try {
        const info = await innertube.getInfo(sample.video_id);
        attempt.metadata_ok = true;
        attempt.title = info.basic_info?.title ?? null;
        attempt.author = info.basic_info?.author ?? info.basic_info?.channel?.name ?? null;
        attempt.duration_seconds = info.basic_info?.duration ?? null;
        attempt.playability_status = info.playability_status?.status ?? null;

        try {
          const transcriptInfo = await info.getTranscript();
          const page = plain(transcriptInfo.page ?? transcriptInfo.transcript ?? transcriptInfo);
          const segments = collectTranscriptSegments(page);
          attempt.transcript_languages = Array.from(transcriptInfo.languages ?? []);
          attempt.transcript_selected_language = transcriptInfo.selectedLanguage ?? null;
          attempt.transcript_segment_count = segments.length;
          attempt.transcript_ok = segments.length > 0;
          await writeFile(
            path.join(OUTPUT, `${sample.video_id}.${clientType}.transcript.json`),
            JSON.stringify({ sample, client_type: clientType, segments, page }, null, 2),
            'utf8',
          );
          recovered ||= attempt.transcript_ok;
        } catch (error) {
          attempt.transcript_error = errorRecord(error);
        }

        try {
          const audio = await readAudioProbe(info);
          attempt.audio_probe_bytes = audio.bytes;
          attempt.audio_probe_chunks = audio.chunks;
          attempt.audio_ok = audio.bytes > 0;
          recovered ||= attempt.audio_ok;
        } catch (error) {
          attempt.audio_error = errorRecord(error);
        }
      } catch (error) {
        attempt.metadata_error = errorRecord(error);
      }

      attempt.elapsed_ms = Date.now() - started;
      sampleResult.attempts.push(attempt);
      console.error(
        `${sample.video_id} ${clientType}: metadata=${attempt.metadata_ok} ` +
          `transcript=${attempt.transcript_segment_count} audio=${attempt.audio_probe_bytes}`,
      );

      // Once either real transcript segments or an audio range has been recovered,
      // later client profiles add no decision value for this video.
      if (recovered) break;
    }

    sampleResult.recovered = recovered;
    result.samples.push(sampleResult);
  }

  result.recovered_video_count = result.samples.filter((sample) => sample.recovered).length;
  result.transcript_recovered_video_count = result.samples.filter((sample) =>
    sample.attempts.some((attempt) => attempt.transcript_ok),
  ).length;
  result.audio_recovered_video_count = result.samples.filter((sample) =>
    sample.attempts.some((attempt) => attempt.audio_ok),
  ).length;
  result.decision = result.recovered_video_count > 0 ? 'TRANSPORT_RECOVERED' : 'NO_RECOVERY';

  const destination = path.join(OUTPUT, 'probe.json');
  await writeFile(destination, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result));
}

main().catch(async (error) => {
  await mkdir(OUTPUT, { recursive: true });
  const payload = {
    schema_version: 1,
    generated_at_utc: new Date().toISOString(),
    decision: 'PROBE_FATAL',
    fatal_error: errorRecord(error),
  };
  await writeFile(path.join(OUTPUT, 'probe.json'), `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  console.error(error);
  process.exitCode = 1;
});
